from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
import json
import sqlite3
from typing import Any

from trading_bot.live.execution import BrokerFillSnapshot, BrokerOrderSnapshot, BrokerSyncSnapshot, ExecutionReport
from trading_bot.types import Position, PositionSide, TradeIntent


TERMINAL_ORDER_STATUSES = {'Filled', 'Cancelled', 'Inactive', 'ApiCancelled', 'UnknownTerminal'}

WORKFLOW_ALLOWED_TRANSITIONS = {
    'cancel_confirm': {
        'CANCEL_SENT': {'CANCEL_RETRY_SENT', 'CANCEL_CONFIRMED', 'MANUAL_REVIEW_REQUIRED'},
        'CANCEL_RETRY_SENT': {'CANCEL_RETRY_SENT', 'CANCEL_CONFIRMED', 'MANUAL_REVIEW_REQUIRED'},
        'CANCEL_CONFIRMED': set(),
        'MANUAL_REVIEW_REQUIRED': set(),
    },
    'stop_resize': {
        'REPLACE_SENT': {'AWAITING_CANCEL_CONFIRM', 'AWAITING_REPLACE_CONFIRM', 'REPLACE_RETRY_SENT', 'PROTECTED', 'MANUAL_REVIEW_REQUIRED'},
        'AWAITING_CANCEL_CONFIRM': {'CANCEL_RETRY_SENT', 'AWAITING_REPLACE_CONFIRM', 'PROTECTED', 'MANUAL_REVIEW_REQUIRED'},
        'CANCEL_RETRY_SENT': {'AWAITING_CANCEL_CONFIRM', 'AWAITING_REPLACE_CONFIRM', 'PROTECTED', 'MANUAL_REVIEW_REQUIRED'},
        'AWAITING_REPLACE_CONFIRM': {'REPLACE_RETRY_SENT', 'PROTECTED', 'MANUAL_REVIEW_REQUIRED'},
        'REPLACE_RETRY_SENT': {'AWAITING_REPLACE_CONFIRM', 'PROTECTED', 'MANUAL_REVIEW_REQUIRED'},
        'PROTECTED': set(),
        'MANUAL_REVIEW_REQUIRED': set(),
    },
}


