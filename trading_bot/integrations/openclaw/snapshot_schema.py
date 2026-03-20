from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import csv
import json
import math

import pandas as pd

from trading_bot.config import load_raw_config, resolve_relative_path
from trading_bot.integrations.openclaw.event_flags import (
    classify_action_bias,
    classify_headline_risk,
    detect_event_flags,
    score_event_risk,
)
from trading_bot.integrations.openclaw.regime import (
    choose_approval_policy,
    classify_event_regime,
    daily_report_priority,
)
from trading_bot.integrations.openclaw.relevance_parser import article_is_relevant, infer_relevance, normalize_symbol

PROVIDER_NAME = 'openclaw_v3'
HISTORY_FIELDNAMES = [
    'timestamp', 'symbol', 'score', 'confidence', 'source', 'summary',
    'relevance_score', 'event_risk_score', 'contradiction_score',
    'headline_risk', 'action_bias', 'source_count', 'thesis', 'event_flags',
    'trading_stance', 'event_regime', 'approval_policy',
]
SOURCE_QUALITY = {
    'reuters': 1.0,
    'bloomberg': 0.97,
    'wsj': 0.94,
    'financial times': 0.94,
    'the information': 0.9,
    'cnbc': 0.82,
    'marketwatch': 0.8,
    'benzinga': 0.74,
    'seeking alpha': 0.72,
    'unknown': 0.6,
}
EVENT_RISK_TEXT = {
    'low': 0.25,
    'medium': 0.55,
    'high': 0.85,
    'critical': 1.0,
}
HORIZON_WEIGHT = {
    'intraday': 1.0,
    'short_term': 0.95,
    'near_term': 0.9,
    'swing': 0.85,
    'medium_term': 0.75,
    'long_term': 0.65,
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()



def _read_json_or_jsonl(path: Path) -> Any:
    text = path.read_text(encoding='utf-8').strip()
    if not text:
        return {'articles': []}
    if path.suffix.lower() == '.jsonl':
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
        return {'articles': rows}
    return json.loads(text)



def load_openclaw_bundle(path: Path) -> dict[str, Any]:
    payload = _read_json_or_jsonl(path)
    if isinstance(payload, list):
        return {'generated_at': _utc_now(), 'articles': payload}
    if 'articles' in payload and isinstance(payload['articles'], list):
        return payload
    if 'items' in payload and isinstance(payload['items'], list):
        return {'generated_at': payload.get('generated_at') or payload.get('timestamp') or _utc_now(), 'articles': payload['items']}
    raise ValueError(f'Unsupported OpenClaw bundle shape: {path}')



def _ensure_history_schema(path: Path) -> None:
    if not path.exists():
        return
    header = path.read_text(encoding='utf-8').splitlines()[0].strip().split(',')
    if all(field in header for field in HISTORY_FIELDNAMES):
        return
    df = pd.read_csv(path)
    for field in HISTORY_FIELDNAMES:
        if field not in df.columns:
            df[field] = '' if field in {'summary', 'headline_risk', 'action_bias', 'thesis', 'event_flags', 'source', 'trading_stance', 'event_regime', 'approval_policy'} else 0.0
    df = df[HISTORY_FIELDNAMES]
    df.to_csv(path, index=False)



def _append_history_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        _ensure_history_schema(path)
    exists = path.exists()
    with path.open('a', encoding='utf-8', newline='') as fh:
        writer = csv.DictWriter(fh, fieldnames=HISTORY_FIELDNAMES)
        if not exists:
            writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, '') for field in HISTORY_FIELDNAMES})



def _load_alias_map(raw_cfg: dict[str, Any], config_path: Path) -> dict[str, list[str]]:
    bridge_cfg = raw_cfg.get('openclaw_bridge', {}) or {}
    path_value = bridge_cfg.get('symbol_aliases_path')
    if not path_value:
        return {}
    path = Path(resolve_relative_path(config_path, path_value))
    if not path.exists():
        return {}
    if path.suffix.lower() in {'.json', '.json5'}:
        payload = json.loads(path.read_text(encoding='utf-8'))
        return {str(k).upper(): [str(x) for x in (v or [])] for k, v in (payload or {}).items()}
    aliases: dict[str, list[str]] = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or ':' not in line:
            continue
        key, rhs = line.split(':', 1)
        aliases[key.strip().upper()] = [part.strip() for part in rhs.split(',') if part.strip()]
    return aliases



