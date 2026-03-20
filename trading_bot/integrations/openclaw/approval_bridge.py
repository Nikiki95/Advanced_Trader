from __future__ import annotations

from pathlib import Path
from typing import Any
import json

from trading_bot.integrations.openclaw.context import load_current_sentiment_json, load_latest_contracts
from trading_bot.integrations.openclaw.guardrails import summarize_portfolio_guardrails
from trading_bot.integrations.openclaw.playbooks import export_review_playbooks
from trading_bot.integrations.openclaw.session_policies import derive_session_policy
from trading_bot.live.runner import LiveRuntime, build_live_runtime, decide_operator_request, monitor_live_state, resolve_operator_alert


def _render_approval_markdown(row: dict[str, Any], contract: dict[str, Any] | None, current_row: dict[str, Any] | None, *, session_policy: dict[str, Any] | None = None) -> str:
    symbol = str(row.get('symbol') or 'GLOBAL')
    details = row.get('details') or row.get('payload') or {}
    return '\n'.join([
        f"# Approval Review: {row.get('approval_id')}",
        '',
        f"- Symbol: {symbol}",
        f"- Intent: {row.get('action_type')}",
        f"- Reason: {row.get('reason')}",
        f"- Notional hint: {details.get('qty', '?')} @ {details.get('price_reference', '?')}",
        f"- Decision tier: {details.get('decision_tier', 'routine')}",
        '',
        '## Latest OpenClaw view',
        f"- Sentiment score: {(current_row or {}).get('sentiment_score', (contract or {}).get('sentiment_score', 'n/a'))}",
        f"- Confidence: {(current_row or {}).get('confidence', (contract or {}).get('confidence', 'n/a'))}",
        f"- Relevance: {(current_row or {}).get('relevance_score', (contract or {}).get('relevance_score', 'n/a'))}",
        f"- Headline risk: {(current_row or {}).get('headline_risk', (contract or {}).get('headline_risk', 'n/a'))}",
        f"- Event risk score: {(current_row or {}).get('event_risk_score', (contract or {}).get('event_risk_score', 'n/a'))}",
        f"- Contradiction score: {(current_row or {}).get('contradiction_score', (contract or {}).get('contradiction_score', 'n/a'))}",
        f"- Trading stance: {(current_row or {}).get('trading_stance', (contract or {}).get('trading_stance', 'n/a'))}",
        f"- Thesis: {(current_row or {}).get('thesis', (contract or {}).get('thesis', 'n/a'))}",
        f"- Session mode: {(session_policy or {}).get('entry_mode', 'normal')}",
        f"- Session tier floor: {(session_policy or {}).get('approval_tier_floor', 'routine')}",
        f"- Guardrails: {', '.join(details.get('guardrail_directives', []) or []) or 'none'}",
        '',
        '## Suggested decision JSON',
        '```json',
        json.dumps({'kind': 'approval', 'approval_id': row.get('approval_id'), 'decision': 'approve', 'operator': 'openclaw', 'note': 'approved after OpenClaw review'}, indent=2),
        '```',
    ])


def _render_alert_markdown(row: dict[str, Any], contract: dict[str, Any] | None, current_row: dict[str, Any] | None, *, session_policy: dict[str, Any] | None = None, guardrails: dict[str, Any] | None = None) -> str:
    symbol = str(row.get('symbol') or 'GLOBAL')
    return '\n'.join([
        f"# Alert Review: {row.get('alert_id')}",
        '',
        f"- Symbol: {symbol}",
        f"- Severity: {row.get('severity')}",
        f"- Category: {row.get('category')}",
        f"- Message: {row.get('message')}",
        '',
        '## Latest OpenClaw view',
        f"- Headline risk: {(current_row or {}).get('headline_risk', (contract or {}).get('headline_risk', 'n/a'))}",
        f"- Event flags: {', '.join((current_row or {}).get('event_flags', (contract or {}).get('event_flags', [])) or []) or 'none'}",
        f"- Thesis: {(current_row or {}).get('thesis', (contract or {}).get('thesis', 'n/a'))}",
        f"- Session mode: {(session_policy or {}).get('entry_mode', 'normal')}",
        f"- Session tier floor: {(session_policy or {}).get('approval_tier_floor', 'routine')}",
        f"- Guardrails: {', '.join((guardrails or {}).get('directives', [])) or 'none'}",
        '',
        '## Suggested resolution JSON',
        '```json',
        json.dumps({'kind': 'alert', 'alert_id': row.get('alert_id'), 'decision': 'resolve', 'operator': 'openclaw', 'note': 'handled after OpenClaw review'}, indent=2),
        '```',
    ])


