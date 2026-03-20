from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json

from trading_bot.integrations.openclaw.context import load_latest_contracts, load_current_sentiment_json
from trading_bot.live.runner import LiveRuntime, build_live_runtime


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def generate_daily_ops_report(runtime: LiveRuntime, output_dir: Path, *, label: str | None = None) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    contracts = load_latest_contracts(runtime)
    current = load_current_sentiment_json(runtime)
    alerts = runtime.state.active_operator_alerts()
    approvals = runtime.state.active_approval_requests()
    workflows = runtime.state.summarize_order_workflows()
    items: list[dict[str, Any]] = []
    for symbol, contract in sorted(contracts.items()):
        cur = current.get(symbol, {})
        items.append({
            'symbol': symbol,
            'trading_stance': contract.get('trading_stance'),
            'event_regime': contract.get('event_regime', 'normal'),
            'approval_policy': contract.get('approval_policy', 'auto'),
            'daily_report_priority': contract.get('daily_report_priority', 'normal'),
            'event_risk_score': contract.get('event_risk_score', 0.0),
            'contradiction_score': contract.get('contradiction_score', 0.0),
            'sentiment_score': cur.get('sentiment_score', contract.get('sentiment_score', 0.0)),
            'confidence': cur.get('confidence', contract.get('confidence', 0.0)),
            'thesis': contract.get('thesis', ''),
            'headline_risk': contract.get('headline_risk', 'low'),
            'event_flags': contract.get('event_flags', []),
            'operator_focus': _focus_line(contract),
        })
    items.sort(key=lambda row: (_priority_rank(row.get('daily_report_priority')), -abs(float(row.get('event_risk_score') or 0.0)), row['symbol']))
    timestamp = _utc_now()
    base = (label or datetime.now(timezone.utc).strftime('%Y%m%d'))
    payload = {
        'generated_at': timestamp,
        'contracts': items,
        'alerts': alerts,
        'approvals': approvals,
        'workflow_summary': workflows,
        'manual_review_count': workflows.get('manual_review_count', 0),
        'critical_contracts': [row['symbol'] for row in items if row.get('daily_report_priority') == 'critical'],
    }
    json_path = output_dir / f'operator_daily_report_{base}.json'
    md_path = output_dir / f'operator_daily_report_{base}.md'
    json_path.write_text(json.dumps(payload, indent=2, default=str), encoding='utf-8')
    md_path.write_text(_render_markdown(payload), encoding='utf-8')
    return {
        'generated_at': timestamp,
        'json_path': str(json_path),
        'markdown_path': str(md_path),
        'critical_contracts': payload['critical_contracts'],
        'alert_count': len(alerts),
        'approval_count': len(approvals),
    }


def generate_daily_ops_report_from_config(config_path: Path, output_dir: Path, *, label: str | None = None) -> dict[str, Any]:
    runtime = build_live_runtime(config_path)
    return generate_daily_ops_report(runtime, output_dir, label=label)


def _priority_rank(value: str | None) -> int:
    order = {'critical': 0, 'elevated': 1, 'normal': 2}
    return order.get(str(value or 'normal'), 3)


def _focus_line(contract: dict[str, Any]) -> str:
    regime = str(contract.get('event_regime') or 'normal')
    policy = str(contract.get('approval_policy') or 'auto')
    stance = str(contract.get('trading_stance') or 'neutral')
    thesis = str(contract.get('thesis') or '').strip()
    if policy == 'block_new_entries':
        return f'Block fresh trades; regime={regime}; stance={stance}. {thesis}'.strip()
    if policy != 'auto':
        return f'Operator review before new risk; regime={regime}; policy={policy}. {thesis}'.strip()
    return f'Normal handling; regime={regime}; stance={stance}. {thesis}'.strip()


def _render_markdown(payload: dict[str, Any]) -> str:
    lines = [
        '# Operator Daily Report',
        '',
        f"Generated at: {payload.get('generated_at')}",
        f"Critical contracts: {', '.join(payload.get('critical_contracts') or []) or 'none'}",
        f"Open alerts: {len(payload.get('alerts') or [])}",
        f"Pending approvals: {len([x for x in (payload.get('approvals') or []) if x.get('status') == 'pending'])}",
        '',
        '## Symbol summary',
        '',
    ]
    for row in payload.get('contracts') or []:
        lines.extend([
            f"### {row['symbol']} [{row.get('daily_report_priority', 'normal')}]",
            f"- Stance: {row.get('trading_stance')}",
            f"- Event regime: {row.get('event_regime')}",
            f"- Approval policy: {row.get('approval_policy')}",
            f"- Sentiment / confidence: {row.get('sentiment_score')} / {row.get('confidence')}",
            f"- Event risk / contradiction: {row.get('event_risk_score')} / {row.get('contradiction_score')}",
            f"- Flags: {', '.join(row.get('event_flags') or []) or 'none'}",
            f"- Operator focus: {row.get('operator_focus')}",
            '',
        ])
    lines.extend([
        '## Runtime summary',
        '',
        f"- Open alerts: {len(payload.get('alerts') or [])}",
        f"- Active approvals: {len(payload.get('approvals') or [])}",
        f"- Manual-review workflows: {(payload.get('workflow_summary') or {}).get('manual_review_count', 0)}",
        f"- Resume queue: {(payload.get('workflow_summary') or {}).get('resume_queue_count', 0)}",
    ])
    return '\n'.join(lines) + '\n'
