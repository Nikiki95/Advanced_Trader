from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

from trading_bot.config import AppConfig, load_config, load_raw_config, resolve_relative_path
from trading_bot.data.sentiment import HistoricalSentimentStore
from trading_bot.live.execution import BrokerSyncError, ExecutionUnavailableError, IBKRExecutor
from trading_bot.live.session import resolve_session
from trading_bot.live.state import RuntimeStateStore
from trading_bot.integrations.openclaw.decision_tiers import classify_decision_tier
from trading_bot.integrations.openclaw.guardrails import summarize_portfolio_guardrails
from trading_bot.integrations.openclaw.session_policies import derive_session_policy
from trading_bot.live.session import resolve_session
from trading_bot.live.status import collect_health_snapshot, format_operator_board
from trading_bot.risk.guards import RiskGuard
from trading_bot.risk.position_sizing import size_from_risk
from trading_bot.strategies.trend_sentiment import TrendSentimentStrategy
from trading_bot.types import PositionSide, TradeIntent


@dataclass(slots=True)
class LiveRuntime:
    config_path: Path
    typed: AppConfig
    raw: dict[str, Any]
    state: RuntimeStateStore


def _load_current_sentiment(raw_cfg: dict) -> HistoricalSentimentStore | None:
    sent_cfg = raw_cfg.get('sentiment', {}) or {}
    path = sent_cfg.get('path')
    if not path:
        return None
    return HistoricalSentimentStore(Path(resolve_relative_path(raw_cfg.get('__config_path__'), path)))


def _load_history(symbol: str, raw_cfg: dict) -> pd.DataFrame:
    source = ((raw_cfg.get('market_data') or {}).get('source') or 'csv').lower()
    if source == 'csv':
        csv_dir = Path(resolve_relative_path(raw_cfg.get('__config_path__'), (raw_cfg.get('market_data') or {}).get('csv_dir', 'data/prices')))
        path = csv_dir / f'{symbol}.csv'
        if not path.exists():
            raise FileNotFoundError(f'Missing price file for live cycle: {path}')
        df = pd.read_csv(path)
    elif source == 'yfinance':
        try:
            import yfinance as yf  # pragma: no cover
        except Exception as exc:  # pragma: no cover
            raise RuntimeError('yfinance not installed. Install with pip install -e .[marketdata]') from exc
        hist = yf.Ticker(symbol).history(period='6mo', interval='1d', auto_adjust=False)
        if hist.empty:
            raise ValueError(f'No yfinance history for {symbol}')
        hist = hist.reset_index().rename(columns={'Date': 'Date', 'Open': 'Open', 'High': 'High', 'Low': 'Low', 'Close': 'Close', 'Volume': 'Volume'})
        df = hist[['Date', 'Open', 'High', 'Low', 'Close', 'Volume']]
    else:
        raise ValueError(f'Unsupported market_data.source for live cycle: {source}')
    df['Date'] = pd.to_datetime(df['Date'], utc=False)
    return df.sort_values('Date').reset_index(drop=True)


def _extract_runtime_paths(config_path: Path, raw: dict[str, Any]) -> tuple[Path, Path, Path | None]:
    live_cfg = raw.get('live', {}) or {}
    state_path = live_cfg.get('state_path')
    journal_path = live_cfg.get('execution_journal_path')
    if not state_path:
        state_path = ((raw.get('compatibility') or {}).get('legacy_paths') or {}).get('runtime_state', 'runtime/live_state.json')
    if not journal_path:
        journal_path = 'runtime/execution_journal.jsonl'
    audit_path = live_cfg.get('audit_path')
    return (
        Path(resolve_relative_path(config_path, state_path)),
        Path(resolve_relative_path(config_path, journal_path)),
        Path(resolve_relative_path(config_path, audit_path)) if audit_path else None,
    )


def _build_executor(raw: dict[str, Any]) -> IBKRExecutor:
    live_broker = ((raw.get('live') or {}).get('broker') or {})
    compat_ib = ((raw.get('compatibility') or {}).get('ibkr') or {})
    return IBKRExecutor(
        host=str(live_broker.get('host', compat_ib.get('host', '127.0.0.1'))),
        port=int(live_broker.get('port', compat_ib.get('port', 4002))),
        client_id=int(live_broker.get('client_id', compat_ib.get('client_id', 1))),
        account=live_broker.get('account') or compat_ib.get('account'),
    )