def _bridge_paths(raw_cfg: dict[str, Any], config_path: Path) -> dict[str, Path]:
    bridge_cfg = raw_cfg.get('openclaw_bridge', {}) or {}
    runtime_root = Path(resolve_relative_path(config_path, bridge_cfg.get('runtime_dir', 'runtime/openclaw')))
    return {
        'runtime_root': runtime_root,
        'raw_articles': runtime_root / 'raw_articles',
        'snapshots': runtime_root / 'snapshots',
        'latest': runtime_root / 'latest',
    }



def _parse_dt(value: Any) -> datetime | None:
    if value in (None, ''):
        return None
    try:
        ts = pd.Timestamp(value)
        if ts.tzinfo is None:
            ts = ts.tz_localize('UTC')
        else:
            ts = ts.tz_convert('UTC')
        return ts.to_pydatetime()
    except Exception:
        return None



def _source_quality(source: str) -> float:
    src = (source or 'unknown').strip().lower()
    if src in SOURCE_QUALITY:
        return SOURCE_QUALITY[src]
    for key, value in SOURCE_QUALITY.items():
        if key != 'unknown' and key in src:
            return value
    return SOURCE_QUALITY['unknown']



def _impact_multiplier(horizon: str | None) -> float:
    key = str(horizon or 'near_term').strip().lower()
    return HORIZON_WEIGHT.get(key, 0.8)



def _event_risk_value(value: Any) -> float | None:
    if value in (None, ''):
        return None
    if isinstance(value, (int, float)):
        return max(0.0, min(1.0, float(value)))
    return EVENT_RISK_TEXT.get(str(value).strip().lower())



def _normalize_article(article: dict[str, Any], *, symbol: str, alias_map: dict[str, list[str]] | None, as_of: str) -> dict[str, Any]:
    normalized = dict(article or {})
    normalized['symbol'] = symbol
    normalized['title'] = str(normalized.get('title') or '')
    normalized['summary'] = str(normalized.get('summary') or normalized.get('body') or '')
    normalized['company'] = str(normalized.get('company') or symbol)
    normalized['source'] = str(normalized.get('source') or normalized.get('publisher') or 'unknown')
    normalized['relevance_score'] = infer_relevance(normalized, symbol=symbol, alias_map=alias_map)

    sentiment_score = normalized.get('sentiment_score')
    if sentiment_score is None and isinstance(normalized.get('sentiment'), dict):
        sentiment_score = normalized['sentiment'].get('score')
    normalized['sentiment_score'] = float(sentiment_score or 0.0)

    confidence = normalized.get('confidence')
    if confidence is None and isinstance(normalized.get('sentiment'), dict):
        confidence = normalized['sentiment'].get('confidence')
    if confidence is None:
        confidence = max(0.35, min(1.0, 0.35 + abs(float(normalized['sentiment_score'])) * 0.5))
    normalized['confidence'] = max(0.0, min(1.0, float(confidence)))

    flags = normalized.get('event_flags') or []
    if isinstance(flags, str):
        flags = [part.strip() for part in flags.replace(';', ',').split(',') if part.strip()]
    merged_flags = sorted(set(list(flags) + detect_event_flags([f"{normalized['title']} {normalized['summary']}"])))
    normalized['event_flags'] = merged_flags

    published_at = _parse_dt(normalized.get('published_at') or normalized.get('timestamp'))
    normalized['published_at'] = published_at.isoformat() if published_at else as_of
    as_of_dt = _parse_dt(as_of) or datetime.now(timezone.utc)
    age_hours = max(0.0, (as_of_dt - (published_at or as_of_dt)).total_seconds() / 3600.0)
    recency_weight = max(0.35, min(1.0, math.exp(-age_hours / 72.0)))
    normalized['recency_weight'] = round(recency_weight * _impact_multiplier(normalized.get('impact_horizon')), 4)
    normalized['source_quality'] = round(_source_quality(normalized['source']), 4)

    explicit_risk = _event_risk_value(normalized.get('event_risk'))
    risk_score = score_event_risk(merged_flags, explicit_event_risk=explicit_risk)
    normalized['event_risk_score'] = round(risk_score, 4)

    action_bias = str(normalized.get('action_bias') or '').strip().lower()
    if action_bias not in {'bullish', 'bearish', 'neutral', 'mixed'}:
        if normalized['sentiment_score'] >= 0.15:
            action_bias = 'bullish'
        elif normalized['sentiment_score'] <= -0.15:
            action_bias = 'bearish'
        else:
            action_bias = 'neutral'
    normalized['action_bias'] = action_bias
    normalized['thesis'] = str(normalized.get('thesis') or normalized.get('title') or '')
    normalized['article_weight'] = round(
        max(0.05, normalized['relevance_score'] * max(0.1, normalized['confidence']) * normalized['source_quality'] * normalized['recency_weight']),
        4,
    )
    return normalized



