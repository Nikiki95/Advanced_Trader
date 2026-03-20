from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import json

from trading_bot.integrations.openclaw.context import load_current_sentiment_json, load_latest_contracts
from trading_bot.integrations.openclaw.decision_tiers import classify_decision_tier
from trading_bot.integrations.openclaw.guardrails import summarize_portfolio_guardrails
from trading_bot.integrations.openclaw.session_policies import derive_session_policy
from trading_bot.live.runner import LiveRuntime, build_live_runtime
from trading_bot.live.session import resolve_session


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(value: str) -> str:
    cleaned = ''.join(ch.lower() if ch.isalnum() else '_' for ch in str(value))
    while '__' in cleaned:
        cleaned = cleaned.replace('__', '_')
    return cleaned.strip('_') or 'item'


def _regime_actions(contract: dict[str, Any] | None, *, session_policy: dict[str, Any] | None = None, guardrails: dict[str, Any] | None = None) -> list[str]:
    contract = contract or {}
    regime = str(contract.get('event_regime') or 'normal')
    policy = str(contract.get('approval_policy') or 'auto')
    actions: list[str] = []
    if regime == 'binary_event_lockdown':
        actions.append('Do not add fresh risk until the binary event is resolved.')
    elif regime == 'contradictory_tape':
        actions.append('Prefer patience over forcing direction while news stays contradictory.')
    elif regime == 'headline_fragile':
        actions.append('Tighten size and require stronger confirmation than usual.')
    if policy == 'block_new_entries':
        actions.append('Block new entries until conditions improve.')
    elif policy != 'auto':
        actions.append(f'Operator review is required under approval policy {policy}.')
    if session_policy:
        if session_policy.get('entry_mode') == 'block':
            actions.append('Current session policy blocks fresh entries.')
        elif session_policy.get('entry_mode') == 'review':
            actions.append('Current session policy requires review before new risk.')
    if guardrails and guardrails.get('directives'):
        actions.append(f"Portfolio directives active: {', '.join(guardrails.get('directives') or [])}.")
    return actions or ['Standard supervised handling is sufficient right now.']


def _playbook_sections(
    symbol: str,
    contract: dict[str, Any] | None,
    current_row: dict[str, Any] | None,
    approvals: list[dict[str, Any]],
    alerts: list[dict[str, Any]],
    *,
    session_name: str | None = None,
    guardrails: dict[str, Any] | None = None,
) -> dict[str, Any]:
    contract = contract or {}
    current_row = current_row or {}
    symbol_approvals = [row for row in approvals if str(row.get('symbol') or '').upper() == symbol]
    symbol_alerts = [row for row in alerts if str(row.get('symbol') or '').upper() == symbol]
    priority = str(contract.get('daily_report_priority') or 'normal')
    review_level = 'manual review required' if symbol_alerts or symbol_approvals or priority in {'critical', 'elevated'} else 'routine monitoring'
    session_policy = derive_session_policy(contract, session_name)
    decision_tier, _ = classify_decision_tier(
        action_type='OPEN_LONG',
        notional=5000.0,
        contract=contract,
        session_policy=session_policy,
        portfolio_guardrails=guardrails,
    )
    return {
        'symbol': symbol,
        'generated_at': _utc_now(),
        'event_regime': contract.get('event_regime', 'normal'),
        'approval_policy': contract.get('approval_policy', 'auto'),
        'trading_stance': current_row.get('trading_stance', contract.get('trading_stance', 'neutral')),
        'headline_risk': current_row.get('headline_risk', contract.get('headline_risk', 'low')),
        'event_flags': current_row.get('event_flags', contract.get('event_flags', [])),
        'event_risk_score': current_row.get('event_risk_score', contract.get('event_risk_score', 0.0)),
        'contradiction_score': current_row.get('contradiction_score', contract.get('contradiction_score', 0.0)),
        'relevance_score': current_row.get('relevance_score', contract.get('relevance_score', 0.0)),
        'sentiment_score': current_row.get('sentiment_score', contract.get('sentiment_score', 0.0)),
        'confidence': current_row.get('confidence', contract.get('confidence', 0.0)),
        'thesis': current_row.get('thesis', contract.get('thesis', '')),
        'review_level': review_level,
        'session_policy': session_policy,
        'suggested_decision_tier': decision_tier,
        'guardrail_directives': (guardrails or {}).get('directives', []),
        'pending_approvals': symbol_approvals,
        'active_alerts': symbol_alerts,
        'recommended_actions': _regime_actions(contract, session_policy=session_policy, guardrails=guardrails),
        'operator_questions': [
            'Does the current OpenClaw thesis still support taking risk here?',
            'Is the current session policy stricter than the raw symbol stance?',
            'Would waiting reduce avoidable headline risk?',
        ],
    }


