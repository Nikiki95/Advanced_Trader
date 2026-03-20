from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import json

from trading_bot.config import load_raw_config, resolve_relative_path
from trading_bot.integrations.openclaw.guardrails import summarize_portfolio_guardrails
from trading_bot.live.session import resolve_session
from trading_bot.live.state import RuntimeStateStore


@dataclass(slots=True)
class HealthSnapshot:
    session: str | None
    market_open: bool
    reason: str
    watchlist_size: int
    current_sentiment_count: int
    historical_sentiment_rows: int
    current_sentiment_path: str | None
    historical_sentiment_path: str | None
    ibkr_endpoint: str | None
    state_path: str | None
    position_count: int
    open_order_count: int
    pending_order_count: int
    stop_order_count: int
    bracket_group_count: int
    fill_history_count: int
    order_history_count: int
    retry_queue_count: int
    pending_replace_queue_count: int
    broker_timeout_count: int
    workflow_count: int
    order_workflow_count: int
    active_order_workflow_count: int
    manual_review_workflow_count: int
    workflow_escalation_count: int
    workflow_resume_queue_count: int
    fill_sync_window_count: int
    fill_cursor_timestamp: str | None
    fill_cursor_execution_id: str | None
    last_run: str | None
    last_sync_at: str | None
    last_recovery_at: str | None
    last_reconciliation_at: str | None
    net_liquidation: float | None
    available_funds: float | None
    unrealized_pnl: float | None
    realized_pnl: float | None
    audit_path: str | None
    active_alert_count: int
    critical_alert_count: int
    pending_approval_count: int
    approved_approval_count: int
    last_monitor_at: str | None
    guardrail_severity: str | None
    guardrail_directive_count: int


def _count_current_json(path: Path | None) -> int:
    if not path or not path.exists():
        return 0
    payload = json.loads(path.read_text(encoding='utf-8'))
    return len(payload)


def _count_csv_rows(path: Path | None) -> int:
    if not path or not path.exists():
        return 0
    rows = path.read_text(encoding='utf-8').strip().splitlines()
    return max(len(rows) - 1, 0)


def collect_health_snapshot(config_path: Path) -> HealthSnapshot:
    raw = load_raw_config(config_path)
    session = resolve_session(raw)
    sent_cfg = raw.get('sentiment', {}) or {}
    current_path = Path(resolve_relative_path(config_path, sent_cfg['current_json_path'])) if sent_cfg.get('current_json_path') else None
    hist_path = Path(resolve_relative_path(config_path, sent_cfg['path'])) if sent_cfg.get('path') else None
    live_cfg = raw.get('live', {}) or {}
    compat_ib = ((raw.get('compatibility') or {}).get('ibkr') or {})
    broker = live_cfg.get('broker', {}) or {}
    endpoint = None
    if compat_ib or broker:
        endpoint = f"{broker.get('host', compat_ib.get('host', '127.0.0.1'))}:{broker.get('port', compat_ib.get('port', 4002))}"

    state_path_str = live_cfg.get('state_path') or ((raw.get('compatibility') or {}).get('legacy_paths') or {}).get('runtime_state', 'runtime/live_state.json')
    state_path = Path(resolve_relative_path(config_path, state_path_str))
    audit_path_str = live_cfg.get('audit_path')
    audit_path = Path(resolve_relative_path(config_path, audit_path_str)) if audit_path_str else None
    state = RuntimeStateStore(state_path, audit_path=audit_path)
    account = state.state.get('account_snapshot') or {}
    last_reconciliation = (state.state.get('last_reconciliation') or {}).get('timestamp')
    last_recovery = (state.state.get('last_recovery') or {}).get('timestamp')
    class _Runtime:
        def __init__(self, raw, path, state):
            self.raw = raw
            self.config_path = config_path
            self.state = state
    guardrails = summarize_portfolio_guardrails(_Runtime(raw, state_path, state))
    return HealthSnapshot(
        session=session.active_session,
        market_open=session.market_open,
        reason=session.reason,
        watchlist_size=len(session.watchlist),
        current_sentiment_count=_count_current_json(current_path),
        historical_sentiment_rows=_count_csv_rows(hist_path),
        current_sentiment_path=str(current_path) if current_path else None,
        historical_sentiment_path=str(hist_path) if hist_path else None,
        ibkr_endpoint=endpoint,
        state_path=str(state_path),
        position_count=len(state.state.get('positions', {})),
        open_order_count=len(state.state.get('orders', [])),
        pending_order_count=len(state.state.get('pending_orders', [])),
        stop_order_count=len(state.state.get('stop_orders', [])),
        bracket_group_count=len(state.state.get('bracket_groups', [])),
        fill_history_count=len(state.state.get('fill_history', [])),
        order_history_count=len(state.state.get('order_history', [])),
        retry_queue_count=len(state.active_retry_actions()),
        pending_replace_queue_count=len(state.active_pending_replace_queue()),
        broker_timeout_count=len(state.state.get('broker_timeouts', [])),
        workflow_count=len(state.state.get('working_order_workflows', [])),
        order_workflow_count=len(state.state.get('order_workflows', [])),
        active_order_workflow_count=len(state.active_order_workflows()),
        manual_review_workflow_count=len([row for row in state.state.get('order_workflows', []) if row.get('manual_review')]),
        workflow_escalation_count=len(state.state.get('workflow_escalations', [])),
        workflow_resume_queue_count=len(state.active_workflow_resume_queue()),
        fill_sync_window_count=len(state.state.get('fill_sync_windows', [])),
        fill_cursor_timestamp=((state.state.get('fill_cursor') or {}).get('last_seen_timestamp')),
        fill_cursor_execution_id=((state.state.get('fill_cursor') or {}).get('last_seen_execution_id')),
        last_run=state.state.get('last_run'),
        last_sync_at=state.state.get('last_sync_at'),
        last_recovery_at=last_recovery,
        last_reconciliation_at=last_reconciliation,
        net_liquidation=account.get('net_liquidation'),
        available_funds=account.get('available_funds'),
        unrealized_pnl=account.get('unrealized_pnl'),
        realized_pnl=account.get('realized_pnl'),
        audit_path=str(audit_path) if audit_path else None,
        active_alert_count=len(state.active_operator_alerts()),
        critical_alert_count=len([row for row in state.active_operator_alerts() if str(row.get('severity') or '').lower() == 'critical']),
        pending_approval_count=len([row for row in state.active_approval_requests() if row.get('status') == 'pending']),
        approved_approval_count=len([row for row in state.active_approval_requests() if row.get('status') == 'approved']),
        last_monitor_at=((state.state.get('last_monitor') or {}).get('timestamp')),
        guardrail_severity=guardrails.get('severity'),
        guardrail_directive_count=len(guardrails.get('directives', [])),
    )