def _execution_settings(raw: dict[str, Any]) -> dict[str, Any]:
    live_broker = ((raw.get('live') or {}).get('broker') or {})
    live_cfg = raw.get('live', {}) or {}
    return {
        'exchange': str(live_broker.get('exchange', 'SMART')),
        'currency': str(live_broker.get('currency', 'USD')),
        'timeout_seconds': int(live_broker.get('order_timeout_seconds', 20)),
        'sync_on_start': bool(live_cfg.get('sync_on_start', True)),
        'recover_on_start': bool(live_cfg.get('recover_on_start', True)),
        'process_retry_queue': bool(live_cfg.get('process_retry_queue', True)),
        'reconcile_protection_on_start': bool(live_cfg.get('reconcile_protection_on_start', True)),
        'fills_lookback_minutes': int(live_cfg.get('fills_lookback_minutes', 1440)),
        'resume_working_orders_on_start': bool(live_cfg.get('resume_working_orders_on_start', True)),
        'stale_order_minutes': int(live_cfg.get('stale_order_minutes', 30)),
        'workflow_timeout_minutes': int(live_cfg.get('workflow_timeout_minutes', 20)),
        'cancel_timeout_policy': str(live_cfg.get('cancel_timeout_policy', 'retry_cancel')),
        'replace_timeout_policy': str(live_cfg.get('replace_timeout_policy', 'retry_replace')),
        'max_workflow_resume_attempts': int(live_cfg.get('max_workflow_resume_attempts', 3)),
        'resume_workflows_on_start': bool(live_cfg.get('resume_workflows_on_start', True)),
        'require_operator_approval': bool(live_cfg.get('require_operator_approval', False)),
        'approval_intents': [str(x) for x in live_cfg.get('approval_intents', ['OPEN_SHORT'])],
        'approval_notional_threshold': float(live_cfg.get('approval_notional_threshold', 0.0) or 0.0),
        'approval_ttl_minutes': int(live_cfg.get('approval_ttl_minutes', 120)),
        'block_when_manual_review_active': bool(live_cfg.get('block_when_manual_review_active', True)),
        'alert_on_warnings': bool(live_cfg.get('alert_on_warnings', True)),
        'alert_on_pending_approvals': bool(live_cfg.get('alert_on_pending_approvals', True)),
    }


def _sync_snapshot_with_cursor(runtime: LiveRuntime, executor: IBKRExecutor, settings: dict[str, Any]):
    cursor = (runtime.state.state.get('fill_cursor') or {}).get('last_seen_timestamp')
    since = None
    if cursor:
        try:
            since = datetime.fromisoformat(str(cursor))
        except Exception:
            since = None
    return executor.sync_account_snapshot(fills_since=since, fills_lookback_minutes=settings.get('fills_lookback_minutes', 1440))



def build_live_runtime(config_path: Path) -> LiveRuntime:
    raw = load_raw_config(config_path)
    raw['__config_path__'] = str(Path(config_path).resolve())
    typed = load_config(config_path)
    state_path, journal_path, audit_path = _extract_runtime_paths(Path(config_path), raw)
    state = RuntimeStateStore(state_path, execution_journal_path=journal_path, audit_path=audit_path)
    if state.state.get('cash_estimate') is None and not state.state.get('account_snapshot'):
        state.set_cash_estimate(typed.risk.starting_cash)
    return LiveRuntime(Path(config_path), typed, raw, state)




def _plan_workflow_resume(runtime: LiveRuntime, settings: dict[str, Any]) -> dict[str, Any]:
    return runtime.state.plan_working_order_resume(
        stale_after_minutes=settings['stale_order_minutes'],
        workflow_timeout_minutes=settings['workflow_timeout_minutes'],
        cancel_timeout_policy=settings['cancel_timeout_policy'],
        replace_timeout_policy=settings['replace_timeout_policy'],
        max_resume_attempts=settings['max_workflow_resume_attempts'],
    )

def _latest_openclaw_contract(runtime: LiveRuntime, symbol: str) -> dict[str, Any] | None:
    import json

    bridge_cfg = runtime.raw.get('openclaw_bridge') or {}
    runtime_dir = Path(resolve_relative_path(runtime.config_path, bridge_cfg.get('runtime_dir', 'runtime/openclaw')))
    latest_file = runtime_dir / 'latest' / 'current.json'
    if not latest_file.exists():
        return None
    payload = json.loads(latest_file.read_text(encoding='utf-8'))
    rows = payload.get('contracts', []) if isinstance(payload, dict) else []
    for row in rows:
        if str(row.get('symbol') or '').upper() == symbol.upper():
            return row
    return None


