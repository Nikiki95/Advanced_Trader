from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json

from trading_bot.integrations.openclaw.context import load_current_sentiment_json, load_latest_contracts
from trading_bot.integrations.openclaw.guardrails import summarize_portfolio_guardrails
from trading_bot.live.runner import LiveRuntime, build_live_runtime


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _priority_rank(value: str | None) -> int:
    order = {'critical': 0, 'elevated': 1, 'normal': 2}
    return order.get(str(value or 'normal'), 3)


def _aggregate(runtime: LiveRuntime) -> dict[str, Any]:
    contracts = load_latest_contracts(runtime)
    current = load_current_sentiment_json(runtime)
    alerts = runtime.state.active_operator_alerts()
    approvals = runtime.state.active_approval_requests()
    regime_counts = Counter()
    policy_counts = Counter()
    priority_counts = Counter()
    symbol_rows: list[dict[str, Any]] = []
    for symbol, contract in contracts.items():
        row = {
            'symbol': symbol,
            'event_regime': contract.get('event_regime', 'normal'),
            'approval_policy': contract.get('approval_policy', 'auto'),
            'daily_report_priority': contract.get('daily_report_priority', 'normal'),
            'trading_stance': contract.get('trading_stance', 'neutral'),
            'event_risk_score': current.get(symbol, {}).get('event_risk_score', contract.get('event_risk_score', 0.0)),
            'contradiction_score': current.get(symbol, {}).get('contradiction_score', contract.get('contradiction_score', 0.0)),
            'headline_risk': current.get(symbol, {}).get('headline_risk', contract.get('headline_risk', 'low')),
            'pending_approvals': len([x for x in approvals if str(x.get('symbol') or '').upper() == symbol]),
            'active_alerts': len([x for x in alerts if str(x.get('symbol') or '').upper() == symbol]),
        }
        regime_counts[row['event_regime']] += 1
        policy_counts[row['approval_policy']] += 1
        priority_counts[row['daily_report_priority']] += 1
        symbol_rows.append(row)
    symbol_rows.sort(key=lambda row: (_priority_rank(row.get('daily_report_priority')), -float(row.get('event_risk_score') or 0.0), row['symbol']))
    focus_symbols = [row['symbol'] for row in symbol_rows if row.get('daily_report_priority') in {'critical', 'elevated'} or row.get('approval_policy') != 'auto']
    operator_focus: list[str] = []
    guardrails = summarize_portfolio_guardrails(runtime)
    if priority_counts.get('critical', 0):
        operator_focus.append('Review critical symbols before considering any fresh entries.')
    if policy_counts.get('block_new_entries', 0):
        operator_focus.append('At least one symbol is in block_new_entries mode; treat those names as locked.')
    if regime_counts.get('contradictory_tape', 0):
        operator_focus.append('Contradictory-tape symbols need extra patience and usually smaller risk.')
    if approvals:
        operator_focus.append('Pending approvals are present; clear them or let them expire before session handoff.')
    if alerts:
        operator_focus.append('Active alerts remain unresolved; operator attention is required.')
    return {
        'generated_at': _utc_now(),
        'symbol_count': len(symbol_rows),
        'regime_counts': dict(regime_counts),
        'approval_policy_counts': dict(policy_counts),
        'priority_counts': dict(priority_counts),
        'focus_symbols': focus_symbols,
        'symbol_rows': symbol_rows,
        'operator_focus': operator_focus,
        'guardrails': guardrails,
    }


def _render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        '# Portfolio Regime Report',
        '',
        f"Generated at: {payload.get('generated_at')}",
        f"Symbols covered: {payload.get('symbol_count')}",
        f"Focus symbols: {', '.join(payload.get('focus_symbols') or []) or 'none'}",
        '',
        '## Regime counts',
        '',
    ]
    for key, value in sorted((payload.get('regime_counts') or {}).items()):
        lines.append(f'- {key}: {value}')
    lines.extend(['', '## Approval policy counts', ''])
    for key, value in sorted((payload.get('approval_policy_counts') or {}).items()):
        lines.append(f'- {key}: {value}')
    lines.extend(['', '## Operator focus', ''])
    for item in payload.get('operator_focus') or ['No special portfolio-wide focus items.']:
        lines.append(f'- {item}')
    lines.extend(['', '## Guardrails', ''])
    lines.append(f"- Severity: {(payload.get('guardrails') or {}).get('severity', 'normal')}")
    lines.append(f"- Directives: {', '.join((payload.get('guardrails') or {}).get('directives', [])) or 'none'}")
    lines.extend(['', '## Symbols', ''])
    for row in payload.get('symbol_rows') or []:
        lines.append(f"- {row['symbol']}: regime={row.get('event_regime')} policy={row.get('approval_policy')} priority={row.get('daily_report_priority')} alerts={row.get('active_alerts')} approvals={row.get('pending_approvals')}")
    return '\\n'.join(lines) + '\\n'


def generate_portfolio_regime_report(runtime: LiveRuntime, output_dir: Path, *, label: str | None = None) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = _aggregate(runtime)
    base = label or datetime.now(timezone.utc).strftime('%Y%m%d')
    json_path = output_dir / f'portfolio_regime_report_{base}.json'
    md_path = output_dir / f'portfolio_regime_report_{base}.md'
    json_path.write_text(json.dumps(payload, indent=2, default=str), encoding='utf-8')
    md_path.write_text(_render_markdown(payload), encoding='utf-8')
    return {'generated_at': payload['generated_at'], 'json_path': str(json_path), 'markdown_path': str(md_path), 'focus_symbols': payload['focus_symbols'], 'symbol_count': payload['symbol_count']}


def generate_portfolio_regime_report_from_config(config_path: Path, output_dir: Path, *, label: str | None = None) -> dict[str, Any]:
    runtime = build_live_runtime(config_path)
    return generate_portfolio_regime_report(runtime, output_dir, label=label)
