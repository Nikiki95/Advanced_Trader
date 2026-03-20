from datetime import datetime, timezone
from pathlib import Path

from trading_bot.live.execution import ExecutionReport
from trading_bot.live.state import RuntimeStateStore


def test_sqlite_backend_roundtrip(tmp_path: Path):
    db_path = tmp_path / 'live_state.db'
    store = RuntimeStateStore(db_path)
    assert store.backend == 'sqlite'
    store.set_cash_estimate(123.0)
    store.upsert_position(
        symbol='AAA',
        side='LONG',
        qty=2,
        entry_price=10.0,
        entry_time=datetime(2026, 3, 20, tzinfo=timezone.utc),
        stop_price=9.0,
        last_price=10.0,
    )
    # reload
    store2 = RuntimeStateStore(db_path)
    assert store2.backend == 'sqlite'
    assert store2.state['cash_estimate'] == 123.0
    assert store2.get_position('AAA') is not None


def test_order_lifecycle_state_machine_updates_from_execution_reports(tmp_path: Path):
    store = RuntimeStateStore(tmp_path / 'state.json')
    report = ExecutionReport(
        symbol='AAA',
        intent='OPEN_LONG',
        broker_side='BUY',
        requested_qty=10,
        filled_qty=0,
        remaining_qty=10,
        status='Submitted',
        submitted_at=datetime(2026, 3, 20, tzinfo=timezone.utc),
        order_id='order-1',
    )
    store.record_execution(report)
    lifecycle = store.state['order_lifecycle']['order-1']
    assert lifecycle['state'] == 'WORKING'

    report2 = ExecutionReport(
        symbol='AAA',
        intent='OPEN_LONG',
        broker_side='BUY',
        requested_qty=10,
        filled_qty=10,
        remaining_qty=0,
        status='Filled',
        submitted_at=datetime(2026, 3, 20, 1, tzinfo=timezone.utc),
        avg_fill_price=10.0,
        order_id='order-1',
    )
    store.record_execution(report2)
    lifecycle2 = store.state['order_lifecycle']['order-1']
    assert lifecycle2['state'] == 'FILLED'


def test_reconciliation_prefers_scoped_cancel_for_orphan_stops(tmp_path: Path):
    store = RuntimeStateStore(tmp_path / 'state.json')
    store.state['stop_orders'] = [
        {
            'order_id': 'stop-1',
            'symbol': 'AAA',
            'qty': 2,
            'remaining_qty': 2,
            'status': 'Submitted',
            'side': 'SELL',
            'order_type': 'STP',
            'stop_price': 9.0,
        }
    ]
    plan = store.plan_reconciliation()
    assert any(a['action_type'] == 'CANCEL_ORDER_IDS' for a in plan['actions'])