def _approval_context(runtime: LiveRuntime, settings: dict[str, Any], *, intent: TradeIntent, symbol: str, qty: int, entry_price: float) -> tuple[list[str], dict[str, Any]]:
    reasons: list[str] = []
    contract = _latest_openclaw_contract(runtime, symbol) or {}
    session = resolve_session(runtime.raw)
    session_policy = derive_session_policy(contract, session.active_session)
    portfolio_guardrails = summarize_portfolio_guardrails(runtime)
    require_approval = bool(settings.get('require_operator_approval', False))
    if require_approval and intent.value in set(settings.get('approval_intents', [])):
        reasons.append(f'intent {intent.value} requires operator approval')
    threshold = float(settings.get('approval_notional_threshold') or 0.0)
    notional = abs(float(qty) * float(entry_price))
    if require_approval and threshold > 0 and notional >= threshold:
        reasons.append(f'notional {notional:.2f} exceeds approval threshold {threshold:.2f}')
    if settings.get('block_when_manual_review_active', True):
        manual_reviews = [row for row in runtime.state.state.get('order_workflows', []) if row.get('manual_review') and row.get('status') != 'complete']
        if manual_reviews:
            reasons.append('active manual-review workflow present')
    tier, tier_reasons = classify_decision_tier(
        action_type=intent.value,
        notional=notional,
        contract=contract,
        session_policy=session_policy,
        portfolio_guardrails=portfolio_guardrails,
    )
    reasons.extend(tier_reasons)
    meta = {
        'decision_tier': tier,
        'session_policy': session_policy,
        'portfolio_guardrails': portfolio_guardrails,
        'contract': contract,
    }
    # backward-compatible human reasons
    policy = str(contract.get('approval_policy') or 'auto')
    regime = str(contract.get('event_regime') or 'normal')
    if policy == 'block_new_entries' and intent in {TradeIntent.OPEN_LONG, TradeIntent.OPEN_SHORT}:
        reasons.append(f'openclaw policy blocks new entries under regime {regime}')
    elif policy == 'review_new_entries' and intent in {TradeIntent.OPEN_LONG, TradeIntent.OPEN_SHORT}:
        reasons.append(f'openclaw policy requires review for new entries under regime {regime}')
    elif policy == 'review_shorts' and intent == TradeIntent.OPEN_SHORT:
        reasons.append(f'openclaw policy requires review for short entries under regime {regime}')
    elif policy == 'review_large_or_risky' and intent in {TradeIntent.OPEN_LONG, TradeIntent.OPEN_SHORT}:
        reasons.append(f'openclaw policy requires review for risky entries under regime {regime}')
    # dedupe while preserving order
    seen = set()
    reasons = [r for r in reasons if not (r in seen or seen.add(r))]
    return reasons, meta


def _approval_reasons(runtime: LiveRuntime, settings: dict[str, Any], *, intent: TradeIntent, symbol: str, qty: int, entry_price: float) -> list[str]:
    reasons, _ = _approval_context(runtime, settings, intent=intent, symbol=symbol, qty=qty, entry_price=entry_price)
    return reasons


def _gate_execution_by_operator(runtime: LiveRuntime, settings: dict[str, Any], *, symbol: str, intent: TradeIntent, qty: int, entry_price: float) -> tuple[bool, dict[str, Any] | None, list[str], dict[str, Any]]:
    reasons, meta = _approval_context(runtime, settings, intent=intent, symbol=symbol, qty=qty, entry_price=entry_price)
    if not reasons:
        return True, None, [], meta
    if meta.get('decision_tier') == 'blocked':
        runtime.state.create_operator_alert(
            category='entry_blocked',
            severity='critical',
            message=f'{symbol}: {intent.value} blocked by V3.4 guardrails',
            symbol=symbol,
            details={'reasons': reasons, 'decision_tier': meta.get('decision_tier')},
            dedupe_key='entry_blocked:' + intent.value + ':' + symbol + ':' + ';'.join(reasons),
        )
        return False, None, reasons, meta
    approval = runtime.state.consume_matching_approval(action_type=intent.value, symbol=symbol)
    if approval is not None:
        return True, approval, reasons, meta
    req = runtime.state.request_operator_approval(
        action_type=intent.value,
        symbol=symbol,
        reason='; '.join(reasons),
        payload={
            'qty': int(qty),
            'price_reference': float(entry_price),
            'intent': intent.value,
            'decision_tier': meta.get('decision_tier'),
            'session_policy': meta.get('session_policy'),
            'guardrail_directives': (meta.get('portfolio_guardrails') or {}).get('directives', []),
        },
        ttl_minutes=int(settings.get('approval_ttl_minutes', 120)),
        dedupe_key=f"{intent.value}:{symbol}:{';'.join(reasons)}",
    )
    runtime.state.create_operator_alert(
        category='approval_required',
        severity='critical' if meta.get('decision_tier') == 'critical' else 'warning',
        message=f'{symbol}: {intent.value} blocked pending operator approval',
        symbol=symbol,
        details={
            'approval_id': req.get('approval_id'),
            'reasons': reasons,
            'qty': int(qty),
            'price_reference': float(entry_price),
            'decision_tier': meta.get('decision_tier'),
        },
        dedupe_key=f"approval_required:{req.get('approval_id')}",
    )
    return False, req, reasons, meta