def _group_articles(bundle: dict[str, Any], *, alias_map: dict[str, list[str]], watchlist: list[str], min_relevance: float, as_of: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for raw_article in bundle.get('articles', []):
        article = dict(raw_article or {})
        symbol = normalize_symbol(article.get('symbol') or article.get('ticker'))
        if symbol is None:
            continue
        if watchlist and symbol not in watchlist:
            continue
        if not article_is_relevant(article, symbol=symbol, min_relevance=min_relevance, alias_map=alias_map):
            continue
        grouped[symbol].append(_normalize_article(article, symbol=symbol, alias_map=alias_map, as_of=as_of))
    return grouped



def export_snapshot_contract(*, symbol: str, as_of: str, articles: list[dict[str, Any]], company: str | None = None) -> dict[str, Any]:
    if not articles:
        return {
            'as_of': as_of,
            'symbol': symbol,
            'company': company or symbol,
            'relevance_score': 0.0,
            'sentiment_score': 0.0,
            'confidence': 0.0,
            'source_count': 0,
            'headline_risk': 'low',
            'event_flags': [],
            'event_risk_score': 0.0,
            'contradiction_score': 0.0,
            'action_bias': 'neutral',
            'source_quality': 0.0,
            'trading_stance': 'neutral',
            'event_regime': 'normal',
            'approval_policy': 'auto',
            'daily_report_priority': 'normal',
            'thesis': '',
            'articles': [],
        }
    weights = [max(0.05, float(a.get('article_weight') or 0.0)) for a in articles]
    weight_sum = max(sum(weights), 1e-9)
    weighted_score = sum(float(a.get('sentiment_score') or 0.0) * w for a, w in zip(articles, weights)) / weight_sum
    weighted_conf = sum(float(a.get('confidence') or 0.0) * w for a, w in zip(articles, weights)) / weight_sum
    avg_rel = sum(float(a.get('relevance_score') or 0.0) * w for a, w in zip(articles, weights)) / weight_sum
    source_quality = sum(float(a.get('source_quality') or 0.0) * w for a, w in zip(articles, weights)) / weight_sum
    article_risks = [float(a.get('event_risk_score') or 0.0) for a in articles]
    weighted_risk = sum(r * w for r, w in zip(article_risks, weights)) / weight_sum
    max_risk = max(article_risks) if article_risks else 0.0
    event_risk_score = round(max(weighted_risk, max_risk * 0.85), 4)
    signs = [1 if float(a.get('sentiment_score') or 0.0) > 0.05 else -1 if float(a.get('sentiment_score') or 0.0) < -0.05 else 0 for a in articles]
    directional_balance = abs(sum(s * w for s, w in zip(signs, weights))) / weight_sum
    contradiction_score = round(max(0.0, min(1.0, 1.0 - directional_balance)), 4)
    flags = sorted({flag for a in articles for flag in (a.get('event_flags') or [])})
    bias_votes = {'bullish': 0.0, 'bearish': 0.0, 'neutral': 0.0, 'mixed': 0.0}
    for article, weight in zip(articles, weights):
        bias_votes[str(article.get('action_bias') or 'neutral')] = bias_votes.get(str(article.get('action_bias') or 'neutral'), 0.0) + weight
    action_bias = max(bias_votes, key=bias_votes.get)
    if action_bias == 'neutral':
        action_bias = classify_action_bias(float(weighted_score), contradiction_score)
    if contradiction_score >= 0.65:
        action_bias = 'mixed'
    headline_risk = classify_headline_risk(flags, avg_confidence=float(weighted_conf), abs_sentiment=abs(float(weighted_score)), event_risk_score=event_risk_score)
    if event_risk_score >= 0.85:
        trading_stance = 'block_new_entries'
    elif contradiction_score >= 0.65:
        trading_stance = 'caution_mixed_news'
    elif action_bias == 'bullish':
        trading_stance = 'favor_long'
    elif action_bias == 'bearish':
        trading_stance = 'favor_short'
    else:
        trading_stance = 'neutral'
    event_regime = classify_event_regime(
        event_flags=flags,
        event_risk_score=event_risk_score,
        contradiction_score=contradiction_score,
        action_bias=action_bias,
        headline_risk=headline_risk,
    )
    approval_policy = choose_approval_policy(
        event_regime=event_regime,
        trading_stance=trading_stance,
        event_risk_score=event_risk_score,
        contradiction_score=contradiction_score,
        action_bias=action_bias,
    )
    report_priority = daily_report_priority(
        event_regime=event_regime,
        approval_policy=approval_policy,
        event_risk_score=event_risk_score,
        contradiction_score=contradiction_score,
    )
    rendered_articles = [
        {
            'id': str(a.get('id') or f"{symbol}:{idx}"),
            'published_at': str(a.get('published_at') or a.get('timestamp') or as_of),
            'source': str(a.get('source') or 'unknown'),
            'title': str(a.get('title') or ''),
            'summary': str(a.get('summary') or ''),
            'relevance_score': round(float(a.get('relevance_score') or 0.0), 4),
            'sentiment_score': round(float(a.get('sentiment_score') or 0.0), 4),
            'confidence': round(float(a.get('confidence') or 0.0), 4),
            'event_flags': list(a.get('event_flags') or []),
            'event_risk_score': round(float(a.get('event_risk_score') or 0.0), 4),
            'action_bias': str(a.get('action_bias') or 'neutral'),
            'impact_horizon': str(a.get('impact_horizon') or 'near_term'),
            'source_quality': round(float(a.get('source_quality') or 0.0), 4),
            'recency_weight': round(float(a.get('recency_weight') or 0.0), 4),
            'url': str(a.get('url') or a.get('link') or ''),
            'thesis': str(a.get('thesis') or a.get('title') or ''),
        }
        for idx, a in enumerate(articles)
    ]
    thesis = str(articles[0].get('thesis') or articles[0].get('title') or '') if len(articles) == 1 else f"{len(articles)} articles; {action_bias} bias; {headline_risk} headline risk"
    return {
        'as_of': as_of,
        'symbol': symbol,
        'company': company or str(articles[0].get('company') or symbol),
        'relevance_score': round(float(avg_rel), 4),
        'sentiment_score': round(float(weighted_score), 4),
        'confidence': round(float(weighted_conf), 4),
        'source_count': len({str(a.get('source') or 'unknown') for a in articles}),
        'headline_risk': headline_risk,
        'event_flags': flags,
        'event_risk_score': event_risk_score,
        'contradiction_score': contradiction_score,
        'action_bias': action_bias,
        'source_quality': round(float(source_quality), 4),
        'trading_stance': trading_stance,
        'event_regime': event_regime,
        'approval_policy': approval_policy,
        'daily_report_priority': report_priority,
        'thesis': thesis,
        'articles': rendered_articles,
    }



def ingest_openclaw_bundle(config_path: Path, bundle_path: Path, *, label: str = 'openclaw_bundle') -> dict[str, Any]:
    raw_cfg = load_raw_config(config_path)
    watchlist = [str(x).upper() for x in ((raw_cfg.get('universe') or {}).get('symbols') or [])]
    bridge_cfg = raw_cfg.get('openclaw_bridge', {}) or {}
    min_relevance = float(bridge_cfg.get('min_relevance', 0.55))
    bundle = load_openclaw_bundle(bundle_path)
    as_of = str(bundle.get('generated_at') or bundle.get('timestamp') or _utc_now())
    sent_cfg = raw_cfg.get('sentiment', {}) or {}
    current_json_path = Path(resolve_relative_path(config_path, sent_cfg.get('current_json_path', '../data/current_sentiment.json')))
    history_csv_path = Path(resolve_relative_path(config_path, sent_cfg.get('path', '../data/sentiment_snapshots.csv')))
    alias_map = _load_alias_map(raw_cfg, config_path)
    paths = _bridge_paths(raw_cfg, config_path)
    grouped = _group_articles(bundle, alias_map=alias_map, watchlist=watchlist, min_relevance=min_relevance, as_of=as_of)

    current_payload: dict[str, Any] = {}
    history_rows: list[dict[str, Any]] = []
    contracts: list[dict[str, Any]] = []
    for symbol, articles in sorted(grouped.items()):
        contract = export_snapshot_contract(symbol=symbol, as_of=as_of, articles=articles)
        contracts.append(contract)
        current_payload[symbol] = {
            'timestamp': as_of,
            'sentiment_score': contract['sentiment_score'],
            'confidence': contract['confidence'],
            'provider': PROVIDER_NAME,
            'summary': contract['articles'][0]['title'] if contract['articles'] else '',
            'headline_count': len(contract['articles']),
            'relevance_score': contract['relevance_score'],
            'event_flags': contract['event_flags'],
            'headline_risk': contract['headline_risk'],
            'source_count': contract['source_count'],
            'event_risk_score': contract['event_risk_score'],
            'contradiction_score': contract['contradiction_score'],
            'action_bias': contract['action_bias'],
            'thesis': contract['thesis'],
            'trading_stance': contract['trading_stance'],
            'event_regime': contract['event_regime'],
            'approval_policy': contract['approval_policy'],
            'daily_report_priority': contract['daily_report_priority'],
        }
        history_rows.append({
            'timestamp': as_of,
            'symbol': symbol,
            'score': contract['sentiment_score'],
            'confidence': contract['confidence'],
            'source': PROVIDER_NAME,
            'summary': contract['articles'][0]['title'] if contract['articles'] else '',
            'relevance_score': contract['relevance_score'],
            'event_risk_score': contract['event_risk_score'],
            'contradiction_score': contract['contradiction_score'],
            'headline_risk': contract['headline_risk'],
            'action_bias': contract['action_bias'],
            'source_count': contract['source_count'],
            'thesis': contract['thesis'],
            'event_flags': '|'.join(contract['event_flags']),
            'trading_stance': contract['trading_stance'],
            'event_regime': contract['event_regime'],
            'approval_policy': contract['approval_policy'],
        })

    current_json_path.parent.mkdir(parents=True, exist_ok=True)
    current_json_path.write_text(json.dumps(current_payload, indent=2), encoding='utf-8')
    if history_rows:
        _append_history_csv(history_csv_path, history_rows)

    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    raw_archive = paths['raw_articles'] / f"{label}_{Path(bundle_path).stem}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    raw_archive.write_text(json.dumps(bundle, indent=2), encoding='utf-8')
    snapshot_payload = {
        'generated_at': as_of,
        'provider': PROVIDER_NAME,
        'label': label,
        'contracts': contracts,
        'source_bundle': str(bundle_path),
    }
    snapshot_file = paths['snapshots'] / f"snapshot_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    snapshot_file.write_text(json.dumps(snapshot_payload, indent=2), encoding='utf-8')
    (paths['latest'] / 'current.json').write_text(json.dumps(snapshot_payload, indent=2), encoding='utf-8')
    return {
        'generated_at': as_of,
        'symbols': sorted(grouped.keys()),
        'contracts_written': len(contracts),
        'history_rows_written': len(history_rows),
        'current_json_path': str(current_json_path),
        'history_csv_path': str(history_csv_path),
        'snapshot_file': str(snapshot_file),
        'raw_archive': str(raw_archive),
    }