@dataclass(slots=True)
class RuntimeStateStore:
    path: Path
    execution_journal_path: Path | None = None
    audit_path: Path | None = None
    state: dict[str, Any] = field(default_factory=dict)
    backend: str = 'json'

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        if self.execution_journal_path is not None:
            self.execution_journal_path = Path(self.execution_journal_path)
        if self.audit_path is not None:
            self.audit_path = Path(self.audit_path)
        if self.path.suffix.lower() == '.db':
            self.backend = 'sqlite'
            self.state = self._load_existing_sqlite()
        else:
            self.backend = 'json'
            self.state = self._load_existing() if self.path.exists() else self._default_state()
        self._normalize()

    def _default_state(self) -> dict[str, Any]:
        return {
            'schema_version': '3.0.0',
            'updated_at': None,
            'last_run': None,
            'last_sync_at': None,
            'last_sync_source': None,
            'last_decisions': [],
            'last_executions': [],
            'last_reconciliation': None,
            'last_recovery': None,
            'warnings': [],
            'cash_estimate': None,
            'account_snapshot': None,
            'positions': {},
            'orders': [],
            'pending_orders': [],
            'stop_orders': [],
            'fills': [],
            'fill_history': [],
            'order_history': [],
            'order_lifecycle': {},
            'bracket_groups': [],
            'fill_cursor': {'last_seen_timestamp': None, 'last_seen_execution_id': None},
            'fill_sync_windows': [],
            'working_order_workflows': [],
            'order_workflows': [],
            'pending_replace_queue': [],
            'workflow_history': [],
            'workflow_resume_history': [],
            'retry_queue': [],
            'run_history': [],
            'reconciliation_history': [],
            'recovery_history': [],
            'broker_timeouts': [],
            'workflow_escalations': [],
            'workflow_resume_queue': [],
            'operator_alerts': [],
            'operator_alert_history': [],
            'approval_queue': [],
            'approval_history': [],
            'monitor_snapshots': [],
            'last_monitor': None,
        }

    def _load_existing(self) -> dict[str, Any]:
        try:
            return json.loads(self.path.read_text(encoding='utf-8'))
        except Exception:
            return self._default_state()

    def _sqlite_connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.path))
        conn.execute('PRAGMA journal_mode=WAL;')
        conn.execute('CREATE TABLE IF NOT EXISTS runtime_state (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT, updated_at TEXT)')
        conn.execute('CREATE TABLE IF NOT EXISTS runtime_events (id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT, ts TEXT, payload TEXT)')
        return conn

    def _load_existing_sqlite(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._default_state()
        try:
            conn = self._sqlite_connect()
            try:
                cur = conn.execute('SELECT payload FROM runtime_state WHERE id=1')
                row = cur.fetchone()
                if not row or not row[0]:
                    return self._default_state()
                return json.loads(row[0])
            finally:
                conn.close()
        except Exception:
            return self._default_state()

    def _save_sqlite(self) -> None:
        payload = json.dumps(self.state, default=str)
        conn = self._sqlite_connect()
        try:
            conn.execute('INSERT INTO runtime_state(id, payload, updated_at) VALUES (1, ?, ?) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload, updated_at=excluded.updated_at', (payload, self.state.get('updated_at'),))
            conn.commit()
        finally:
            conn.close()

    def _normalize(self) -> None:
        base = self._default_state()
        for key, value in base.items():
            self.state.setdefault(key, value)
        for key in ('positions',):
            self.state.setdefault(key, {})
        for key in ('orders', 'pending_orders', 'stop_orders', 'fills', 'fill_history', 'order_history', 'bracket_groups', 'fill_sync_windows', 'working_order_workflows', 'order_workflows', 'pending_replace_queue', 'workflow_history', 'workflow_resume_history', 'retry_queue', 'run_history', 'reconciliation_history', 'recovery_history', 'broker_timeouts', 'workflow_escalations', 'workflow_resume_queue', 'operator_alerts', 'operator_alert_history', 'approval_queue', 'approval_history', 'monitor_snapshots'):
            self.state.setdefault(key, [])
        if self.state.get('schema_version') != '3.0.0':
            self.state['schema_version'] = '2.9.0'
        self.state.setdefault('fill_cursor', {'last_seen_timestamp': None, 'last_seen_execution_id': None})
        self.state.setdefault('working_order_workflows', [])
        self.state.setdefault('order_workflows', [])
        self.state.setdefault('pending_replace_queue', [])
        self.state.setdefault('workflow_history', [])
        self.state.setdefault('workflow_resume_history', [])
        self.state.setdefault('fill_sync_windows', [])
        self.state.setdefault('broker_timeouts', [])
        self.state.setdefault('workflow_escalations', [])
        self.state.setdefault('workflow_resume_queue', [])
        self.state.setdefault('operator_alerts', [])
        self.state.setdefault('operator_alert_history', [])
        self.state.setdefault('approval_queue', [])
        self.state.setdefault('approval_history', [])
        self.state.setdefault('monitor_snapshots', [])
        self.state.setdefault('last_monitor', None)

    def _timestamp(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def save(self) -> None:
        self.state['updated_at'] = self._timestamp()
        if self.backend == 'sqlite':
            self._save_sqlite()
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + '.tmp')
        tmp.write_text(json.dumps(self.state, indent=2, default=str), encoding='utf-8')
        tmp.replace(self.path)

    def _append_jsonl(self, payload: dict[str, Any]) -> None:
        if self.execution_journal_path is not None:
            if Path(self.execution_journal_path).suffix.lower() == '.db':
                conn = sqlite3.connect(str(self.execution_journal_path))
                try:
                    conn.execute('PRAGMA journal_mode=WAL;')
                    conn.execute('CREATE TABLE IF NOT EXISTS runtime_events (id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT, ts TEXT, payload TEXT)')
                    etype = str(payload.get('type') or 'event')
                    ts = str(payload.get('timestamp') or payload.get('submitted_at') or payload.get('updated_at') or self._timestamp())
                    conn.execute('INSERT INTO runtime_events(type, ts, payload) VALUES (?, ?, ?)', (etype, ts, json.dumps(payload, default=str)))
                    conn.commit()
                finally:
                    conn.close()
            else:
                self.execution_journal_path.parent.mkdir(parents=True, exist_ok=True)
                with self.execution_journal_path.open('a', encoding='utf-8') as fh:
                    fh.write(json.dumps(payload, default=str) + '\n')
        self._append_audit_event(payload)

    def _append_audit_event(self, payload: dict[str, Any]) -> None:
        if self.audit_path is None:
            return
        if Path(self.audit_path).suffix.lower() == '.db':
            conn = sqlite3.connect(str(self.audit_path))
            try:
                conn.execute('PRAGMA journal_mode=WAL;')
                conn.execute('CREATE TABLE IF NOT EXISTS audit_events (id INTEGER PRIMARY KEY AUTOINCREMENT, type TEXT, ts TEXT, payload TEXT)')
                etype = str(payload.get('type') or 'event')
                ts = str(payload.get('timestamp') or payload.get('submitted_at') or payload.get('updated_at') or self._timestamp())
                conn.execute('INSERT INTO audit_events(type, ts, payload) VALUES (?, ?, ?)', (etype, ts, json.dumps(payload, default=str)))
                conn.commit()
            finally:
                conn.close()
            return
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        with self.audit_path.open('a', encoding='utf-8') as fh:
            fh.write(json.dumps(payload, default=str) + '\n')

    def _coerce_side(self, value: str | PositionSide) -> PositionSide:
        if isinstance(value, PositionSide):
            return value
        return PositionSide(str(value))

    def _is_terminal(self, status: str | None) -> bool:
        return str(status or '') in TERMINAL_ORDER_STATUSES

    def _order_row(self, **kwargs) -> dict[str, Any]:
        row = dict(kwargs)
        row.setdefault('filled_qty', 0)
        row.setdefault('remaining_qty', max(int(row.get('qty') or 0) - int(row.get('filled_qty') or 0), 0))
        return row

    def _derive_lifecycle_state(self, status: str | None, filled_qty: int, remaining_qty: int) -> str:
        s = str(status or '')
        if s in {'Filled'} or (self._is_terminal(s) and filled_qty > 0 and remaining_qty == 0):
            return 'FILLED'
        if s in {'Cancelled', 'Inactive', 'ApiCancelled'} and filled_qty == 0:
            return 'CANCELLED'
        if remaining_qty > 0 and filled_qty > 0:
            return 'PARTIALLY_FILLED'
        if remaining_qty > 0:
            return 'WORKING'
        if s and s not in TERMINAL_ORDER_STATUSES:
            return 'WORKING'
        return 'UNKNOWN'

    def _update_order_lifecycle(
        self,
        order_id: str,
        *,
        status: str | None,
        filled_qty: int,
        remaining_qty: int,
        source: str,
        extra: dict[str, Any] | None = None,
    ) -> str:
        lifecycle = self.state.setdefault('order_lifecycle', {})
        row = lifecycle.get(order_id) or {'order_id': order_id, 'history': []}
        state = self._derive_lifecycle_state(status, filled_qty, remaining_qty)
        row['state'] = state
        row['last_status'] = status
        row['filled_qty'] = int(filled_qty)
        row['remaining_qty'] = int(remaining_qty)
        row['updated_at'] = self._timestamp()
        event = {
            'timestamp': row['updated_at'],
            'source': source,
            'status': status,
            'state': state,
            'filled_qty': int(filled_qty),
            'remaining_qty': int(remaining_qty),
        }
        if extra:
            event.update(extra)
        row.setdefault('history', []).append(event)
        row['history'] = row['history'][-50:]
        lifecycle[order_id] = row
        self.state['order_lifecycle'] = lifecycle
        return state

    def _append_order_history(self, row: dict[str, Any], source: str) -> None:
        history = self.state.setdefault('order_history', [])
        payload = dict(row)
        payload['source'] = source
        payload['recorded_at'] = self._timestamp()
        order_id = payload.get('order_id')
        if order_id:
            filled_qty = int(payload.get('filled_qty') or 0)
            remaining_qty = int(payload.get('remaining_qty') or max(int(payload.get('qty') or 0) - filled_qty, 0))
            payload['lifecycle_state'] = self._update_order_lifecycle(
                str(order_id),
                status=str(payload.get('status')),
                filled_qty=filled_qty,
                remaining_qty=remaining_qty,
                source=source,
                extra={'symbol': payload.get('symbol'), 'order_type': payload.get('order_type')},
            )
        history.append(payload)
        self.state['order_history'] = history[-500:]

    def _fill_key(self, row: dict[str, Any]) -> str:
        execution_id = row.get('execution_id')
        if execution_id:
            return str(execution_id)
        return json.dumps(
            {
                'order_id': row.get('order_id'),
                'symbol': row.get('symbol'),
                'qty': row.get('qty'),
                'price': row.get('price'),
                'timestamp': row.get('timestamp'),
                'source': row.get('source'),
            },
            sort_keys=True,
            default=str,
        )

    def _append_fill_history(self, row: dict[str, Any]) -> None:
        history = self.state.setdefault('fill_history', [])
        key = self._fill_key(row)
        if any(self._fill_key(existing) == key for existing in history):
            return
        payload = dict(row)
        payload['recorded_at'] = self._timestamp()
        history.append(payload)
        self.state['fill_history'] = history[-1000:]

    def _update_bracket_group(self, *, symbol: str, bracket_id: str | None, parent_order_id: str | None, stop_order_id: str | None = None, child_order_ids: list[str] | None = None, position_side: str | None = None, status: str | None = None) -> None:
        bracket_id = bracket_id or parent_order_id or stop_order_id
        if not bracket_id:
            return
        groups = self.state.setdefault('bracket_groups', [])
        row = None
        for existing in groups:
            if str(existing.get('bracket_id')) == str(bracket_id):
                row = existing
                break
        if row is None:
            row = {
                'bracket_id': str(bracket_id),
                'symbol': symbol.upper(),
                'parent_order_id': parent_order_id,
                'stop_order_ids': [],
                'child_order_ids': [],
                'status': status or 'open',
                'created_at': self._timestamp(),
                'last_seen_at': self._timestamp(),
                'position_side': position_side,
            }
            groups.append(row)
        row['symbol'] = symbol.upper()
        row['last_seen_at'] = self._timestamp()
        if parent_order_id:
            row['parent_order_id'] = str(parent_order_id)
        if stop_order_id and stop_order_id not in row.setdefault('stop_order_ids', []):
            row['stop_order_ids'].append(str(stop_order_id))
        for child_id in child_order_ids or []:
            if child_id and child_id not in row.setdefault('child_order_ids', []):
                row['child_order_ids'].append(str(child_id))
        if position_side:
            row['position_side'] = position_side
        if status:
            row['status'] = status
        self.state['bracket_groups'] = groups[-200:]

    def _rebuild_bracket_groups_from_live_orders(self, open_orders: list[BrokerOrderSnapshot]) -> None:
        groups: dict[str, dict[str, Any]] = {str(row.get('bracket_id')): dict(row) for row in self.state.get('bracket_groups', []) if row.get('bracket_id')}
        now = self._timestamp()
        for row in groups.values():
            row['live_order_ids'] = []
            row['live_children'] = []
        for order in open_orders:
            bracket_id = order.parent_id or order.order_id
            if not bracket_id:
                continue
            group = groups.setdefault(
                str(bracket_id),
                {
                    'bracket_id': str(bracket_id),
                    'symbol': order.symbol.upper(),
                    'parent_order_id': order.parent_id or order.order_id,
                    'stop_order_ids': [],
                    'child_order_ids': [],
                    'live_order_ids': [],
                    'live_children': [],
                    'status': 'open',
                    'created_at': now,
                    'last_seen_at': now,
                    'position_side': 'LONG' if order.side.upper() == 'SELL' else 'SHORT',
                    'oca_group': order.oca_group,
                },
            )
            group['symbol'] = order.symbol.upper()
            group['last_seen_at'] = now
            group['oca_group'] = order.oca_group or group.get('oca_group')
            if order.order_id and order.order_id not in group.setdefault('live_order_ids', []):
                group['live_order_ids'].append(order.order_id)
            if order.order_type.upper() == 'STP':
                if order.order_id not in group.setdefault('stop_order_ids', []):
                    group['stop_order_ids'].append(order.order_id)
            else:
                parent_id = order.parent_id or order.order_id
                group['parent_order_id'] = parent_id
                if order.order_id != parent_id and order.order_id not in group.setdefault('child_order_ids', []):
                    group['child_order_ids'].append(order.order_id)
            for child_id in order.child_order_ids or []:
                if child_id and child_id not in group.setdefault('child_order_ids', []):
                    group['child_order_ids'].append(child_id)
                if child_id and child_id not in group.setdefault('live_children', []):
                    group['live_children'].append(child_id)
        self.state['bracket_groups'] = list(groups.values())[-200:]


    def _workflow_identity(self, workflow_type: str, symbol: str, target_order_ids: list[str] | None = None) -> tuple[str, str, tuple[str, ...]]:
        return workflow_type, symbol.upper(), tuple(sorted(str(x) for x in (target_order_ids or []) if x))

    def _upsert_order_workflow(
        self,
        *,
        workflow_type: str,
        symbol: str,
        state: str,
        target_order_ids: list[str] | None = None,
        replacement_order_id: str | None = None,
        desired_qty: int | None = None,
        desired_stop_price: float | None = None,
        position_side: str | None = None,
        note: str | None = None,
        status: str = 'active',
    ) -> dict[str, Any]:
        identity = self._workflow_identity(workflow_type, symbol, target_order_ids)
        workflows = self.state.setdefault('order_workflows', [])
        row = None
        for existing in workflows:
            if existing.get('status') == 'complete':
                continue
            if self._workflow_identity(existing.get('workflow_type', ''), existing.get('symbol', ''), existing.get('target_order_ids') or []) == identity:
                row = existing
                break
        ts = self._timestamp()
        if row is None:
            row = {
                'workflow_id': f"{workflow_type}:{symbol.upper()}:{ts}",
                'workflow_type': workflow_type,
                'symbol': symbol.upper(),
                'target_order_ids': [str(x) for x in (target_order_ids or []) if x],
                'replacement_order_id': replacement_order_id,
                'desired_qty': int(desired_qty) if desired_qty is not None else None,
                'desired_stop_price': float(desired_stop_price) if desired_stop_price is not None else None,
                'position_side': position_side,
                'state': state,
                'status': status,
                'created_at': ts,
                'updated_at': ts,
                'history': [],
                'chain_id': f"{workflow_type}:{symbol.upper()}",
                'manual_review': False,
            }
            workflows.append(row)
        else:
            if replacement_order_id is not None:
                row['replacement_order_id'] = replacement_order_id
            if desired_qty is not None:
                row['desired_qty'] = int(desired_qty)
            if desired_stop_price is not None:
                row['desired_stop_price'] = float(desired_stop_price)
            if position_side is not None:
                row['position_side'] = position_side
            row['updated_at'] = ts
            row['status'] = status
            row.setdefault('chain_id', f"{workflow_type}:{symbol.upper()}")
            row.setdefault('manual_review', False)
        row['state'] = state
        event = {'timestamp': ts, 'state': state, 'status': status}
        if note:
            event['note'] = note
        row.setdefault('history', []).append(event)
        row['history'] = row['history'][-50:]
        self.state['order_workflows'] = workflows[-200:]
        return row

    def register_cancel_workflow(self, *, symbol: str, order_ids: list[str], note: str | None = None) -> dict[str, Any]:
        row = self._upsert_order_workflow(
            workflow_type='cancel_confirm',
            symbol=symbol,
            state='CANCEL_SENT',
            target_order_ids=order_ids,
            note=note or 'cancel submitted; awaiting broker confirmation',
        )
        row.setdefault('timeout_policy', 'retry_cancel')
        row.setdefault('resume_count', 0)
        self._append_jsonl({'type': 'order_workflow', 'event': 'cancel_sent', 'workflow': row})
        self.save()
        return row

    def register_stop_resize_workflow(
        self,
        *,
        symbol: str,
        order_ids: list[str],
        replacement_order_id: str | None,
        desired_qty: int,
        desired_stop_price: float,
        position_side: str,
        note: str | None = None,
    ) -> dict[str, Any]:
        row = self._upsert_order_workflow(
            workflow_type='stop_resize',
            symbol=symbol,
            state='REPLACE_SENT',
            target_order_ids=order_ids,
            replacement_order_id=replacement_order_id,
            desired_qty=desired_qty,
            desired_stop_price=desired_stop_price,
            position_side=position_side,
            note=note or 'stop resize submitted; awaiting cancel and replace confirmation',
        )
        row.setdefault('timeout_policy', 'retry_replace')
        row.setdefault('resume_count', 0)
        self._append_jsonl({'type': 'order_workflow', 'event': 'resize_submitted', 'workflow': row})
        self.save()
        return row

    def active_order_workflows(self) -> list[dict[str, Any]]:
        return [row for row in self.state.get('order_workflows', []) if row.get('status', 'active') == 'active']

    def summarize_order_workflows(self) -> dict[str, Any]:
        active = self.active_order_workflows()
        return {
            'active_count': len(active),
            'total_count': len(self.state.get('order_workflows', [])),
            'active': [
                {
                    'workflow_id': row.get('workflow_id'),
                    'workflow_type': row.get('workflow_type'),
                    'symbol': row.get('symbol'),
                    'state': row.get('state'),
                    'target_order_ids': row.get('target_order_ids'),
                    'replacement_order_id': row.get('replacement_order_id'),
                    'resume_count': row.get('resume_count', 0),
                }
                for row in active
            ],
            'pending_replace_queue_count': len(self.active_pending_replace_queue()),
            'manual_review_count': len([row for row in active if row.get('manual_review')]),
            'resume_queue_count': len(self.active_workflow_resume_queue()),
        }

    def _workflow_can_transition(self, workflow_type: str, current_state: str | None, new_state: str | None) -> bool:
        if not new_state or not current_state or current_state == new_state:
            return True
        allowed = WORKFLOW_ALLOWED_TRANSITIONS.get(str(workflow_type or ''), {})
        if not allowed:
            return True
        next_states = allowed.get(str(current_state), set())
        return new_state in next_states

    def transition_order_workflow(
        self,
        workflow_id: str,
        *,
        new_state: str | None = None,
        status: str | None = None,
        note: str | None = None,
        replacement_order_id: str | None = None,
        manual_review: bool | None = None,
        force: bool = False,
    ) -> dict[str, Any] | None:
        workflows = self.state.setdefault('order_workflows', [])
        for row in workflows:
            if str(row.get('workflow_id')) != str(workflow_id):
                continue
            current_state = str(row.get('state') or '')
            workflow_type = str(row.get('workflow_type') or '')
            if new_state and not force and not self._workflow_can_transition(workflow_type, current_state, new_state):
                note = (note + '; ' if note else '') + f'invalid transition {current_state}->{new_state} ignored'
                new_state = current_state
            ts = self._timestamp()
            if new_state is not None:
                row['state'] = new_state
            if status is not None:
                row['status'] = status
            if replacement_order_id is not None:
                row['replacement_order_id'] = replacement_order_id
            if manual_review is not None:
                row['manual_review'] = bool(manual_review)
            row['updated_at'] = ts
            event = {'timestamp': ts, 'state': row.get('state'), 'status': row.get('status')}
            if note:
                event['note'] = note
            row.setdefault('history', []).append(event)
            row['history'] = row['history'][-50:]
            self.state['order_workflows'] = workflows[-200:]
            self.save()
            return row
        return None

    def queue_workflow_resume_action(self, *, workflow_id: str | None, action: dict[str, Any], reason: str | None = None) -> dict[str, Any]:
        queue = self.state.setdefault('workflow_resume_queue', [])
        key = self._retry_key(action)
        for existing in queue:
            if existing.get('workflow_id') == workflow_id and existing.get('key') == key and existing.get('status') in {'pending', 'failed'}:
                existing['updated_at'] = self._timestamp()
                existing['reason'] = reason or existing.get('reason')
                self.save()
                return existing
        row = {
            'resume_queue_id': f"resume:{workflow_id or 'none'}:{self._timestamp()}",
            'workflow_id': workflow_id,
            'key': key,
            'action': action,
            'status': 'pending',
            'reason': reason,
            'created_at': self._timestamp(),
            'updated_at': self._timestamp(),
            'attempts': 0,
            'last_error': None,
        }
        queue.append(row)
        self.state['workflow_resume_queue'] = queue[-200:]
        self.save()
        return row

    def active_workflow_resume_queue(self) -> list[dict[str, Any]]:
        return [row for row in self.state.get('workflow_resume_queue', []) if row.get('status') in {'pending', 'failed'}]

    def _parse_ts(self, value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value))
        except Exception:
            return None

    def create_operator_alert(
        self,
        *,
        category: str,
        severity: str,
        message: str,
        symbol: str | None = None,
        details: dict[str, Any] | None = None,
        dedupe_key: str | None = None,
    ) -> dict[str, Any]:
        ts = self._timestamp()
        severity_value = str(severity).lower()
        symbol_value = symbol.upper() if symbol else None
        details = details or {}
        dedupe_value = dedupe_key or f"{category}:{symbol_value or 'none'}:{message}"
        for row in self.state.get('operator_alerts', []):
            if row.get('status') in {'active', 'acknowledged'} and row.get('dedupe_key') == dedupe_value:
                row['updated_at'] = ts
                row['count'] = int(row.get('count') or 1) + 1
                if details:
                    row['details'] = {**(row.get('details') or {}), **details}
                self.save()
                return row
        row = {
            'alert_id': f"alert:{category}:{symbol_value or 'none'}:{ts}",
            'category': category,
            'severity': severity_value,
            'message': message,
            'symbol': symbol_value,
            'details': details,
            'dedupe_key': dedupe_value,
            'status': 'active',
            'created_at': ts,
            'updated_at': ts,
            'count': 1,
            'acknowledged_by': None,
            'acknowledged_at': None,
            'resolved_by': None,
            'resolved_at': None,
            'notes': [],
        }
        self.state['operator_alerts'] = (self.state.get('operator_alerts', []) + [row])[-500:]
        self.state['operator_alert_history'] = (self.state.get('operator_alert_history', []) + [{'timestamp': ts, 'event': 'created', 'alert_id': row['alert_id'], 'category': category, 'severity': severity_value}])[-1000:]
        self._append_jsonl({'type': 'operator_alert', 'event': 'created', 'alert': row})
        self.save()
        return row

    def active_operator_alerts(self) -> list[dict[str, Any]]:
        return [row for row in self.state.get('operator_alerts', []) if row.get('status') in {'active', 'acknowledged'}]

    def acknowledge_operator_alert(self, alert_id: str, *, operator: str | None = None, note: str | None = None) -> dict[str, Any] | None:
        for row in self.state.get('operator_alerts', []):
            if str(row.get('alert_id')) != str(alert_id):
                continue
            row['status'] = 'acknowledged'
            row['acknowledged_by'] = operator
            row['acknowledged_at'] = self._timestamp()
            row['updated_at'] = row['acknowledged_at']
            if note:
                row.setdefault('notes', []).append({'timestamp': row['updated_at'], 'operator': operator, 'note': note, 'event': 'acknowledged'})
            self.state['operator_alert_history'] = (self.state.get('operator_alert_history', []) + [{'timestamp': row['updated_at'], 'event': 'acknowledged', 'alert_id': row['alert_id'], 'operator': operator}])[-1000:]
            self.save()
            return row
        return None

    def resolve_operator_alert(self, alert_id: str, *, operator: str | None = None, note: str | None = None) -> dict[str, Any] | None:
        for row in self.state.get('operator_alerts', []):
            if str(row.get('alert_id')) != str(alert_id):
                continue
            row['status'] = 'resolved'
            row['resolved_by'] = operator
            row['resolved_at'] = self._timestamp()
            row['updated_at'] = row['resolved_at']
            if note:
                row.setdefault('notes', []).append({'timestamp': row['updated_at'], 'operator': operator, 'note': note, 'event': 'resolved'})
            self.state['operator_alert_history'] = (self.state.get('operator_alert_history', []) + [{'timestamp': row['updated_at'], 'event': 'resolved', 'alert_id': row['alert_id'], 'operator': operator}])[-1000:]
            self.save()
            return row
        return None

    def request_operator_approval(
        self,
        *,
        action_type: str,
        symbol: str | None,
        reason: str,
        payload: dict[str, Any] | None = None,
        ttl_minutes: int = 120,
        dedupe_key: str | None = None,
    ) -> dict[str, Any]:
        ts = self._timestamp()
        symbol_value = symbol.upper() if symbol else None
        payload = payload or {}
        dedupe_value = dedupe_key or f"{action_type}:{symbol_value or 'none'}:{reason}"
        for row in self.state.get('approval_queue', []):
            if row.get('status') in {'pending', 'approved'} and row.get('dedupe_key') == dedupe_value:
                row['updated_at'] = ts
                row['count'] = int(row.get('count') or 1) + 1
                if payload:
                    row['payload'] = {**(row.get('payload') or {}), **payload}
                self.save()
                return row
        row = {
            'approval_id': f"approval:{action_type}:{symbol_value or 'none'}:{ts}",
            'action_type': action_type,
            'symbol': symbol_value,
            'reason': reason,
            'payload': payload,
            'status': 'pending',
            'created_at': ts,
            'updated_at': ts,
            'expires_at': (datetime.now(timezone.utc) + timedelta(minutes=int(ttl_minutes))).isoformat(),
            'approved_by': None,
            'approved_at': None,
            'consumed_at': None,
            'rejected_by': None,
            'rejected_at': None,
            'note': None,
            'count': 1,
            'dedupe_key': dedupe_value,
        }
        self.state['approval_queue'] = (self.state.get('approval_queue', []) + [row])[-500:]
        self.state['approval_history'] = (self.state.get('approval_history', []) + [{'timestamp': ts, 'event': 'requested', 'approval_id': row['approval_id'], 'action_type': action_type, 'symbol': symbol_value}])[-1000:]
        self._append_jsonl({'type': 'approval_request', 'event': 'requested', 'approval': row})
        self.save()
        return row

    def active_approval_requests(self) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        active = []
        changed = False
        for row in self.state.get('approval_queue', []):
            if row.get('status') not in {'pending', 'approved'}:
                continue
            expires = self._parse_ts(row.get('expires_at'))
            if expires and expires < now and row.get('status') != 'expired':
                row['status'] = 'expired'
                row['updated_at'] = self._timestamp()
                changed = True
                continue
            if row.get('status') in {'pending', 'approved'}:
                active.append(row)
        if changed:
            self.save()
        return active

    def decide_operator_approval(self, approval_id: str, *, approve: bool, operator: str | None = None, note: str | None = None) -> dict[str, Any] | None:
        for row in self.state.get('approval_queue', []):
            if str(row.get('approval_id')) != str(approval_id):
                continue
            ts = self._timestamp()
            row['updated_at'] = ts
            row['note'] = note
            if approve:
                row['status'] = 'approved'
                row['approved_by'] = operator
                row['approved_at'] = ts
                event = 'approved'
            else:
                row['status'] = 'rejected'
                row['rejected_by'] = operator
                row['rejected_at'] = ts
                event = 'rejected'
            self.state['approval_history'] = (self.state.get('approval_history', []) + [{'timestamp': ts, 'event': event, 'approval_id': row['approval_id'], 'operator': operator}])[-1000:]
            self.save()
            return row
        return None

    def consume_matching_approval(self, *, action_type: str, symbol: str | None = None) -> dict[str, Any] | None:
        symbol_value = symbol.upper() if symbol else None
        for row in self.active_approval_requests():
            if row.get('status') != 'approved':
                continue
            if str(row.get('action_type')) != str(action_type):
                continue
            if symbol_value and str(row.get('symbol') or '').upper() != symbol_value:
                continue
            ts = self._timestamp()
            row['status'] = 'consumed'
            row['consumed_at'] = ts
            row['updated_at'] = ts
            self.state['approval_history'] = (self.state.get('approval_history', []) + [{'timestamp': ts, 'event': 'consumed', 'approval_id': row['approval_id'], 'action_type': action_type, 'symbol': symbol_value}])[-1000:]
            self.save()
            return row
        return None

    def record_monitor_snapshot(self, *, health: dict[str, Any], alerts: list[dict[str, Any]], approvals: list[dict[str, Any]], summary: dict[str, Any]) -> dict[str, Any]:
        snap = {
            'timestamp': self._timestamp(),
            'health': health,
            'alerts': alerts,
            'approvals': approvals,
            'summary': summary,
        }
        self.state['last_monitor'] = snap
        self.state['monitor_snapshots'] = (self.state.get('monitor_snapshots', []) + [snap])[-200:]
        self._append_jsonl({'type': 'monitor_snapshot', **snap})
        self.save()
        return snap

    def mark_workflow_resume_result(self, resume_queue_id: str, *, success: bool, error: str | None = None) -> None:
        for row in self.state.get('workflow_resume_queue', []):
            if str(row.get('resume_queue_id')) != str(resume_queue_id):
                continue
            row['attempts'] = int(row.get('attempts') or 0) + 1
            row['updated_at'] = self._timestamp()
            row['status'] = 'done' if success else 'failed'
            row['last_error'] = error
        self.save()

    def mark_workflow_manual_review(self, workflow_id: str, *, note: str | None = None, category: str = 'workflow_manual_review') -> dict[str, Any] | None:
        row = self.transition_order_workflow(workflow_id, new_state='MANUAL_REVIEW_REQUIRED', status='manual_review', manual_review=True, note=note or 'manual review required', force=True)
        if row is not None:
            escalations = self.state.setdefault('workflow_escalations', [])
            escalations.append({
                'timestamp': self._timestamp(),
                'workflow_id': workflow_id,
                'symbol': str(row.get('symbol') or '').upper(),
                'category': category,
                'reason': note or 'manual review required',
            })
            self.state['workflow_escalations'] = escalations[-200:]
            self._append_jsonl({'type': 'workflow_escalation', 'workflow_id': workflow_id, 'category': category, 'reason': note or 'manual review required', 'timestamp': self._timestamp()})
            self.save()
        return row


    def _workflow_age_minutes(self, row: dict[str, Any]) -> float | None:
        stamp = row.get('updated_at') or row.get('created_at') or row.get('queued_at')
        if not stamp:
            return None
        try:
            dt = datetime.fromisoformat(str(stamp))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return max((datetime.now(timezone.utc) - dt).total_seconds() / 60.0, 0.0)
        except Exception:
            return None

    def update_workflow_by_id(
        self,
        workflow_id: str,
        *,
        state: str | None = None,
        status: str | None = None,
        replacement_order_id: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any] | None:
        return self.transition_order_workflow(
            workflow_id,
            new_state=state,
            status=status,
            replacement_order_id=replacement_order_id,
            note=note,
            force=False,
        )

    def queue_pending_replace(
        self,
        *,
        workflow_id: str,
        symbol: str,
        desired_qty: int,
        desired_stop_price: float,
        position_side: str,
        replacement_order_id: str | None = None,
        reason: str | None = None,
    ) -> dict[str, Any]:
        queue = self.state.setdefault('pending_replace_queue', [])
        row = None
        for existing in queue:
            if str(existing.get('workflow_id')) == str(workflow_id) and existing.get('status') in {'pending', 'submitted', 'failed'}:
                row = existing
                break
        ts = self._timestamp()
        if row is None:
            row = {
                'queue_id': f"replace:{symbol.upper()}:{ts}",
                'workflow_id': workflow_id,
                'symbol': symbol.upper(),
                'desired_qty': int(desired_qty),
                'desired_stop_price': float(desired_stop_price),
                'position_side': position_side,
                'replacement_order_id': replacement_order_id,
                'status': 'pending',
                'attempts': 0,
                'queued_at': ts,
                'updated_at': ts,
                'last_error': None,
                'reason': reason,
            }
            queue.append(row)
        else:
            row['desired_qty'] = int(desired_qty)
            row['desired_stop_price'] = float(desired_stop_price)
            row['position_side'] = position_side
            row['replacement_order_id'] = replacement_order_id or row.get('replacement_order_id')
            row['updated_at'] = ts
            row['status'] = 'pending'
            row['reason'] = reason or row.get('reason')
        self.state['pending_replace_queue'] = queue[-200:]
        self._append_jsonl({'type': 'pending_replace', 'event': 'queued', 'row': row, 'timestamp': ts})
        self.save()
        return row

    def active_pending_replace_queue(self) -> list[dict[str, Any]]:
        return [row for row in self.state.get('pending_replace_queue', []) if row.get('status') in {'pending', 'submitted', 'failed'}]

    def note_workflow_resume_attempt(self, workflow_id: str, *, state: str | None = None, note: str | None = None) -> dict[str, Any] | None:
        workflows = self.state.setdefault('order_workflows', [])
        for row in workflows:
            if str(row.get('workflow_id')) != str(workflow_id):
                continue
            row['resume_count'] = int(row.get('resume_count') or 0) + 1
            row['last_resume_at'] = self._timestamp()
            if state is not None:
                if self._workflow_can_transition(str(row.get('workflow_type') or ''), str(row.get('state') or ''), state):
                    row['state'] = state
            row['manual_review'] = False
            row['updated_at'] = row['last_resume_at']
            event = {'timestamp': row['last_resume_at'], 'state': row.get('state'), 'status': row.get('status'), 'resume_count': row['resume_count']}
            if note:
                event['note'] = note
            row.setdefault('history', []).append(event)
            row['history'] = row['history'][-50:]
            self.state['order_workflows'] = workflows[-200:]
            self.save()
            return row
        return None

    def note_pending_replace_attempt(self, workflow_id: str, *, success: bool, replacement_order_id: str | None = None, error: str | None = None) -> dict[str, Any] | None:
        for row in self.state.get('pending_replace_queue', []):
            if str(row.get('workflow_id')) != str(workflow_id):
                continue
            row['attempts'] = int(row.get('attempts') or 0) + 1
            row['updated_at'] = self._timestamp()
            row['status'] = 'submitted' if success else 'failed'
            row['last_error'] = error
            if replacement_order_id is not None:
                row['replacement_order_id'] = replacement_order_id
            self.save()
            return row
        return None

    def mark_pending_replace_completed(self, workflow_id: str, replacement_order_id: str | None = None) -> None:
        changed = False
        for row in self.state.get('pending_replace_queue', []):
            if str(row.get('workflow_id')) != str(workflow_id):
                continue
            row['status'] = 'complete'
            row['updated_at'] = self._timestamp()
            if replacement_order_id is not None:
                row['replacement_order_id'] = replacement_order_id
            changed = True
        if changed:
            self.save()

    def note_broker_timeout(self, *, workflow_id: str | None, symbol: str, category: str, policy: str, note: str) -> None:
        rows = self.state.setdefault('broker_timeouts', [])
        self.state.setdefault('workflow_escalations', [])
        self.state.setdefault('workflow_resume_queue', [])
        rows.append({'timestamp': self._timestamp(), 'workflow_id': workflow_id, 'symbol': symbol.upper(), 'category': category, 'policy': policy, 'note': note})
        self.state['broker_timeouts'] = rows[-200:]
        self._append_jsonl({'type': 'broker_timeout', 'workflow_id': workflow_id, 'symbol': symbol.upper(), 'category': category, 'policy': policy, 'note': note, 'timestamp': self._timestamp()})
        self.save()

    def _find_matching_stop(self, *, symbol: str, desired_qty: int | None, desired_stop_price: float | None, position_side: str | None) -> dict[str, Any] | None:
        expected_side = None
        if position_side == 'LONG':
            expected_side = 'SELL'
        elif position_side == 'SHORT':
            expected_side = 'BUY'
        for row in self.active_stop_orders(symbol):
            qty = int(row.get('remaining_qty') or row.get('qty') or 0)
            stop_price = row.get('stop_price')
            side = str(row.get('side') or '').upper()
            if desired_qty is not None and qty != int(desired_qty):
                continue
            if desired_stop_price is not None and stop_price is not None and abs(float(stop_price) - float(desired_stop_price)) > 1e-9:
                continue
            if expected_side and side and side != expected_side:
                continue
            return row
        return None

    def confirm_order_workflows(self) -> dict[str, Any]:
        active_order_ids = {str(row.get('order_id')) for row in (self.state.get('orders', []) + self.state.get('stop_orders', [])) if row.get('order_id') and not self._is_terminal(row.get('status'))}
        completed: list[dict[str, Any]] = []
        for row in self.state.get('order_workflows', []):
            if row.get('status') == 'complete':
                continue
            target_ids = [str(x) for x in (row.get('target_order_ids') or []) if x]
            target_active = any(oid in active_order_ids for oid in target_ids)
            workflow_type = str(row.get('workflow_type') or '')
            if workflow_type == 'cancel_confirm':
                if not target_active:
                    row = self._upsert_order_workflow(
                        workflow_type='cancel_confirm',
                        symbol=str(row.get('symbol') or ''),
                        state='CANCEL_CONFIRMED',
                        target_order_ids=target_ids,
                        note='broker no longer reports targeted orders',
                        status='complete',
                    )
                    self.mark_pending_replace_completed(str(row.get('workflow_id')), replacement_order_id=str(row.get('replacement_order_id') or ''))
                    completed.append({'workflow_id': row.get('workflow_id'), 'state': row.get('state')})
                continue
            if workflow_type == 'stop_resize':
                matching = self._find_matching_stop(
                    symbol=str(row.get('symbol') or ''),
                    desired_qty=row.get('desired_qty'),
                    desired_stop_price=row.get('desired_stop_price'),
                    position_side=row.get('position_side'),
                )
                if not target_active and matching is not None:
                    row = self._upsert_order_workflow(
                        workflow_type='stop_resize',
                        symbol=str(row.get('symbol') or ''),
                        state='PROTECTED',
                        target_order_ids=target_ids,
                        replacement_order_id=str(matching.get('order_id') or row.get('replacement_order_id') or ''),
                        desired_qty=row.get('desired_qty'),
                        desired_stop_price=row.get('desired_stop_price'),
                        position_side=row.get('position_side'),
                        note='old stop gone and replacement stop confirmed live',
                        status='complete',
                    )
                    completed.append({'workflow_id': row.get('workflow_id'), 'state': row.get('state')})
                elif target_active:
                    self._upsert_order_workflow(
                        workflow_type='stop_resize',
                        symbol=str(row.get('symbol') or ''),
                        state='AWAITING_CANCEL_CONFIRM',
                        target_order_ids=target_ids,
                        replacement_order_id=row.get('replacement_order_id'),
                        desired_qty=row.get('desired_qty'),
                        desired_stop_price=row.get('desired_stop_price'),
                        position_side=row.get('position_side'),
                        note='old stop still visible at broker',
                    )
                else:
                    updated = self._upsert_order_workflow(
                        workflow_type='stop_resize',
                        symbol=str(row.get('symbol') or ''),
                        state='AWAITING_REPLACE_CONFIRM',
                        target_order_ids=target_ids,
                        replacement_order_id=row.get('replacement_order_id'),
                        desired_qty=row.get('desired_qty'),
                        desired_stop_price=row.get('desired_stop_price'),
                        position_side=row.get('position_side'),
                        note='old stop gone; waiting for replacement protection to appear live',
                    )
                    self.queue_pending_replace(
                        workflow_id=str(updated.get('workflow_id')),
                        symbol=str(updated.get('symbol') or ''),
                        desired_qty=int(updated.get('desired_qty') or 0),
                        desired_stop_price=float(updated.get('desired_stop_price') or 0.0),
                        position_side=str(updated.get('position_side') or ''),
                        replacement_order_id=str(updated.get('replacement_order_id') or ''),
                        reason='replacement stop not yet visible at broker',
                    )
        if completed:
            self.state['workflow_history'] = (self.state.get('workflow_history', []) + completed)[-500:]
            self._append_jsonl({'type': 'workflow_confirmation', 'completed': completed, 'timestamp': self._timestamp()})
            self.save()
        return self.summarize_order_workflows()

    def get_position(self, symbol: str) -> Position | None:
        raw = self.state.get('positions', {}).get(symbol.upper())
        if not raw:
            return None
        return Position(
            symbol=raw['symbol'],
            side=PositionSide(raw['side']),
            qty=int(raw['qty']),
            entry_price=float(raw['entry_price']),
            entry_time=datetime.fromisoformat(raw['entry_time']),
            stop_price=float(raw.get('stop_price') or 0.0),
            last_price=float(raw.get('last_price') or raw['entry_price']),
        )

    def list_positions(self) -> dict[str, Position]:
        out: dict[str, Position] = {}
        for symbol in self.state.get('positions', {}):
            pos = self.get_position(symbol)
            if pos:
                out[symbol] = pos
        return out

    def upsert_position(
        self,
        *,
        symbol: str,
        side: PositionSide | str,
        qty: int,
        entry_price: float,
        entry_time: datetime,
        stop_price: float | None,
        last_price: float | None = None,
        source: str = 'local_execution',
    ) -> None:
        if qty <= 0:
            self.close_position(symbol, reason='qty_non_positive')
            return
        side_value = self._coerce_side(side).value
        self.state['positions'][symbol.upper()] = {
            'symbol': symbol.upper(),
            'side': side_value,
            'qty': int(qty),
            'entry_price': float(entry_price),
            'entry_time': entry_time.isoformat(),
            'stop_price': float(stop_price) if stop_price is not None else None,
            'last_price': float(last_price if last_price is not None else entry_price),
            'source': source,
        }
        self.save()

    def mark_position(self, symbol: str, last_price: float | None = None, stop_price: float | None = None) -> None:
        row = self.state.get('positions', {}).get(symbol.upper())
        if not row:
            return
        if last_price is not None:
            row['last_price'] = float(last_price)
        if stop_price is not None:
            row['stop_price'] = float(stop_price)
        self.save()

    def close_position(self, symbol: str, reason: str = 'closed') -> None:
        if symbol.upper() in self.state.get('positions', {}):
            del self.state['positions'][symbol.upper()]
            self.state.setdefault('warnings', []).append({'timestamp': self._timestamp(), 'symbol': symbol.upper(), 'reason': reason})
            self.save()

    def set_cash_estimate(self, value: float | None) -> None:
        self.state['cash_estimate'] = float(value) if value is not None else None
        self.save()

    def estimate_cash(self, default_cash: float) -> float:
        account = self.state.get('account_snapshot') or {}
        for key in ('available_funds', 'total_cash_value'):
            value = account.get(key)
            if value is not None:
                return float(value)
        value = self.state.get('cash_estimate')
        return float(value) if value is not None else float(default_cash)

    def estimate_equity(self, default_cash: float) -> float:
        account = self.state.get('account_snapshot') or {}
        if account.get('net_liquidation') is not None:
            return float(account['net_liquidation'])
        cash = self.estimate_cash(default_cash)
        market_value = 0.0
        for pos in self.list_positions().values():
            market_value += pos.market_value()
        return cash + market_value

    def gross_exposure_estimate(self, default_cash: float) -> float:
        equity = max(self.estimate_equity(default_cash), 1e-9)
        notional = sum(abs(p.qty * p.last_price) for p in self.list_positions().values())
        return notional / equity

    def _local_fill_from_execution(self, report: ExecutionReport) -> dict[str, Any] | None:
        if report.filled_qty <= 0 or report.avg_fill_price is None:
            return None
        return {
            'execution_id': f"local:{report.order_id or report.submitted_at.isoformat()}:{report.symbol}:{report.filled_qty}",
            'order_id': report.order_id,
            'symbol': report.symbol.upper(),
            'side': report.broker_side,
            'qty': int(report.filled_qty),
            'price': float(report.avg_fill_price),
            'timestamp': report.submitted_at.isoformat(),
            'commission': None,
            'realized_pnl': None,
            'parent_id': report.parent_order_id,
            'source': 'local_execution',
            'intent': report.intent,
        }

    def record_execution(self, report: ExecutionReport) -> None:
        payload = report.to_dict()
        self.state['last_executions'] = (self.state.get('last_executions', []) + [payload])[-20:]
        self.state.setdefault('fills', []).append(payload)
        self._upsert_order_from_execution(payload)
        self._apply_execution_to_positions(report)
        fill_row = self._local_fill_from_execution(report)
        if fill_row:
            self._append_fill_history(fill_row)
        if report.intent in {TradeIntent.OPEN_LONG.value, TradeIntent.OPEN_SHORT.value}:
            self._update_bracket_group(
                symbol=report.symbol,
                bracket_id=report.bracket_id,
                parent_order_id=report.parent_order_id or report.order_id,
                stop_order_id=report.stop_order_id,
                child_order_ids=report.child_order_ids,
                position_side='LONG' if report.intent == TradeIntent.OPEN_LONG.value else 'SHORT',
                status='protected' if report.stop_order_id else 'open',
            )
        self._append_jsonl({'type': 'execution', **payload})
        self.save()

    def _upsert_order_from_execution(self, payload: dict[str, Any]) -> None:
        orders = self.state.setdefault('orders', [])
        pending = self.state.setdefault('pending_orders', [])
        order_id = payload.get('order_id')
        remaining_qty = int(payload.get('remaining_qty') if payload.get('remaining_qty') is not None else max(int(payload.get('requested_qty') or 0) - int(payload.get('filled_qty') or 0), 0))
        if order_id:
            row = {
                'order_id': order_id,
                'symbol': payload.get('symbol'),
                'intent': payload.get('intent'),
                'broker_side': payload.get('broker_side'),
                'qty': int(payload.get('requested_qty') or 0),
                'filled_qty': int(payload.get('filled_qty') or 0),
                'remaining_qty': remaining_qty,
                'status': payload.get('status'),
                'submitted_at': payload.get('submitted_at'),
                'avg_fill_price': payload.get('avg_fill_price'),
                'parent_id': payload.get('parent_order_id'),
                'bracket_id': payload.get('bracket_id'),
                'order_type': 'MKT',
            }
            orders = [old for old in orders if old.get('order_id') != order_id]
            orders.append(row)
            self.state['orders'] = orders[-200:]
            self._append_order_history(row, source='execution_report')
            pending = [old for old in pending if old.get('order_id') != order_id]
            if remaining_qty > 0 or not self._is_terminal(payload.get('status')):
                pending.append(row)
            self.state['pending_orders'] = pending[-200:]

        stop_id = payload.get('stop_order_id')
        if stop_id:
            stop_orders = [row for row in self.state.setdefault('stop_orders', []) if row.get('order_id') != stop_id]
            stop_row = {
                'order_id': stop_id,
                'symbol': payload.get('symbol'),
                'qty': int(payload.get('filled_qty') or 0),
                'filled_qty': 0,
                'remaining_qty': int(payload.get('filled_qty') or 0),
                'status': payload.get('stop_status'),
                'stop_price': payload.get('stop_price'),
                'submitted_at': payload.get('submitted_at'),
                'side': 'SELL' if payload.get('intent') == 'OPEN_LONG' else 'BUY',
                'order_type': 'STP',
                'parent_id': payload.get('parent_order_id') or payload.get('order_id'),
                'bracket_id': payload.get('bracket_id') or payload.get('parent_order_id') or payload.get('order_id'),
            }
            stop_orders.append(stop_row)
            self.state['stop_orders'] = stop_orders[-200:]
            self._append_order_history(stop_row, source='execution_report_stop')
            self._update_bracket_group(
                symbol=str(payload.get('symbol') or ''),
                bracket_id=stop_row.get('bracket_id'),
                parent_order_id=stop_row.get('parent_id'),
                stop_order_id=stop_id,
                position_side='LONG' if payload.get('intent') == 'OPEN_LONG' else 'SHORT',
                status='protected',
            )
        cancelled = set(payload.get('cancelled_stop_ids') or [])
        if cancelled:
            for row in self.state.get('stop_orders', []):
                if row.get('order_id') in cancelled:
                    row['status'] = 'Cancelled'
                    row['remaining_qty'] = 0

    def _apply_execution_to_positions(self, report: ExecutionReport) -> None:
        if report.filled_qty <= 0 or report.avg_fill_price is None:
            return
        timestamp = report.submitted_at
        symbol = report.symbol.upper()
        intent = TradeIntent(report.intent)
        current_cash = self.state.get('cash_estimate')
        current_cash = float(current_cash) if current_cash is not None else 0.0
        price = float(report.avg_fill_price)
        notional = report.filled_qty * price
        current = self.get_position(symbol)

        if intent == TradeIntent.OPEN_LONG:
            self.state['cash_estimate'] = current_cash - notional
            if current and current.side == PositionSide.LONG:
                total_qty = current.qty + report.filled_qty
                avg_price = ((current.entry_price * current.qty) + (price * report.filled_qty)) / max(total_qty, 1)
                self.upsert_position(symbol=symbol, side=PositionSide.LONG, qty=total_qty, entry_price=avg_price, entry_time=current.entry_time, stop_price=report.stop_price if report.stop_price is not None else current.stop_price, last_price=price, source='ibkr')
            else:
                self.upsert_position(symbol=symbol, side=PositionSide.LONG, qty=report.filled_qty, entry_price=price, entry_time=timestamp, stop_price=report.stop_price, last_price=price, source='ibkr')
            return

        if intent == TradeIntent.OPEN_SHORT:
            self.state['cash_estimate'] = current_cash + notional
            if current and current.side == PositionSide.SHORT:
                total_qty = current.qty + report.filled_qty
                avg_price = ((current.entry_price * current.qty) + (price * report.filled_qty)) / max(total_qty, 1)
                self.upsert_position(symbol=symbol, side=PositionSide.SHORT, qty=total_qty, entry_price=avg_price, entry_time=current.entry_time, stop_price=report.stop_price if report.stop_price is not None else current.stop_price, last_price=price, source='ibkr')
            else:
                self.upsert_position(symbol=symbol, side=PositionSide.SHORT, qty=report.filled_qty, entry_price=price, entry_time=timestamp, stop_price=report.stop_price, last_price=price, source='ibkr')
            return

        if intent == TradeIntent.CLOSE_LONG:
            self.state['cash_estimate'] = current_cash + notional
            if current and current.side == PositionSide.LONG:
                remaining = current.qty - report.filled_qty
                if remaining > 0:
                    self.upsert_position(symbol=symbol, side=PositionSide.LONG, qty=remaining, entry_price=current.entry_price, entry_time=current.entry_time, stop_price=current.stop_price, last_price=price, source='ibkr_partial_close')
                else:
                    self.close_position(symbol, reason='close_long_fill')
            return

        if intent == TradeIntent.CLOSE_SHORT:
            self.state['cash_estimate'] = current_cash - notional
            if current and current.side == PositionSide.SHORT:
                remaining = current.qty - report.filled_qty
                if remaining > 0:
                    self.upsert_position(symbol=symbol, side=PositionSide.SHORT, qty=remaining, entry_price=current.entry_price, entry_time=current.entry_time, stop_price=current.stop_price, last_price=price, source='ibkr_partial_close')
                else:
                    self.close_position(symbol, reason='close_short_fill')
            return

    def _record_fill_sync_window(self, *, received_count: int, new_count: int, latest_timestamp: str | None, latest_execution_id: str | None) -> None:
        windows = self.state.setdefault('fill_sync_windows', [])
        windows.append({
            'timestamp': self._timestamp(),
            'received_count': int(received_count),
            'new_count': int(new_count),
            'latest_timestamp': latest_timestamp,
            'latest_execution_id': latest_execution_id,
        })
        self.state['fill_sync_windows'] = windows[-100:]

    def record_broker_fills(self, fills: list[BrokerFillSnapshot]) -> None:
        cursor = self.state.setdefault('fill_cursor', {'last_seen_timestamp': None, 'last_seen_execution_id': None})
        last_seen = cursor.get('last_seen_timestamp')
        last_dt = None
        if last_seen:
            try:
                last_dt = datetime.fromisoformat(str(last_seen))
            except Exception:
                last_dt = None
        max_ts = last_dt
        latest_execution_id = cursor.get('last_seen_execution_id')
        existing_keys = {self._fill_key(existing) for existing in self.state.get('fill_history', [])}
        new_count = 0
        for fill in fills:
            row = fill.to_dict()
            row['source'] = 'broker_sync'
            key = self._fill_key(row)
            if key not in existing_keys:
                self._append_fill_history(row)
                existing_keys.add(key)
                new_count += 1
            try:
                ts = datetime.fromisoformat(row['timestamp'])
                if max_ts is None or ts > max_ts:
                    max_ts = ts
                    latest_execution_id = str(row.get('execution_id') or latest_execution_id)
                elif max_ts is not None and ts == max_ts and row.get('execution_id'):
                    latest_execution_id = str(row.get('execution_id'))
            except Exception:
                continue
        latest_ts_str = max_ts.isoformat() if max_ts is not None else cursor.get('last_seen_timestamp')
        if latest_ts_str is not None:
            cursor['last_seen_timestamp'] = latest_ts_str
        if latest_execution_id is not None:
            cursor['last_seen_execution_id'] = latest_execution_id
        self.state['fill_cursor'] = cursor
        self._record_fill_sync_window(received_count=len(fills), new_count=new_count, latest_timestamp=latest_ts_str, latest_execution_id=latest_execution_id)

    def sync_from_broker(self, snapshot: BrokerSyncSnapshot) -> None:
        existing = self.state.get('positions', {})
        new_positions: dict[str, Any] = {}
        for pos in snapshot.positions:
            prior = existing.get(pos.symbol.upper(), {})
            new_positions[pos.symbol.upper()] = {
                'symbol': pos.symbol.upper(),
                'side': pos.side.value,
                'qty': int(pos.qty),
                'entry_price': float(pos.avg_cost),
                'entry_time': prior.get('entry_time') or snapshot.timestamp.isoformat(),
                'stop_price': prior.get('stop_price'),
                'last_price': float(pos.market_price) if pos.market_price is not None else float(prior.get('last_price') or pos.avg_cost),
                'source': 'broker_sync',
            }
        self.state['positions'] = new_positions
        self.state['orders'] = []
        self.state['pending_orders'] = []
        self.state['stop_orders'] = []
        for order in snapshot.open_orders:
            row = {
                'order_id': order.order_id,
                'symbol': order.symbol,
                'qty': order.qty,
                'filled_qty': int(order.filled_qty),
                'remaining_qty': int(order.remaining_qty),
                'status': order.status,
                'side': order.side,
                'order_type': order.order_type,
                'parent_id': order.parent_id,
                'avg_fill_price': order.avg_fill_price,
                'bracket_id': order.parent_id or order.order_id,
                'perm_id': order.perm_id,
                'oca_group': order.oca_group,
                'transmit': order.transmit,
                'child_order_ids': list(order.child_order_ids or []),
            }
            if order.order_type.upper() == 'STP':
                row['stop_price'] = order.stop_price
                self.state['stop_orders'].append(row)
                pos = self.state['positions'].get(order.symbol.upper())
                if pos is not None and order.stop_price is not None:
                    pos['stop_price'] = order.stop_price
            else:
                self.state['orders'].append(row)
                if order.remaining_qty > 0 or not self._is_terminal(order.status):
                    self.state['pending_orders'].append(row)
            self._append_order_history(row, source='broker_sync')
        self._rebuild_bracket_groups_from_live_orders(snapshot.open_orders)
        self.record_broker_fills(snapshot.recent_fills)
        self.confirm_order_workflows()
        if snapshot.account is not None:
            account = snapshot.account.to_dict()
            self.state['account_snapshot'] = account
            if account.get('available_funds') is not None:
                self.state['cash_estimate'] = float(account['available_funds'])
            elif account.get('total_cash_value') is not None:
                self.state['cash_estimate'] = float(account['total_cash_value'])
        self.state['last_sync_at'] = snapshot.timestamp.isoformat()
        self.state['last_sync_source'] = 'ibkr'
        self._append_jsonl({'type': 'sync', **snapshot.to_dict()})
        self.save()

    def _fills_by_order_id(self) -> dict[str, int]:
        agg: dict[str, int] = {}
        for row in self.state.get('fill_history', []):
            order_id = row.get('order_id')
            if not order_id:
                continue
            agg[str(order_id)] = agg.get(str(order_id), 0) + abs(int(row.get('qty') or 0))
        return agg

    def recover_order_lifecycle(self, snapshot: BrokerSyncSnapshot | None = None) -> dict[str, Any]:
        open_ids = set()
        if snapshot is not None:
            open_ids = {str(order.order_id) for order in snapshot.open_orders if order.order_id}
        else:
            open_ids = {str(row.get('order_id')) for row in self.state.get('orders', []) + self.state.get('stop_orders', []) if row.get('order_id')}
        fills_by_order = self._fills_by_order_id()
        recovered_orders: list[dict[str, Any]] = []
        warnings: list[str] = []
        new_pending: list[dict[str, Any]] = []

        for row in self.state.get('pending_orders', []):
            current = dict(row)
            order_id = str(current.get('order_id') or '')
            qty = int(current.get('qty') or 0)
            known_fills = int(fills_by_order.get(order_id, current.get('filled_qty') or 0))
            if order_id in open_ids:
                current['filled_qty'] = max(int(current.get('filled_qty') or 0), known_fills)
                current['remaining_qty'] = max(int(current.get('remaining_qty') or 0), max(qty - current['filled_qty'], 0))
                new_pending.append(current)
                continue
            if known_fills >= qty > 0:
                current['filled_qty'] = known_fills
                current['remaining_qty'] = 0
                current['status'] = 'Filled'
                recovered_orders.append({'order_id': order_id, 'resolution': 'filled_from_history'})
                self._append_order_history(current, source='restart_recovery')
                continue
            if 0 < known_fills < qty:
                current['filled_qty'] = known_fills
                current['remaining_qty'] = max(qty - known_fills, 0)
                current['status'] = 'PartiallyFilled'
                new_pending.append(current)
                recovered_orders.append({'order_id': order_id, 'resolution': 'partial_from_history', 'remaining_qty': current['remaining_qty']})
                self._append_order_history(current, source='restart_recovery')
                continue
            symbol = str(current.get('symbol') or '').upper()
            if symbol and symbol not in self.state.get('positions', {}):
                current['status'] = 'UnknownTerminal'
                current['remaining_qty'] = 0
                recovered_orders.append({'order_id': order_id, 'resolution': 'closed_missing_after_restart'})
                self._append_order_history(current, source='restart_recovery')
            else:
                new_pending.append(current)
                warnings.append(f'{order_id}: still pending after restart with no explicit broker open-order match')

        self.state['pending_orders'] = new_pending[-200:]

        bracket_review: list[dict[str, Any]] = []
        for group in self.state.get('bracket_groups', []):
            symbol = str(group.get('symbol') or '').upper()
            pos = self.get_position(symbol) if symbol else None
            stop_qty = self.active_stop_qty(symbol) if symbol else 0
            if pos and stop_qty <= 0:
                group['status'] = 'degraded'
                warnings.append(f'{symbol}: bracket group present but no active protective stop')
            elif pos and stop_qty > 0:
                group['status'] = 'protected'
            elif not pos and stop_qty <= 0:
                group['status'] = 'closed'
            bracket_review.append({'bracket_id': group.get('bracket_id'), 'symbol': symbol, 'status': group.get('status')})

        report = {
            'timestamp': self._timestamp(),
            'recovered_orders': recovered_orders,
            'warnings': warnings,
            'bracket_review': bracket_review,
            'fill_history_count': len(self.state.get('fill_history', [])),
        }
        self.state['last_recovery'] = report
        self.state['recovery_history'] = (self.state.get('recovery_history', []) + [report])[-50:]
        self._append_jsonl({'type': 'recovery', **report})
        self.save()
        return report

    def active_stop_orders(self, symbol: str | None = None) -> list[dict[str, Any]]:
        rows = [row for row in self.state.get('stop_orders', []) if not self._is_terminal(row.get('status'))]
        if symbol is None:
            return rows
        return [row for row in rows if str(row.get('symbol', '')).upper() == symbol.upper()]

    def active_stop_qty(self, symbol: str) -> int:
        return sum(int(row.get('remaining_qty') or row.get('qty') or 0) for row in self.active_stop_orders(symbol))

    def replace_stop_orders(self, symbol: str, stop: BrokerOrderSnapshot | dict[str, Any], cancelled_ids: list[str] | None = None) -> None:
        cancelled_ids = cancelled_ids or []
        symbol_upper = symbol.upper()
        updated: list[dict[str, Any]] = []
        for row in self.state.get('stop_orders', []):
            row_copy = dict(row)
            if row_copy.get('order_id') in cancelled_ids:
                row_copy['status'] = 'Cancelled'
                row_copy['remaining_qty'] = 0
            if str(row_copy.get('symbol', '')).upper() == symbol_upper and row_copy.get('status') not in TERMINAL_ORDER_STATUSES:
                row_copy['status'] = 'Cancelled'
                row_copy['remaining_qty'] = 0
            updated.append(row_copy)
        if isinstance(stop, BrokerOrderSnapshot):
            row = stop.to_dict()
        else:
            row = dict(stop)
        row.setdefault('symbol', symbol_upper)
        row.setdefault('bracket_id', row.get('parent_id') or row.get('order_id'))
        updated.append(row)
        self.state['stop_orders'] = updated[-200:]
        pos = self.state.get('positions', {}).get(symbol_upper)
        if pos is not None and row.get('stop_price') is not None:
            pos['stop_price'] = float(row['stop_price'])
        self._update_bracket_group(symbol=symbol_upper, bracket_id=row.get('bracket_id'), parent_order_id=row.get('parent_id'), stop_order_id=row.get('order_id'), status='protected')
        self.save()

    def mark_stop_orders_cancelled(self, symbol: str | None = None, order_ids: list[str] | None = None) -> None:
        symbol_upper = symbol.upper() if symbol else None
        idset = set(order_ids or [])
        changed = False
        for row in self.state.get('stop_orders', []):
            if symbol_upper and str(row.get('symbol', '')).upper() != symbol_upper:
                continue
            if idset and row.get('order_id') not in idset:
                continue
            row['status'] = 'Cancelled'
            row['remaining_qty'] = 0
            changed = True
        if changed:
            self.save()

    def _retry_key(self, action: dict[str, Any]) -> str:
        base = {
            'action_type': action.get('action_type'),
            'symbol': action.get('symbol'),
            'qty': action.get('qty'),
            'stop_price': action.get('stop_price'),
            'order_ids': action.get('order_ids'),
        }
        return json.dumps(base, sort_keys=True, default=str)

    def enqueue_retry_action(self, action: dict[str, Any], reason: str | None = None) -> None:
        key = self._retry_key(action)
        queue = self.state.setdefault('retry_queue', [])
        for row in queue:
            if row.get('key') == key and row.get('status', 'pending') in {'pending', 'failed'}:
                row['last_error'] = reason
                row['last_seen_at'] = self._timestamp()
                self.save()
                return
        queue.append({'key': key, 'created_at': self._timestamp(), 'last_seen_at': self._timestamp(), 'last_attempt_at': None, 'attempts': 0, 'status': 'pending', 'last_error': reason, 'action': action})
        self.state['retry_queue'] = queue[-100:]
        self.save()

    def active_retry_actions(self) -> list[dict[str, Any]]:
        return [row for row in self.state.get('retry_queue', []) if row.get('status') in {'pending', 'failed'}]

    def mark_retry_result(self, key: str, *, success: bool, error: str | None = None) -> None:
        for row in self.state.get('retry_queue', []):
            if row.get('key') != key:
                continue
            row['attempts'] = int(row.get('attempts') or 0) + 1
            row['last_attempt_at'] = self._timestamp()
            row['status'] = 'done' if success else 'failed'
            row['last_error'] = error
        self.save()



    def plan_working_order_resume(
        self,
        *,
        stale_after_minutes: int = 30,
        workflow_timeout_minutes: int = 20,
        cancel_timeout_policy: str = 'retry_cancel',
        replace_timeout_policy: str = 'retry_replace',
        max_resume_attempts: int = 3,
    ) -> dict[str, Any]:
        workflows: list[dict[str, Any]] = []
        warnings: list[str] = []
        positions = self.state.get('positions', {})
        stops_by_symbol: dict[str, list[dict[str, Any]]] = {}
        for row in self.active_stop_orders():
            stops_by_symbol.setdefault(str(row.get('symbol', '')).upper(), []).append(row)
        now_dt = datetime.now(timezone.utc)
        for row in self.state.get('pending_orders', []):
            symbol = str(row.get('symbol') or '').upper()
            if not symbol:
                continue
            order_type = str(row.get('order_type') or '').upper()
            if order_type == 'STP':
                continue
            qty = int(row.get('qty') or 0)
            filled_qty = int(row.get('filled_qty') or 0)
            remaining_qty = int(row.get('remaining_qty') or max(qty - filled_qty, 0))
            submitted_at = row.get('submitted_at')
            age_minutes = None
            if submitted_at:
                try:
                    sub_dt = datetime.fromisoformat(str(submitted_at))
                    if sub_dt.tzinfo is None:
                        sub_dt = sub_dt.replace(tzinfo=timezone.utc)
                    age_minutes = max((now_dt - sub_dt).total_seconds() / 60.0, 0.0)
                except Exception:
                    age_minutes = None
            position = positions.get(symbol)
            lifecycle = ((self.state.get('order_lifecycle') or {}).get(str(row.get('order_id'))) or {}).get('state')
            if filled_qty > 0 and position is not None:
                stop_qty = sum(int(s.get('remaining_qty') or s.get('qty') or 0) for s in stops_by_symbol.get(symbol, []))
                if stop_qty != int(position.get('qty') or 0):
                    workflows.append({
                        'workflow_type': 'resume_protection',
                        'symbol': symbol,
                        'order_id': row.get('order_id'),
                        'position_qty': int(position.get('qty') or 0),
                        'filled_qty': filled_qty,
                        'stop_qty': stop_qty,
                        'reason': 'filled exposure is not fully protected',
                        'recommended_action': 'ENSURE_STOP',
                    })
                    continue
            if remaining_qty > 0 and age_minutes is not None and age_minutes >= float(stale_after_minutes):
                workflows.append({
                    'workflow_type': 'review_stale_order',
                    'symbol': symbol,
                    'order_id': row.get('order_id'),
                    'age_minutes': round(age_minutes, 2),
                    'filled_qty': filled_qty,
                    'remaining_qty': remaining_qty,
                    'reason': 'working order is stale and should be reviewed',
                    'recommended_action': 'MANUAL_REVIEW',
                })
            if lifecycle == 'UNKNOWN' and remaining_qty > 0:
                warnings.append(f'{symbol}: order {row.get("order_id")} has unknown lifecycle but still shows remaining quantity')

        active_order_ids = {
            str(row.get('order_id'))
            for row in (self.state.get('orders', []) + self.state.get('stop_orders', []))
            if row.get('order_id') and not self._is_terminal(row.get('status'))
        }
        actions: list[dict[str, Any]] = []
        action_keys: set[str] = set()

        def _add_action(action: dict[str, Any]) -> None:
            key = json.dumps(action, sort_keys=True, default=str)
            if key in action_keys:
                return
            workflow_id = action.get('source_workflow_id') or action.get('workflow_id')
            if workflow_id:
                queued = self.queue_workflow_resume_action(workflow_id=str(workflow_id), action=action, reason=str(action.get('reason') or 'workflow resume action'))
                action = dict(action)
                action['resume_queue_id'] = queued.get('resume_queue_id')
                key = json.dumps(action, sort_keys=True, default=str)
                if key in action_keys:
                    return
            action_keys.add(key)
            actions.append(action)

        for row in self.active_order_workflows():
            workflow_type = str(row.get('workflow_type') or '')
            workflow_id = str(row.get('workflow_id') or '')
            age_minutes = self._workflow_age_minutes(row)
            resume_count = int(row.get('resume_count') or 0)
            symbol = str(row.get('symbol') or '').upper()
            if workflow_type == 'cancel_confirm':
                row.setdefault('timeout_policy', cancel_timeout_policy)
                if age_minutes is not None and age_minutes >= float(workflow_timeout_minutes):
                    self.note_broker_timeout(
                        workflow_id=workflow_id,
                        symbol=symbol,
                        category='cancel_confirm',
                        policy=str(row.get('timeout_policy') or cancel_timeout_policy),
                        note='cancel workflow exceeded timeout window',
                    )
                    workflows.append({
                        'workflow_type': 'resume_cancel_confirm',
                        'symbol': symbol,
                        'workflow_id': workflow_id,
                        'age_minutes': round(age_minutes, 2),
                        'resume_count': resume_count,
                        'reason': 'cancel confirmation timed out',
                        'recommended_action': 'CANCEL_ORDER_IDS'
                        if str(row.get('timeout_policy') or cancel_timeout_policy) == 'retry_cancel' and resume_count < int(max_resume_attempts)
                        else 'MANUAL_REVIEW',
                    })
                    if str(row.get('timeout_policy') or cancel_timeout_policy) == 'retry_cancel' and resume_count < int(max_resume_attempts):
                        _add_action({
                            'action_type': 'CANCEL_ORDER_IDS',
                            'symbol': symbol,
                            'order_ids': row.get('target_order_ids') or [],
                            'reason': 'workflow timeout retry cancel',
                            'source_workflow_id': workflow_id,
                        })
                    else:
                        warnings.append(f'{symbol}: cancel workflow {workflow_id} exceeded retry budget or requires manual review')
                        _add_action({
                            'action_type': 'MARK_WORKFLOW_MANUAL_REVIEW',
                            'symbol': symbol,
                            'workflow_id': workflow_id,
                            'reason': 'cancel confirmation exceeded retry budget',
                        })
                continue
            if workflow_type != 'stop_resize':
                continue
            row.setdefault('timeout_policy', replace_timeout_policy)
            matching = self._find_matching_stop(
                symbol=symbol,
                desired_qty=row.get('desired_qty'),
                desired_stop_price=row.get('desired_stop_price'),
                position_side=row.get('position_side'),
            )
            target_active = any(str(oid) in active_order_ids for oid in (row.get('target_order_ids') or []))
            if row.get('state') == 'AWAITING_CANCEL_CONFIRM' and age_minutes is not None and age_minutes >= float(workflow_timeout_minutes):
                self.note_broker_timeout(
                    workflow_id=workflow_id,
                    symbol=symbol,
                    category='stop_resize_cancel',
                    policy='retry_cancel',
                    note='stop resize still waiting for old stop cancellation',
                )
                workflows.append({
                    'workflow_type': 'resume_stop_resize_cancel',
                    'symbol': symbol,
                    'workflow_id': workflow_id,
                    'age_minutes': round(age_minutes, 2),
                    'resume_count': resume_count,
                    'reason': 'old stop is still live after resize request',
                    'recommended_action': 'CANCEL_ORDER_IDS' if target_active and resume_count < int(max_resume_attempts) else 'MANUAL_REVIEW',
                })
                if target_active and resume_count < int(max_resume_attempts):
                    _add_action({
                        'action_type': 'CANCEL_ORDER_IDS',
                        'symbol': symbol,
                        'order_ids': row.get('target_order_ids') or [],
                        'reason': 'workflow timeout retry cancel before replace',
                        'source_workflow_id': workflow_id,
                    })
                else:
                    _add_action({
                        'action_type': 'MARK_WORKFLOW_MANUAL_REVIEW',
                        'symbol': symbol,
                        'workflow_id': workflow_id,
                        'reason': 'stop resize cancel phase exceeded retry budget',
                    })
            elif row.get('state') == 'AWAITING_REPLACE_CONFIRM' and matching is None and age_minutes is not None and age_minutes >= float(workflow_timeout_minutes):
                self.note_broker_timeout(
                    workflow_id=workflow_id,
                    symbol=symbol,
                    category='stop_resize_replace',
                    policy=str(row.get('timeout_policy') or replace_timeout_policy),
                    note='replacement stop not visible after timeout window',
                )
                queue_row = self.queue_pending_replace(
                    workflow_id=workflow_id,
                    symbol=symbol,
                    desired_qty=int(row.get('desired_qty') or 0),
                    desired_stop_price=float(row.get('desired_stop_price') or 0.0),
                    position_side=str(row.get('position_side') or ''),
                    replacement_order_id=str(row.get('replacement_order_id') or ''),
                    reason='workflow-level resume requested replacement stop retry',
                )
                workflows.append({
                    'workflow_type': 'resume_stop_resize_replace',
                    'symbol': symbol,
                    'workflow_id': workflow_id,
                    'queue_id': queue_row.get('queue_id'),
                    'age_minutes': round(age_minutes, 2),
                    'resume_count': resume_count,
                    'reason': 'replacement stop is still missing',
                    'recommended_action': 'RETRY_REPLACE_STOP'
                    if str(row.get('timeout_policy') or replace_timeout_policy) == 'retry_replace' and resume_count < int(max_resume_attempts)
                    else 'MANUAL_REVIEW',
                })
                if str(row.get('timeout_policy') or replace_timeout_policy) == 'retry_replace' and resume_count < int(max_resume_attempts):
                    _add_action({
                        'action_type': 'RETRY_REPLACE_STOP',
                        'symbol': symbol,
                        'qty': int(row.get('desired_qty') or 0),
                        'stop_price': float(row.get('desired_stop_price') or 0.0),
                        'position_side': str(row.get('position_side') or ''),
                        'workflow_id': workflow_id,
                        'queue_id': queue_row.get('queue_id'),
                        'reason': 'workflow timeout retry replace protective stop',
                    })
                else:
                    warnings.append(f'{symbol}: stop resize workflow {workflow_id} exceeded retry budget or requires manual review')
                    _add_action({
                        'action_type': 'MARK_WORKFLOW_MANUAL_REVIEW',
                        'symbol': symbol,
                        'workflow_id': workflow_id,
                        'reason': 'replacement stop missing after retry budget exhausted',
                    })

        for row in self.active_pending_replace_queue():
            workflow_id = str(row.get('workflow_id') or '')
            age_minutes = self._workflow_age_minutes(row)
            attempts = int(row.get('attempts') or 0)
            symbol = str(row.get('symbol') or '').upper()
            if age_minutes is None or age_minutes < float(workflow_timeout_minutes):
                continue
            if attempts >= int(max_resume_attempts):
                warnings.append(f"{symbol}: pending replace queue {row.get('queue_id')} exceeded retry budget")
                _add_action({
                    'action_type': 'MARK_WORKFLOW_MANUAL_REVIEW',
                    'symbol': symbol,
                    'workflow_id': workflow_id,
                    'reason': f"pending replace queue {row.get('queue_id')} exceeded retry budget",
                })
                continue
            _add_action({
                'action_type': 'RETRY_REPLACE_STOP',
                'symbol': symbol,
                'qty': int(row.get('desired_qty') or 0),
                'stop_price': float(row.get('desired_stop_price') or 0.0),
                'position_side': str(row.get('position_side') or ''),
                'workflow_id': workflow_id,
                'queue_id': row.get('queue_id'),
                'reason': 'pending replace queue resume',
            })

        self.state['working_order_workflows'] = workflows[-200:]
        review = {
            'timestamp': self._timestamp(),
            'workflows': self.state['working_order_workflows'],
            'warnings': warnings,
            'count': len(self.state['working_order_workflows']),
            'actions': actions,
        }
        self.state['workflow_resume_history'] = (self.state.get('workflow_resume_history', []) + [review])[-100:]
        self.save()
        return review
    def plan_reconciliation(self) -> dict[str, Any]:
        actions: list[dict[str, Any]] = []
        workflow_review = self.plan_working_order_resume()
        warnings: list[str] = list(workflow_review.get('warnings', []))
        positions = self.list_positions()
        active_stops = self.active_stop_orders()
        stops_by_symbol: dict[str, list[dict[str, Any]]] = {}
        for row in active_stops:
            stops_by_symbol.setdefault(str(row.get('symbol', '')).upper(), []).append(row)

        for symbol, pos in positions.items():
            expected_side = 'SELL' if pos.side == PositionSide.LONG else 'BUY'
            stop_rows = stops_by_symbol.get(symbol.upper(), [])
            active_qty = sum(int(row.get('remaining_qty') or row.get('qty') or 0) for row in stop_rows)
            if pos.stop_price in (None, 0):
                warnings.append(f'{symbol}: position has no protective stop price in runtime state')
                continue
            if not stop_rows:
                actions.append({'action_type': 'ENSURE_STOP', 'symbol': symbol.upper(), 'position_side': pos.side.value, 'qty': int(pos.qty), 'stop_price': float(pos.stop_price), 'reason': 'missing stop'})
                continue
            needs_resize = False
            reason_bits: list[str] = []
            if active_qty != int(pos.qty):
                needs_resize = True
                reason_bits.append(f'stop qty {active_qty} != position qty {pos.qty}')
            if any(str(row.get('side', '')).upper() != expected_side for row in stop_rows):
                needs_resize = True
                reason_bits.append('wrong stop side')
            if any(row.get('stop_price') is not None and abs(float(row.get('stop_price')) - float(pos.stop_price)) > 1e-9 for row in stop_rows):
                needs_resize = True
                reason_bits.append('stop price drift')
            if needs_resize:
                actions.append({
                    'action_type': 'RESIZE_STOP',
                    'symbol': symbol.upper(),
                    'position_side': pos.side.value,
                    'qty': int(pos.qty),
                    'stop_price': float(pos.stop_price),
                    'existing_order_ids': [str(row.get('order_id')) for row in stop_rows if row.get('order_id')],
                    'reason': '; '.join(reason_bits) or 'resize protective stop',
                })

        for symbol, rows in stops_by_symbol.items():
            if symbol in positions:
                continue
            order_ids = [str(row.get('order_id')) for row in rows if row.get('order_id')]
            if order_ids:
                actions.append({'action_type': 'CANCEL_ORDER_IDS', 'symbol': symbol, 'order_ids': order_ids, 'reason': 'orphan stop without live position'})
            else:
                actions.append({'action_type': 'CANCEL_SYMBOL_STOPS', 'symbol': symbol, 'order_ids': [], 'reason': 'orphan stop without live position'})

        pending = [{'order_id': row.get('order_id'), 'symbol': row.get('symbol'), 'filled_qty': row.get('filled_qty'), 'remaining_qty': row.get('remaining_qty'), 'status': row.get('status')} for row in self.state.get('pending_orders', [])]
        plan = {'timestamp': self._timestamp(), 'actions': actions, 'warnings': warnings, 'pending_orders': pending}
        self.state['last_reconciliation'] = plan
        self.state['reconciliation_history'] = (self.state.get('reconciliation_history', []) + [plan])[-50:]
        self.save()
        return plan

    def record_run(self, decisions: list[dict[str, Any]], executions: list[dict[str, Any]] | None = None, session_info: dict[str, Any] | None = None, warnings: list[str] | None = None, reconciliation: dict[str, Any] | None = None) -> None:
        run = {'timestamp': self._timestamp(), 'session_info': session_info or {}, 'decisions': decisions, 'executions': executions or [], 'warnings': warnings or [], 'reconciliation': reconciliation or {}}
        self.state['last_run'] = run['timestamp']
        self.state['last_decisions'] = decisions
        self.state['run_history'] = (self.state.get('run_history', []) + [run])[-50:]
        self.state['warnings'] = (self.state.get('warnings', []) + [{'timestamp': run['timestamp'], 'message': w} for w in (warnings or [])])[-200:]
        self._append_jsonl({'type': 'run', **run})
        for warning in (warnings or []):
            self.create_operator_alert(category='run_warning', severity='warning', message=str(warning), details={'timestamp': run['timestamp']}, dedupe_key=f"run_warning:{warning}")
        self.save()
