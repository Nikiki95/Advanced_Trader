from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json

from typing import TYPE_CHECKING

from trading_bot.integrations.openclaw.context import load_latest_contracts

if TYPE_CHECKING:
    from trading_bot.live.runner import LiveRuntime


CRITICAL_REGIMES = {'binary_event_lockdown', 'contradictory_tape'}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def summarize_portfolio_guardrails(runtime: LiveRuntime) -> dict[str, Any]:
    contracts = load_latest_contracts(runtime)
    alerts = runtime.state.active_operator_alerts()
    approvals = runtime.state.active_approval_requests()
    regimes = Counter(str(row.get('event_regime') or 'normal') for row in contracts.values())
    policies = Counter(str(row.get('approval_policy') or 'auto') for row in contracts.values())
    critical_alerts = [row for row in alerts if str(row.get('severity') or '').lower() == 'critical']
    manual_reviews = [row for row in runtime.state.state.get('order_workflows', []) if row.get('manual_review') and row.get('status') != 'complete']

    directives: list[str] = []
    rationale: list[str] = []
    if critical_alerts or manual_reviews:
        directives.append('operator_only')
        rationale.append('critical alerts or manual-review workflows are active')
    if policies.get('block_new_entries', 0) >= 2 or regimes.get('binary_event_lockdown', 0) >= 2:
        directives.append('freeze_new_entries')
        rationale.append('multiple symbols are currently locked for fresh risk')
    if regimes.get('contradictory_tape', 0) >= 1 or len(approvals) >= 2:
        directives.append('review_all_new_entries')
        rationale.append('portfolio context is noisy enough that new entries should be reviewed')
    if regimes.get('headline_fragile', 0) + regimes.get('contradictory_tape', 0) >= 2:
        directives.append('reduce_size')
        rationale.append('headline instability suggests smaller average size')
    if policies.get('review_shorts', 0) >= 1 or regimes.get('binary_event_lockdown', 0) >= 1:
        directives.append('review_all_shorts')
        rationale.append('short exposure should be operator-reviewed today')

    unique = []
    for item in directives:
        if item not in unique:
            unique.append(item)
    severity = 'normal'
    if 'freeze_new_entries' in unique or 'operator_only' in unique:
        severity = 'critical'
    elif unique:
        severity = 'elevated'
    blocked_symbols = sorted([symbol for symbol, row in contracts.items() if str(row.get('approval_policy') or 'auto') == 'block_new_entries' or str(row.get('event_regime') or 'normal') == 'binary_event_lockdown'])
    return {
        'generated_at': _utc_now(),
        'severity': severity,
        'directives': unique,
        'rationale': rationale,
        'regime_counts': dict(regimes),
        'policy_counts': dict(policies),
        'critical_alert_count': len(critical_alerts),
        'manual_review_count': len(manual_reviews),
        'pending_approval_count': len(approvals),
        'blocked_symbols': blocked_symbols,
    }


def generate_guardrail_report(runtime: LiveRuntime, output_dir: Path, *, label: str | None = None) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    payload = summarize_portfolio_guardrails(runtime)
    base = label or datetime.now(timezone.utc).strftime('%Y%m%d')
    json_path = output_dir / f'portfolio_guardrails_{base}.json'
    md_path = output_dir / f'portfolio_guardrails_{base}.md'
    json_path.write_text(json.dumps(payload, indent=2, default=str), encoding='utf-8')
    lines = [
        '# Portfolio Guardrail Report',
        '',
        f"Generated at: {payload['generated_at']}",
        f"Severity: {payload['severity']}",
        f"Directives: {', '.join(payload['directives']) or 'none'}",
        f"Blocked symbols: {', '.join(payload['blocked_symbols']) or 'none'}",
        '',
        '## Rationale',
    ]
    for item in payload['rationale'] or ['No portfolio-wide guardrails beyond standard supervision.']:
        lines.append(f'- {item}')
    md_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return {'json_path': str(json_path), 'markdown_path': str(md_path), 'severity': payload['severity'], 'directives': payload['directives']}


def generate_guardrail_report_from_config(config_path: Path, output_dir: Path, *, label: str | None = None) -> dict[str, Any]:
    from trading_bot.live.runner import build_live_runtime

    runtime = build_live_runtime(config_path)
    return generate_guardrail_report(runtime, output_dir, label=label)