def render_symbol_playbook_markdown(payload: dict[str, Any]) -> str:
    approvals = payload.get('pending_approvals') or []
    alerts = payload.get('active_alerts') or []
    lines = [
        f"# Symbol Playbook: {payload.get('symbol')}",
        '',
        f"- Review level: {payload.get('review_level')}",
        f"- Event regime: {payload.get('event_regime')}",
        f"- Approval policy: {payload.get('approval_policy')}",
        f"- Trading stance: {payload.get('trading_stance')}",
        f"- Headline risk: {payload.get('headline_risk')}",
        f"- Event flags: {', '.join(payload.get('event_flags') or []) or 'none'}",
        f"- Sentiment / confidence / relevance: {payload.get('sentiment_score')} / {payload.get('confidence')} / {payload.get('relevance_score')}",
        f"- Event risk / contradiction: {payload.get('event_risk_score')} / {payload.get('contradiction_score')}",
        f"- Session mode: {(payload.get('session_policy') or {}).get('entry_mode')}",
        f"- Session tier floor: {(payload.get('session_policy') or {}).get('approval_tier_floor')}",
        f"- Suggested decision tier: {payload.get('suggested_decision_tier')}",
        f"- Guardrails: {', '.join(payload.get('guardrail_directives') or []) or 'none'}",
        f"- Thesis: {payload.get('thesis') or 'n/a'}",
        '',
        '## Recommended operator actions',
        '',
    ]
    for action in payload.get('recommended_actions') or []:
        lines.append(f'- {action}')
    lines.extend(['', '## Pending approvals', ''])
    if approvals:
        for row in approvals:
            lines.append(f"- {row.get('approval_id')}: {row.get('action_type')} — {row.get('reason')}")
    else:
        lines.append('- none')
    lines.extend(['', '## Active alerts', ''])
    if alerts:
        for row in alerts:
            lines.append(f"- {row.get('alert_id')}: [{row.get('severity')}] {row.get('message')}")
    else:
        lines.append('- none')
    lines.extend(['', '## Operator questions', ''])
    for question in payload.get('operator_questions') or []:
        lines.append(f'- {question}')
    return '\n'.join(lines) + '\n'


def select_symbols_for_playbooks(runtime: LiveRuntime) -> list[str]:
    contracts = load_latest_contracts(runtime)
    alerts = runtime.state.active_operator_alerts()
    approvals = runtime.state.active_approval_requests()
    selected = {str(row.get('symbol') or '').upper() for row in approvals + alerts if row.get('symbol')}
    for symbol, contract in contracts.items():
        priority = str(contract.get('daily_report_priority') or 'normal')
        policy = str(contract.get('approval_policy') or 'auto')
        if priority in {'critical', 'elevated'} or policy != 'auto':
            selected.add(symbol)
    return sorted(sym for sym in selected if sym)


def export_review_playbooks(runtime: LiveRuntime, output_dir: Path, *, symbols: list[str] | None = None) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    contracts = load_latest_contracts(runtime)
    current = load_current_sentiment_json(runtime)
    guardrails = summarize_portfolio_guardrails(runtime)
    session_name = resolve_session(runtime.raw).active_session
    approvals = runtime.state.active_approval_requests()
    alerts = runtime.state.active_operator_alerts()
    targets = [sym.upper() for sym in (symbols or select_symbols_for_playbooks(runtime))]
    written: list[str] = []
    for symbol in targets:
        playbook = _playbook_sections(symbol, contracts.get(symbol), current.get(symbol, {}), approvals, alerts, session_name=session_name, guardrails=guardrails)
        stem = _slug(symbol)
        (output_dir / f'{stem}.json').write_text(json.dumps(playbook, indent=2, default=str), encoding='utf-8')
        (output_dir / f'{stem}.md').write_text(render_symbol_playbook_markdown(playbook), encoding='utf-8')
        written.append(symbol)
    (output_dir / 'index.json').write_text(json.dumps({'generated_at': _utc_now(), 'symbols': written}, indent=2), encoding='utf-8')
    return {'output_dir': str(output_dir), 'symbols': written, 'count': len(written)}


def export_review_playbooks_from_config(config_path: Path, output_dir: Path, *, symbols: list[str] | None = None) -> dict[str, Any]:
    runtime = build_live_runtime(config_path)
    return export_review_playbooks(runtime, output_dir, symbols=symbols)
