from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TYPE_CHECKING
import json

from trading_bot.integrations.openclaw.context import load_latest_contracts
from trading_bot.live.session import resolve_session

if TYPE_CHECKING:
    from trading_bot.live.runner import LiveRuntime


SESSION_KEYS = ('eu', 'us', 'pre', 'open', 'intraday', 'close', 'overnight')


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def derive_session_policy(contract: dict[str, Any] | None, session_name: str | None) -> dict[str, Any]:
    contract = contract or {}
    name = str(session_name or 'unscheduled')
    regime = str(contract.get('event_regime') or 'normal')
    policy = str(contract.get('approval_policy') or 'auto')
    risk = float(contract.get('event_risk_score') or 0.0)
    contradiction = float(contract.get('contradiction_score') or 0.0)

    entry_mode = 'normal'
    size_multiplier = 1.0
    shorting_allowed = True
    approval_tier_floor = 'routine'
    notes: list[str] = []

    if regime == 'binary_event_lockdown' or policy == 'block_new_entries':
        entry_mode = 'block'
        size_multiplier = 0.0
        approval_tier_floor = 'blocked'
        shorting_allowed = False
        notes.append('No fresh risk while the symbol is locked down.')
    elif regime in {'contradictory_tape', 'headline_fragile'} or policy != 'auto':
        entry_mode = 'review'
        size_multiplier = 0.5
        approval_tier_floor = 'elevated'
        notes.append('Require operator review before fresh risk.')

    if risk >= 0.8 or contradiction >= 0.65:
        entry_mode = 'review' if entry_mode != 'block' else entry_mode
        size_multiplier = min(size_multiplier, 0.5)
        approval_tier_floor = 'critical' if entry_mode != 'block' else approval_tier_floor
        notes.append('Use smaller size due to headline/event instability.')

    if name in {'open', 'close'}:
        size_multiplier = min(size_multiplier, 0.7 if entry_mode == 'normal' else 0.5)
        notes.append('Opening/closing windows are more fragile; keep risk tighter.')
    elif name == 'overnight':
        size_multiplier = min(size_multiplier, 0.4)
        approval_tier_floor = 'critical' if approval_tier_floor != 'blocked' else approval_tier_floor
        notes.append('Overnight adds gap risk; escalate review threshold.')
    elif name == 'pre':
        size_multiplier = min(size_multiplier, 0.6)
        notes.append('Pre-market liquidity can be thinner than regular hours.')

    if policy == 'review_shorts':
        shorting_allowed = False
        notes.append('Shorts require explicit review under current policy.')

    return {
        'session_name': name,
        'entry_mode': entry_mode,
        'size_multiplier': round(float(size_multiplier), 2),
        'shorting_allowed': bool(shorting_allowed),
        'approval_tier_floor': approval_tier_floor,
        'notes': notes or ['Standard supervised handling.'],
    }


def generate_session_policy_report(runtime: LiveRuntime, output_dir: Path, *, label: str | None = None) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    contracts = load_latest_contracts(runtime)
    session = resolve_session(runtime.raw)
    active_session = session.active_session or 'unscheduled'
    rows: list[dict[str, Any]] = []
    blocked: list[str] = []
    review: list[str] = []
    for symbol, contract in sorted(contracts.items()):
        policy = derive_session_policy(contract, active_session)
        row = {
            'symbol': symbol,
            'active_session': active_session,
            'event_regime': contract.get('event_regime', 'normal'),
            'approval_policy': contract.get('approval_policy', 'auto'),
            **policy,
        }
        rows.append(row)
        if row['entry_mode'] == 'block':
            blocked.append(symbol)
        elif row['entry_mode'] == 'review':
            review.append(symbol)
    payload = {
        'generated_at': _utc_now(),
        'active_session': active_session,
        'blocked_symbols': blocked,
        'review_symbols': review,
        'rows': rows,
    }
    base = label or datetime.now(timezone.utc).strftime('%Y%m%d')
    json_path = output_dir / f'session_policy_report_{base}.json'
    md_path = output_dir / f'session_policy_report_{base}.md'
    json_path.write_text(json.dumps(payload, indent=2, default=str), encoding='utf-8')
    lines = [
        '# Session Policy Report',
        '',
        f"Generated at: {payload['generated_at']}",
        f"Active session: {active_session}",
        f"Blocked symbols: {', '.join(blocked) or 'none'}",
        f"Review symbols: {', '.join(review) or 'none'}",
        '',
        '## Symbols',
        '',
    ]
    for row in rows:
        lines.extend([
            f"- {row['symbol']}: mode={row['entry_mode']} tier_floor={row['approval_tier_floor']} size_mult={row['size_multiplier']} shorts={row['shorting_allowed']}",
            f"  notes: {' | '.join(row['notes'])}",
        ])
    md_path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return {'json_path': str(json_path), 'markdown_path': str(md_path), 'blocked_symbols': blocked, 'review_symbols': review, 'active_session': active_session}


def generate_session_policy_report_from_config(config_path: Path, output_dir: Path, *, label: str | None = None) -> dict[str, Any]:
    from trading_bot.live.runner import build_live_runtime

    runtime = build_live_runtime(config_path)
    return generate_session_policy_report(runtime, output_dir, label=label)
