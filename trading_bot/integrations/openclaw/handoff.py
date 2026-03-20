from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json

from trading_bot.integrations.openclaw.context import load_latest_contracts
from trading_bot.live.runner import LiveRuntime, build_live_runtime


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _render_markdown(packet: dict) -> str:
    lines = [
        '# Operator Shift Handoff',
        '',
        f"Generated at: {packet.get('generated_at')}",
        f"Blocked symbols: {', '.join(packet.get('blocked_symbols') or []) or 'none'}",
        f"Review symbols: {', '.join(packet.get('review_symbols') or []) or 'none'}",
        f"Critical symbols: {', '.join(packet.get('critical_symbols') or []) or 'none'}",
        '',
        '## Pending approvals',
        '',
    ]
    approvals = packet.get('pending_approvals') or []
    if approvals:
        for row in approvals:
            lines.append(f"- {row.get('approval_id')}: {row.get('action_type')} {row.get('symbol') or 'GLOBAL'} — {row.get('reason')}")
    else:
        lines.append('- none')
    lines.extend(['', '## Active alerts', ''])
    alerts = packet.get('active_alerts') or []
    if alerts:
        for row in alerts:
            lines.append(f"- {row.get('alert_id')}: [{row.get('severity')}] {row.get('message')}")
    else:
        lines.append('- none')
    lines.extend(['', '## Operator guardrails', ''])
    for item in packet.get('operator_guardrails') or []:
        lines.append(f'- {item}')
    return '\\n'.join(lines) + '\\n'


def generate_shift_handoff(runtime: LiveRuntime, output_dir: Path, *, label: str | None = None) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    approvals = runtime.state.active_approval_requests()
    alerts = runtime.state.active_operator_alerts()
    contracts = load_latest_contracts(runtime)
    blocked = sorted(symbol for symbol, row in contracts.items() if str(row.get('approval_policy') or 'auto') == 'block_new_entries')
    review_symbols = sorted(symbol for symbol, row in contracts.items() if str(row.get('approval_policy') or 'auto') != 'auto' and symbol not in blocked)
    critical = sorted(symbol for symbol, row in contracts.items() if str(row.get('daily_report_priority') or 'normal') == 'critical')
    packet = {
        'generated_at': _utc_now(),
        'blocked_symbols': blocked,
        'review_symbols': review_symbols,
        'critical_symbols': critical,
        'pending_approvals': approvals,
        'active_alerts': alerts,
        'operator_guardrails': [
            'Do not convert OpenClaw research directly into broker actions.',
            'Resolve or acknowledge critical alerts before shift handoff closes.',
            'Carry forward only still-valid approvals; let stale approvals expire.',
            'Use symbol playbooks for any elevated or critical names.',
        ],
    }
    base = label or datetime.now(timezone.utc).strftime('%Y%m%d')
    json_path = output_dir / f'shift_handoff_{base}.json'
    md_path = output_dir / f'shift_handoff_{base}.md'
    json_path.write_text(json.dumps(packet, indent=2, default=str), encoding='utf-8')
    md_path.write_text(_render_markdown(packet), encoding='utf-8')
    return {'generated_at': packet['generated_at'], 'json_path': str(json_path), 'markdown_path': str(md_path), 'blocked_symbols': blocked, 'critical_symbols': critical, 'approval_count': len(approvals), 'alert_count': len(alerts)}


def generate_shift_handoff_from_config(config_path: Path, output_dir: Path, *, label: str | None = None) -> dict:
    runtime = build_live_runtime(config_path)
    return generate_shift_handoff(runtime, output_dir, label=label)
