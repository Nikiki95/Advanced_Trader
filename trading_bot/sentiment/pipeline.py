from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import csv
import json
from typing import Any

from trading_bot.config import load_raw_config, resolve_relative_path
from trading_bot.live.session import resolve_session
from trading_bot.sentiment.news import fetch_headlines


POSITIVE_KEYWORDS = ['beat', 'beats', 'growth', 'upgrade', 'surge', 'rally', 'strong', 'bullish', 'buy', 'profit']
NEGATIVE_KEYWORDS = ['miss', 'downgrade', 'drop', 'weak', 'bearish', 'sell', 'plunge', 'lawsuit', 'loss', 'decline']


def score_headlines(headlines: list[dict | Any]) -> tuple[float, float, str]:
    if not headlines:
        return 0.0, 0.0, 'No recent headlines'
    score = 0
    texts: list[str] = []
    for item in headlines:
        title = getattr(item, 'title', None) if not isinstance(item, dict) else item.get('title', '')
        summary = getattr(item, 'summary', None) if not isinstance(item, dict) else item.get('summary', '')
        text = f"{title or ''} {summary or ''}".lower()
        texts.append(title or '')
        for word in POSITIVE_KEYWORDS:
            score += text.count(word)
        for word in NEGATIVE_KEYWORDS:
            score -= text.count(word)
    normalized = max(-1.0, min(1.0, score / max(len(headlines) * 2, 1)))
    confidence = min(1.0, 0.35 + 0.1 * len(headlines) + min(abs(normalized), 1.0) * 0.35)
    return round(normalized, 4), round(confidence, 4), texts[0] if texts else 'No summary'


def _append_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ['timestamp', 'symbol', 'score', 'confidence', 'source', 'summary']
    if path.exists():
        header = path.read_text(encoding='utf-8').splitlines()[0].strip().split(',')
        if 'summary' not in header:
            df = __import__('pandas').read_csv(path)
            if 'summary' not in df.columns:
                df['summary'] = ''
            df = df[fieldnames]
            df.to_csv(path, index=False)
    exists = path.exists()
    with open(path, 'a', encoding='utf-8', newline='') as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        if not exists:
            writer.writeheader()
        for row in rows:
            writer.writerow(row)


def run_sentiment_scan(config_path: Path, symbols: list[str] | None = None) -> dict[str, Any]:
    raw = load_raw_config(config_path)
    raw['__config_path__'] = str(Path(config_path).resolve())
    session = resolve_session(raw)
    compat = raw.get('compatibility', {}) or {}
    runtime_cfg = compat.get('sentiment_runtime', {}) or {}
    feed_map = runtime_cfg.get('feed_map', {}) or {}
    sent_cfg = raw.get('sentiment', {}) or {}
    current_json_path = Path(resolve_relative_path(config_path, sent_cfg.get('current_json_path', '../data/current_sentiment.json')))
    history_csv_path = Path(resolve_relative_path(config_path, sent_cfg.get('path', '../data/sentiment_history.csv')))
    watchlist = [str(s).upper() for s in (symbols or session.watchlist or raw.get('universe', {}).get('symbols', []))]

    current_payload = {}
    rows = []
    timestamp = datetime.now(timezone.utc).isoformat()
    active_key = session.active_session or 'us'
    feeds = feed_map.get(active_key) or feed_map.get('default') or []

    for symbol in watchlist:
        items = fetch_headlines(symbol, feeds)
        score, confidence, summary = score_headlines(items)
        current_payload[symbol] = {
            'timestamp': timestamp,
            'sentiment_score': score,
            'confidence': confidence,
            'provider': 'keyword_news_v2',
            'summary': summary,
            'headline_count': len(items),
        }
        rows.append({
            'timestamp': timestamp,
            'symbol': symbol,
            'score': score,
            'confidence': confidence,
            'source': 'keyword_news_v2',
            'summary': summary,
        })

    _append_csv(history_csv_path, rows)
    current_json_path.parent.mkdir(parents=True, exist_ok=True)
    current_json_path.write_text(json.dumps(current_payload, indent=2), encoding='utf-8')
    return {
        'timestamp': timestamp,
        'session': session.active_session,
        'symbols': watchlist,
        'rows_written': len(rows),
        'current_json_path': str(current_json_path),
        'history_csv_path': str(history_csv_path),
    }