def _update_operator_alerts(runtime: LiveRuntime, settings: dict[str, Any], warnings: list[str]) -> None:
    if settings.get('alert_on_warnings', True):
        for warning in warnings:
            runtime.state.create_operator_alert(category='runtime_warning', severity='warning', message=str(warning), dedupe_key=f'runtime_warning:{warning}')
    manual_reviews = [row for row in runtime.state.state.get('order_workflows', []) if row.get('manual_review') and row.get('status') != 'complete']
    for row in manual_reviews:
        runtime.state.create_operator_alert(
            category='manual_review',
            severity='critical',
            message=f"{row.get('symbol')}: workflow {row.get('workflow_type')} requires manual review",
            symbol=str(row.get('symbol') or ''),
            details={'workflow_id': row.get('workflow_id'), 'state': row.get('state')},
            dedupe_key=f"manual_review:{row.get('workflow_id')}",
        )
    if settings.get('alert_on_pending_approvals', True):
        for row in runtime.state.active_approval_requests():
            if row.get('status') != 'pending':
                continue
            runtime.state.create_operator_alert(
                category='pending_approval',
                severity='info',
                message=f"Pending operator approval for {row.get('action_type')} {row.get('symbol') or 'GLOBAL'}",
                symbol=str(row.get('symbol') or ''),
                details={'approval_id': row.get('approval_id')},
                dedupe_key=f"pending_approval:{row.get('approval_id')}",
            )


def _process_workflow_resume(runtime: LiveRuntime, executor: IBKRExecutor, settings: dict[str, Any], *, execute: bool) -> tuple[dict[str, Any], list[dict[str, Any]], list[str]]:
    review = _plan_workflow_resume(runtime, settings)
    warnings = list(review.get('warnings', []))
    applied: list[dict[str, Any]] = []
    for action in review.get('actions', []):
        if not execute or not settings.get('resume_workflows_on_start', True):
            runtime.state.enqueue_retry_action(action, reason='queued by workflow resume review')
            continue
        try:
            applied.append(_attempt_reconcile_action(runtime, executor, settings, action))
        except (ExecutionUnavailableError, BrokerSyncError, Exception) as exc:  # noqa: BLE001
            warnings.append(str(exc))
            runtime.state.enqueue_retry_action(action, reason=str(exc))
    return review, applied, warnings

def sync_live_state(runtime: LiveRuntime) -> dict[str, Any]:
    executor = _build_executor(runtime.raw)
    settings = _execution_settings(runtime.raw)
    snapshot = _sync_snapshot_with_cursor(runtime, executor, settings)
    runtime.state.sync_from_broker(snapshot)
    workflow_review = _plan_workflow_resume(runtime, settings)
    _update_operator_alerts(runtime, settings, workflow_review.get('warnings', []))
    return {**snapshot.to_dict(), 'working_order_resume': workflow_review, 'order_workflows': runtime.state.summarize_order_workflows()}


def resume_live_state(runtime: LiveRuntime) -> dict[str, Any]:
    settings = _execution_settings(runtime.raw)
    review = _plan_workflow_resume(runtime, settings)
    return {
        'timestamp': runtime.state.state.get('updated_at'),
        'resume': review,
        'order_workflows': runtime.state.summarize_order_workflows(),
        'portfolio_guardrails': guardrails,
        'state_path': str(runtime.state.path),
    }


def monitor_live_state(runtime: LiveRuntime) -> dict[str, Any]:
    health = collect_health_snapshot(runtime.config_path)
    alerts = runtime.state.active_operator_alerts()
    approvals = runtime.state.active_approval_requests()
    workflows = runtime.state.summarize_order_workflows()
    guardrails = summarize_portfolio_guardrails(runtime)
    summary = {
        'active_alerts': len(alerts),
        'critical_alerts': len([row for row in alerts if str(row.get('severity') or '').lower() == 'critical']),
        'pending_approvals': len([row for row in approvals if row.get('status') == 'pending']),
        'approved_approvals': len([row for row in approvals if row.get('status') == 'approved']),
        'manual_review_workflows': workflows.get('manual_review_count'),
        'guardrail_severity': guardrails.get('severity'),
        'guardrail_directives': guardrails.get('directives', []),
    }
    runtime.state.record_monitor_snapshot(health=asdict(health), alerts=alerts[:25], approvals=approvals[:25], summary=summary)
    return {
        'timestamp': runtime.state.state.get('updated_at'),
        'health': asdict(health),
        'operator_board': format_operator_board(alerts=alerts, approvals=approvals, workflows=workflows),
        'alerts': alerts,
        'approvals': approvals,
        'order_workflows': workflows,
        'portfolio_guardrails': guardrails,
        'state_path': str(runtime.state.path),
    }


def decide_operator_request(runtime: LiveRuntime, *, approval_id: str, approve: bool, operator: str | None = None, note: str | None = None) -> dict[str, Any]:
    row = runtime.state.decide_operator_approval(approval_id, approve=approve, operator=operator, note=note)
    if row is None:
        raise ValueError(f'Unknown approval_id: {approval_id}')
    if approve:
        runtime.state.resolve_operator_alert(f"alert:pending_approval:{row.get('symbol') or 'none'}:{row.get('created_at')}", operator=operator, note='approval granted')
    return row