def format_health_snapshot(snapshot: HealthSnapshot) -> str:
    lines = [
        '=== AI Trading Bot V3.4 Health ===',
        f'Session: {snapshot.session or "none"}',
        f'Market open: {snapshot.market_open}',
        f'Reason: {snapshot.reason}',
        f'Watchlist size: {snapshot.watchlist_size}',
        f'Current sentiment entries: {snapshot.current_sentiment_count}',
        f'Historical sentiment rows: {snapshot.historical_sentiment_rows}',
        f'Current sentiment path: {snapshot.current_sentiment_path}',
        f'Historical sentiment path: {snapshot.historical_sentiment_path}',
        f'IBKR endpoint: {snapshot.ibkr_endpoint}',
        f'Runtime state path: {snapshot.state_path}',
        f'State backend: {Path(snapshot.state_path).suffix.lstrip('.') if snapshot.state_path else None}',
        f'Runtime positions: {snapshot.position_count}',
        f'Runtime open orders: {snapshot.open_order_count}',
        f'Runtime pending orders: {snapshot.pending_order_count}',
        f'Runtime stop orders: {snapshot.stop_order_count}',
        f'Bracket groups: {snapshot.bracket_group_count}',
        f'Order history rows: {snapshot.order_history_count}',
        f'Fill history rows: {snapshot.fill_history_count}',
        f'Retry queue entries: {snapshot.retry_queue_count}',
        f'Pending replace queue: {snapshot.pending_replace_queue_count}',
        f'Broker timeout events: {snapshot.broker_timeout_count}',
        f'Working-order workflows: {snapshot.workflow_count}',
        f'Order workflows total: {snapshot.order_workflow_count}',
        f'Order workflows active: {snapshot.active_order_workflow_count}',
        f'Manual-review workflows: {snapshot.manual_review_workflow_count}',
        f'Workflow escalations: {snapshot.workflow_escalation_count}',
        f'Workflow resume queue: {snapshot.workflow_resume_queue_count}',
        f'Fill sync windows: {snapshot.fill_sync_window_count}',
        f'Fill cursor timestamp: {snapshot.fill_cursor_timestamp}',
        f'Fill cursor execution id: {snapshot.fill_cursor_execution_id}',
        f'Net liquidation: {snapshot.net_liquidation}',
        f'Available funds: {snapshot.available_funds}',
        f'Unrealized PnL: {snapshot.unrealized_pnl}',
        f'Realized PnL: {snapshot.realized_pnl}',
        f'Last run: {snapshot.last_run}',
        f'Last sync: {snapshot.last_sync_at}',
        f'Last recovery: {snapshot.last_recovery_at}',
        f'Last reconciliation: {snapshot.last_reconciliation_at}',
        f'Active alerts: {snapshot.active_alert_count}',
        f'Critical alerts: {snapshot.critical_alert_count}',
        f'Pending approvals: {snapshot.pending_approval_count}',
        f'Approved approvals: {snapshot.approved_approval_count}',
        f'Last monitor snapshot: {snapshot.last_monitor_at}',
        f'Guardrail severity: {snapshot.guardrail_severity}',
        f'Guardrail directives: {snapshot.guardrail_directive_count}',
        f'Audit path: {snapshot.audit_path}',
    ]
    return '\n'.join(lines)


def format_operator_board(*, alerts: list[dict], approvals: list[dict], workflows: dict | None = None) -> str:
    lines = ['=== Operator Board ===']
    lines.append(f'Active alerts: {len(alerts)}')
    for row in alerts[:10]:
        lines.append(f"- [{row.get('severity', 'info')}] {row.get('alert_id')}: {row.get('message')} ({row.get('symbol') or 'GLOBAL'})")
    lines.append(f'Active approvals: {len(approvals)}')
    for row in approvals[:10]:
        tier = ((row.get('payload') or {}).get('decision_tier') or row.get('decision_tier') or 'routine')
        lines.append(f"- [{row.get('status')}/{tier}] {row.get('approval_id')}: {row.get('action_type')} {row.get('symbol') or 'GLOBAL'} -> {row.get('reason')}")
    if workflows is not None:
        lines.append(f"Manual-review workflows: {workflows.get('manual_review_count')}")
        lines.append(f"Resume queue: {workflows.get('resume_queue_count')}")
    return '\n'.join(lines)