def export_operator_queue(runtime: LiveRuntime, output_dir: Path) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    board = monitor_live_state(runtime)
    alerts = runtime.state.active_operator_alerts()
    approvals = runtime.state.active_approval_requests()
    contracts = load_latest_contracts(runtime)
    current_sentiment = load_current_sentiment_json(runtime)
    guardrails = summarize_portfolio_guardrails(runtime)
    payload = {
        'timestamp': runtime.state.state.get('updated_at'),
        'state_path': str(runtime.state.path),
        'alerts': alerts,
        'approvals': approvals,
        'operator_board': board['operator_board'],
        'health': board['health'],
        'portfolio_guardrails': guardrails,
    }
    (output_dir / 'operator_queue.json').write_text(json.dumps(payload, indent=2, default=str), encoding='utf-8')
    (output_dir / 'operator_board.txt').write_text(board['operator_board'], encoding='utf-8')
    for folder in ('approvals', 'alerts', 'decisions', 'review_packets', 'playbooks'):
        (output_dir / folder).mkdir(exist_ok=True)
    review_packets: list[dict[str, Any]] = []
    for row in approvals:
        symbol = str(row.get('symbol') or '').upper()
        contract = contracts.get(symbol)
        current_row = current_sentiment.get(symbol, {})
        session_policy = derive_session_policy(contract, board.get('health', {}).get('session'))
        stem = str(row.get('approval_id')).replace(':', '_')
        (output_dir / 'approvals' / f'{stem}.json').write_text(json.dumps(row, indent=2, default=str), encoding='utf-8')
        (output_dir / 'approvals' / f'{stem}.md').write_text(_render_approval_markdown(row, contract, current_row, session_policy=session_policy), encoding='utf-8')
        review_packets.append({'kind': 'approval', 'symbol': symbol, 'approval_id': row.get('approval_id'), 'contract': contract, 'current_sentiment': current_row, 'session_policy': session_policy, 'guardrails': guardrails})
    for row in alerts:
        symbol = str(row.get('symbol') or '').upper()
        contract = contracts.get(symbol)
        current_row = current_sentiment.get(symbol, {})
        session_policy = derive_session_policy(contract, board.get('health', {}).get('session'))
        stem = str(row.get('alert_id')).replace(':', '_')
        (output_dir / 'alerts' / f'{stem}.json').write_text(json.dumps(row, indent=2, default=str), encoding='utf-8')
        (output_dir / 'alerts' / f'{stem}.md').write_text(_render_alert_markdown(row, contract, current_row, session_policy=session_policy, guardrails=guardrails), encoding='utf-8')
        review_packets.append({'kind': 'alert', 'symbol': symbol, 'alert_id': row.get('alert_id'), 'contract': contract, 'current_sentiment': current_row, 'session_policy': session_policy, 'guardrails': guardrails})
    (output_dir / 'review_packets' / 'review_packets.json').write_text(json.dumps(review_packets, indent=2, default=str), encoding='utf-8')
    playbooks = export_review_playbooks(runtime, output_dir / 'playbooks')
    return {'output_dir': str(output_dir), 'approvals_exported': len(approvals), 'alerts_exported': len(alerts), 'review_packets': len(review_packets), 'playbooks_exported': playbooks.get('count', 0)}


def _decision_files(input_dir: Path) -> list[Path]:
    if input_dir.is_file():
        return [input_dir]
    decisions_dir = input_dir / 'decisions'
    if decisions_dir.exists():
        return sorted(p for p in decisions_dir.glob('*.json'))
    return sorted(p for p in input_dir.glob('*.json'))


def import_operator_decisions(runtime: LiveRuntime, input_dir: Path) -> dict[str, Any]:
    applied: list[dict[str, Any]] = []
    errors: list[str] = []
    for path in _decision_files(input_dir):
        payload = json.loads(path.read_text(encoding='utf-8'))
        rows = payload if isinstance(payload, list) else [payload]
        for row in rows:
            kind = str(row.get('kind') or '').lower()
            try:
                if kind == 'approval':
                    result = decide_operator_request(runtime, approval_id=str(row['approval_id']), approve=str(row.get('decision', 'approve')).lower() != 'reject', operator=str(row.get('operator') or 'openclaw'), note=row.get('note'))
                elif kind == 'alert':
                    result = resolve_operator_alert(runtime, alert_id=str(row['alert_id']), operator=str(row.get('operator') or 'openclaw'), note=row.get('note'), acknowledge_only=str(row.get('decision', 'resolve')).lower() in {'ack', 'acknowledge', 'acknowledged'})
                else:
                    raise ValueError(f'Unknown decision kind in {path.name}: {kind}')
                applied.append({'file': path.name, 'kind': kind, 'id': result.get('approval_id') or result.get('alert_id'), 'status': result.get('status')})
            except Exception as exc:  # noqa: BLE001
                errors.append(f'{path.name}: {exc}')
    return {'applied': applied, 'errors': errors, 'count': len(applied)}


def export_operator_queue_from_config(config_path: Path, output_dir: Path) -> dict[str, Any]:
    runtime = build_live_runtime(config_path)
    return export_operator_queue(runtime, output_dir)