def resolve_operator_alert(runtime: LiveRuntime, *, alert_id: str, operator: str | None = None, note: str | None = None, acknowledge_only: bool = False) -> dict[str, Any]:
    row = runtime.state.acknowledge_operator_alert(alert_id, operator=operator, note=note) if acknowledge_only else runtime.state.resolve_operator_alert(alert_id, operator=operator, note=note)
    if row is None:
        raise ValueError(f'Unknown alert_id: {alert_id}')
    return row


def recover_live_state(runtime: LiveRuntime, execute: bool = False) -> dict[str, Any]:
    warnings: list[str] = []
    settings = _execution_settings(runtime.raw)
    executor = _build_executor(runtime.raw)
    sync_snapshot = None
    recovery = None
    applied: list[dict[str, Any]] = []
    try:
        sync_snapshot = _sync_snapshot_with_cursor(runtime, executor, _execution_settings(runtime.raw))
        runtime.state.sync_from_broker(sync_snapshot)
        recovery = runtime.state.recover_order_lifecycle(sync_snapshot)
        warnings.extend(recovery.get('warnings', []))
        if settings['resume_working_orders_on_start']:
            resume_review, resume_applied, resume_warnings = _process_workflow_resume(runtime, executor, settings, execute=execute)
            warnings.extend(resume_warnings)
    except (ExecutionUnavailableError, BrokerSyncError) as exc:
        warnings.append(str(exc))

    plan = runtime.state.plan_reconciliation()
    if execute:
        for action in plan['actions']:
            try:
                applied.append(_attempt_reconcile_action(runtime, executor, settings, action))
            except (ExecutionUnavailableError, BrokerSyncError, Exception) as exc:  # noqa: BLE001
                warnings.append(str(exc))
                runtime.state.enqueue_retry_action(action, reason=str(exc))
    else:
        for action in plan['actions']:
            runtime.state.enqueue_retry_action(action, reason='queued by dry recovery')

    _update_operator_alerts(runtime, settings, warnings)
    return {
        'timestamp': runtime.state.state.get('updated_at'),
        'sync': sync_snapshot.to_dict() if sync_snapshot else None,
        'recovery': recovery,
        'reconciliation': plan,
        'applied': applied,
        'warnings': warnings,
        'order_workflows': runtime.state.summarize_order_workflows(),
        'workflow_resume': locals().get('resume_review'),
        'workflow_resume_applied': locals().get('resume_applied', []),
        'state_path': str(runtime.state.path),
    }


def _attempt_reconcile_action(runtime: LiveRuntime, executor: IBKRExecutor, settings: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    action_type = action.get('action_type')
    symbol = str(action.get('symbol', '')).upper()
    if action_type == 'ENSURE_STOP':
        stop = executor.ensure_protective_stop(
            symbol=symbol,
            position_side=PositionSide(action['position_side']),
            qty=int(action['qty']),
            stop_price=float(action['stop_price']),
            exchange=settings['exchange'],
            currency=settings['currency'],
            timeout_seconds=settings['timeout_seconds'],
        )
        runtime.state.replace_stop_orders(symbol, stop)
        return {'action': action, 'result': 'ok', 'stop_order_id': stop.order_id}
    if action_type == 'RESIZE_STOP':
        existing_order_ids = [str(x) for x in (action.get('existing_order_ids') or []) if x]
        stop, cancelled = executor.resize_protective_stop(
            symbol=symbol,
            position_side=PositionSide(action['position_side']),
            qty=int(action['qty']),
            stop_price=float(action['stop_price']),
            existing_order_ids=existing_order_ids,
            exchange=settings['exchange'],
            currency=settings['currency'],
            timeout_seconds=settings['timeout_seconds'],
        )
        runtime.state.replace_stop_orders(symbol, stop, cancelled_ids=cancelled or existing_order_ids)
        runtime.state.register_stop_resize_workflow(
            symbol=symbol,
            order_ids=cancelled or existing_order_ids,
            replacement_order_id=stop.order_id,
            desired_qty=int(action['qty']),
            desired_stop_price=float(action['stop_price']),
            position_side=str(action['position_side']),
            note=str(action.get('reason') or 'stop resize requested'),
        )
        return {'action': action, 'result': 'ok', 'stop_order_id': stop.order_id, 'cancelled_order_ids': cancelled or existing_order_ids}
    if action_type == 'CANCEL_ORDER_IDS':
        order_ids = [str(x) for x in (action.get('order_ids') or [])]
        cancelled = executor.cancel_orders(order_ids)
        runtime.state.mark_stop_orders_cancelled(symbol=symbol, order_ids=cancelled or order_ids)
        source_workflow_id = action.get('source_workflow_id')
        if source_workflow_id:
            runtime.state.note_workflow_resume_attempt(str(source_workflow_id), state='CANCEL_RETRY_SENT', note=str(action.get('reason') or 'cancel retry submitted'))
        else:
            runtime.state.register_cancel_workflow(symbol=symbol, order_ids=cancelled or order_ids, note=str(action.get('reason') or 'cancel requested'))
        if action.get('resume_queue_id'):
            runtime.state.mark_workflow_resume_result(str(action.get('resume_queue_id')), success=True)
        return {'action': action, 'result': 'ok', 'cancelled_order_ids': cancelled or order_ids}
    if action_type == 'RETRY_REPLACE_STOP':
        stop = executor.ensure_protective_stop(
            symbol=symbol,
            position_side=PositionSide(action['position_side']),
            qty=int(action['qty']),
            stop_price=float(action['stop_price']),
            exchange=settings['exchange'],
            currency=settings['currency'],
            timeout_seconds=settings['timeout_seconds'],
        )
        runtime.state.replace_stop_orders(symbol, stop)
        workflow_id = action.get('workflow_id')
        if workflow_id:
            runtime.state.note_workflow_resume_attempt(str(workflow_id), state='REPLACE_RETRY_SENT', note=str(action.get('reason') or 'replace retry submitted'))
            runtime.state.update_workflow_by_id(str(workflow_id), replacement_order_id=stop.order_id)
            runtime.state.note_pending_replace_attempt(str(workflow_id), success=True, replacement_order_id=stop.order_id)
        if action.get('resume_queue_id'):
            runtime.state.mark_workflow_resume_result(str(action.get('resume_queue_id')), success=True)
        return {'action': action, 'result': 'ok', 'stop_order_id': stop.order_id}
    if action_type == 'CANCEL_SYMBOL_STOPS':
        cancelled = executor.cancel_symbol_stops(symbol)
        runtime.state.mark_stop_orders_cancelled(symbol=symbol, order_ids=cancelled or action.get('order_ids') or [])
        runtime.state.register_cancel_workflow(symbol=symbol, order_ids=cancelled or action.get('order_ids') or [], note=str(action.get('reason') or 'symbol stop cancel requested'))
        if action.get('resume_queue_id'):
            runtime.state.mark_workflow_resume_result(str(action.get('resume_queue_id')), success=True)
        return {'action': action, 'result': 'ok', 'cancelled_stop_ids': cancelled or action.get('order_ids') or []}
    if action_type == 'MARK_WORKFLOW_MANUAL_REVIEW':
        workflow_id = str(action.get('workflow_id') or '')
        runtime.state.mark_workflow_manual_review(workflow_id, note=str(action.get('reason') or 'manual review requested'), category='workflow_timeout_escalation')
        if action.get('resume_queue_id'):
            runtime.state.mark_workflow_resume_result(str(action.get('resume_queue_id')), success=True)
        return {'action': action, 'result': 'ok', 'workflow_id': workflow_id, 'status': 'manual_review'}
    raise ValueError(f'Unsupported reconciliation action: {action_type}')


def process_retry_queue(runtime: LiveRuntime, execute: bool = False) -> dict[str, Any]:
    settings = _execution_settings(runtime.raw)
    warnings: list[str] = []
    processed: list[dict[str, Any]] = []
    queued = runtime.state.active_retry_actions()
    if not queued:
        return {'processed': processed, 'warnings': warnings, 'count': 0}
    if not execute:
        return {'processed': processed, 'warnings': warnings, 'count': len(queued)}
    executor = _build_executor(runtime.raw)
    for retry in queued:
        key = retry['key']
        action = retry['action']
        try:
            result = _attempt_reconcile_action(runtime, executor, settings, action)
            processed.append(result)
            runtime.state.mark_retry_result(key, success=True)
        except (ExecutionUnavailableError, BrokerSyncError, Exception) as exc:  # noqa: BLE001
            warnings.append(str(exc))
            runtime.state.mark_retry_result(key, success=False, error=str(exc))
            if action.get('resume_queue_id'):
                runtime.state.mark_workflow_resume_result(str(action.get('resume_queue_id')), success=False, error=str(exc))
    return {'processed': processed, 'warnings': warnings, 'count': len(queued)}


def reconcile_live_state(runtime: LiveRuntime, execute: bool = False) -> dict[str, Any]:
    warnings: list[str] = []
    settings = _execution_settings(runtime.raw)
    executor = _build_executor(runtime.raw)
    sync_snapshot = None
    try:
        sync_snapshot = _sync_snapshot_with_cursor(runtime, executor, _execution_settings(runtime.raw))
        runtime.state.sync_from_broker(sync_snapshot)
        if settings['recover_on_start']:
            recovery = runtime.state.recover_order_lifecycle(sync_snapshot)
            warnings.extend(recovery.get('warnings', []))
        if settings['resume_working_orders_on_start']:
            resume_review, resume_applied, resume_warnings = _process_workflow_resume(runtime, executor, settings, execute=execute)
            warnings.extend(resume_warnings)
    except (ExecutionUnavailableError, BrokerSyncError) as exc:
        warnings.append(str(exc))

    processed_retries = {'processed': [], 'warnings': [], 'count': 0}
    if settings['process_retry_queue']:
        processed_retries = process_retry_queue(runtime, execute=execute)
        warnings.extend(processed_retries['warnings'])

    plan = runtime.state.plan_reconciliation()
    applied: list[dict[str, Any]] = []
    if execute:
        for action in plan['actions']:
            try:
                applied.append(_attempt_reconcile_action(runtime, executor, settings, action))
            except (ExecutionUnavailableError, BrokerSyncError, Exception) as exc:  # noqa: BLE001
                warnings.append(str(exc))
                runtime.state.enqueue_retry_action(action, reason=str(exc))
    else:
        for action in plan['actions']:
            runtime.state.enqueue_retry_action(action, reason='queued by dry reconcile')

    _update_operator_alerts(runtime, settings, warnings)
    return {
        'timestamp': plan['timestamp'],
        'sync': sync_snapshot.to_dict() if sync_snapshot else None,
        'reconciliation': plan,
        'applied': applied,
        'retry_processing': processed_retries,
        'warnings': warnings,
        'order_workflows': runtime.state.summarize_order_workflows(),
        'workflow_resume': locals().get('startup_workflow_resume'),
        'workflow_resume_applied': locals().get('startup_workflow_applied', []),
        'state_path': str(runtime.state.path),
    }


def run_live_cycle(runtime: LiveRuntime, execute: bool = False) -> dict[str, Any]:
    session = resolve_session(runtime.raw)
    sentiment_store = _load_current_sentiment(runtime.raw)
    strategy = TrendSentimentStrategy(runtime.typed.strategy, sentiment_store)
    risk = RiskGuard(runtime.typed.risk)
    decisions: list[dict[str, Any]] = []
    executor_result: list[dict[str, Any]] = []
    warnings: list[str] = []
    approvals_used: list[dict[str, Any]] = []

    settings = _execution_settings(runtime.raw)
    executor = _build_executor(runtime.raw)

    startup_recovery = None
    startup_reconciliation = {'timestamp': None, 'actions': [], 'warnings': [], 'pending_orders': []}
    if settings['sync_on_start']:
        try:
            snapshot = _sync_snapshot_with_cursor(runtime, executor, _execution_settings(runtime.raw))
            runtime.state.sync_from_broker(snapshot)
            if settings['recover_on_start']:
                startup_recovery = runtime.state.recover_order_lifecycle(snapshot)
                warnings.extend(startup_recovery.get('warnings', []))
            if settings['resume_working_orders_on_start']:
                startup_workflow_resume, startup_workflow_applied, startup_workflow_warnings = _process_workflow_resume(runtime, executor, settings, execute=execute)
                warnings.extend(startup_workflow_warnings)
        except (ExecutionUnavailableError, BrokerSyncError) as exc:
            warnings.append(str(exc))
    if settings['process_retry_queue']:
        retry_result = process_retry_queue(runtime, execute=execute)
        warnings.extend(retry_result['warnings'])
    if settings['reconcile_protection_on_start']:
        startup_reconciliation = runtime.state.plan_reconciliation()
        if execute:
            for action in startup_reconciliation['actions']:
                try:
                    applied = _attempt_reconcile_action(runtime, executor, settings, action)
                    executor_result.append({'type': 'reconciliation', **applied})
                except (ExecutionUnavailableError, BrokerSyncError, Exception) as exc:  # noqa: BLE001
                    warnings.append(str(exc))
                    runtime.state.enqueue_retry_action(action, reason=str(exc))

    if not session.watchlist:
        out = {
            'timestamp': session.now.isoformat(),
            'session': session.active_session,
            'market_open': session.market_open,
            'reason': session.reason,
            'warnings': warnings,
            'decisions': [],
            'executions': [],
            'recovery': startup_recovery,
            'reconciliation': startup_reconciliation,
            'order_workflows': runtime.state.summarize_order_workflows(),
            'workflow_resume': locals().get('startup_workflow_resume'),
            'workflow_resume_applied': locals().get('startup_workflow_applied', []),
        }
        _update_operator_alerts(runtime, settings, warnings)
        runtime.state.record_run([], [], {'session': session.active_session, 'market_open': session.market_open, 'reason': session.reason}, warnings, reconciliation=startup_reconciliation)
        return out

    current_positions = runtime.state.list_positions()

    for symbol in session.watchlist:
        try:
            hist = _load_history(symbol, runtime.raw)
            last_close = float(hist.iloc[-1]['Close'])
            if symbol in current_positions:
                runtime.state.mark_position(symbol, last_price=last_close)
                current_positions[symbol].last_price = last_close
            pos = current_positions.get(symbol)
            decision = strategy.decide(symbol=symbol, history=hist, timestamp=session.now, position=pos)
            entry_price = last_close
            stop_price = None
            qty = 0
            if decision.intent in {TradeIntent.OPEN_LONG, TradeIntent.OPEN_SHORT}:
                side = PositionSide.LONG if decision.intent == TradeIntent.OPEN_LONG else PositionSide.SHORT
                stop_price = risk.stop_price(side, entry_price, decision.stop_atr)
                equity_est = runtime.state.estimate_equity(runtime.typed.risk.starting_cash)
                cash_est = runtime.state.estimate_cash(runtime.typed.risk.starting_cash)
                daily_pnl = float(((runtime.state.state.get('account_snapshot') or {}).get('realized_pnl') or 0.0) + ((runtime.state.state.get('account_snapshot') or {}).get('unrealized_pnl') or 0.0))
                if risk.can_open_position(
                    open_positions=len(current_positions),
                    gross_exposure=runtime.state.gross_exposure_estimate(runtime.typed.risk.starting_cash),
                    equity=equity_est,
                    cash=cash_est,
                    daily_pnl=daily_pnl,
                ):
                    qty = size_from_risk(
                        equity=equity_est,
                        cash=cash_est,
                        entry_price=entry_price,
                        stop_price=stop_price,
                        risk_per_trade=runtime.typed.risk.risk_per_trade,
                        max_symbol_weight=runtime.typed.risk.max_symbol_weight,
                    )
                else:
                    warnings.append(f'Risk guard blocked new position for {symbol}')
            elif decision.intent in {TradeIntent.CLOSE_LONG, TradeIntent.CLOSE_SHORT} and pos is not None:
                qty = int(pos.qty)

            decision_row = {
                'symbol': symbol,
                'intent': decision.intent.value,
                'score': round(decision.score, 4),
                'reason': decision.reason,
                'price_reference': round(entry_price, 4),
                'qty': int(qty),
                'stop_price': round(stop_price, 4) if stop_price is not None else None,
                'has_position': pos is not None,
            }
            decisions.append(decision_row)

            if not execute or not session.market_open or decision.intent == TradeIntent.HOLD or qty <= 0:
                continue

            allowed, approval_row, approval_reasons, approval_meta = _gate_execution_by_operator(
                runtime,
                settings,
                symbol=symbol,
                intent=decision.intent,
                qty=qty,
                entry_price=entry_price,
            )
            if not allowed:
                warning = f"{symbol}: execution blocked pending operator approval ({'; '.join(approval_reasons)})"
                warnings.append(warning)
                decision_row['approval_required'] = True
                decision_row['approval_id'] = approval_row.get('approval_id') if approval_row else None
                decision_row['decision_tier'] = approval_meta.get('decision_tier')
                decision_row['guardrail_directives'] = (approval_meta.get('portfolio_guardrails') or {}).get('directives', [])
                continue
            if approval_row is not None:
                approvals_used.append({'approval_id': approval_row.get('approval_id'), 'symbol': symbol, 'intent': decision.intent.value})
                decision_row['approval_used'] = approval_row.get('approval_id')

            report = executor.execute(
                symbol=symbol,
                intent=decision.intent,
                qty=qty,
                stop_price=stop_price,
                exchange=settings['exchange'],
                currency=settings['currency'],
                timeout_seconds=settings['timeout_seconds'],
            )
            report_dict = report.to_dict()
            executor_result.append(report_dict)
            runtime.state.record_execution(report)
            current_positions = runtime.state.list_positions()

            post_exec_plan = runtime.state.plan_reconciliation()
            for action in post_exec_plan['actions']:
                if action.get('symbol') != symbol.upper():
                    continue
                try:
                    applied = _attempt_reconcile_action(runtime, executor, settings, action)
                    executor_result.append({'type': 'reconciliation', **applied})
                except (ExecutionUnavailableError, BrokerSyncError, Exception) as exc:  # noqa: BLE001
                    warnings.append(str(exc))
                    runtime.state.enqueue_retry_action(action, reason=str(exc))
        except (ExecutionUnavailableError, BrokerSyncError) as exc:
            warnings.append(str(exc))
            decisions.append({'symbol': symbol, 'intent': 'ERROR', 'reason': str(exc)})
        except Exception as exc:  # noqa: BLE001
            decisions.append({'symbol': symbol, 'intent': 'ERROR', 'reason': str(exc)})

    session_info = {'session': session.active_session, 'market_open': session.market_open, 'reason': session.reason}
    final_reconciliation = runtime.state.plan_reconciliation()
    guardrails = summarize_portfolio_guardrails(runtime)
    _update_operator_alerts(runtime, settings, warnings)
    runtime.state.record_run(decisions, executor_result, session_info, warnings, reconciliation=final_reconciliation)
    return {
        'timestamp': session.now.isoformat(),
        'session': session.active_session,
        'market_open': session.market_open,
        'reason': session.reason,
        'warnings': warnings,
        'decisions': decisions,
        'executions': executor_result,
        'approvals_used': approvals_used,
        'recovery': startup_recovery,
        'reconciliation': final_reconciliation,
        'order_workflows': runtime.state.summarize_order_workflows(),
        'portfolio_guardrails': guardrails,
        'state_path': str(runtime.state.path),
    }
