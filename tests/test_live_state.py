from datetime import datetime, timezone
from pathlib import Path

from trading_bot.live.execution import BrokerAccountSnapshot, BrokerOrderSnapshot, BrokerPositionSnapshot, BrokerSyncSnapshot, ExecutionReport
from trading_bot.live.state import RuntimeStateStore
from trading_bot.types import PositionSide


def test_runtime_state_tracks_open_and_close_execution(tmp_path: Path):
    store = RuntimeStateStore(tmp_path / 'state.json', execution_journal_path=tmp_path / 'journal.jsonl')
    store.set_cash_estimate(100000)

    open_report = ExecutionReport(
        symbol='AAPL',
        intent='OPEN_LONG',
        broker_side='BUY',
        requested_qty=10,
        filled_qty=10,
        remaining_qty=0,
        status='Filled',
        submitted_at=datetime(2026, 3, 20, tzinfo=timezone.utc),
        avg_fill_price=150.0,
        order_id='1',
        stop_order_id='2',
        stop_price=145.0,
        stop_status='Submitted',
    )
    store.record_execution(open_report)
    pos = store.get_position('AAPL')
    assert pos is not None
    assert pos.side == PositionSide.LONG
    assert pos.qty == 10
    assert store.state['cash_estimate'] == 98500.0

    close_report = ExecutionReport(
        symbol='AAPL',
        intent='CLOSE_LONG',
        broker_side='SELL',
        requested_qty=10,
        filled_qty=10,
        remaining_qty=0,
        status='Filled',
        submitted_at=datetime(2026, 3, 20, 12, tzinfo=timezone.utc),
        avg_fill_price=155.0,
        order_id='3',
        cancelled_stop_ids=['2'],
    )
    store.record_execution(close_report)
    assert store.get_position('AAPL') is None
    assert store.state['cash_estimate'] == 100050.0
    assert any(row['status'] == 'Cancelled' for row in store.state['stop_orders'])


def test_runtime_state_handles_partial_close_without_dropping_position(tmp_path: Path):
    store = RuntimeStateStore(tmp_path / 'state.json')
    store.set_cash_estimate(100000)
    store.upsert_position(
        symbol='MSFT',
        side=PositionSide.LONG,
        qty=10,
        entry_price=100.0,
        entry_time=datetime(2026, 3, 20, tzinfo=timezone.utc),
        stop_price=95.0,
        last_price=100.0,
    )
    report = ExecutionReport(
        symbol='MSFT',
        intent='CLOSE_LONG',
        broker_side='SELL',
        requested_qty=10,
        filled_qty=4,
        remaining_qty=6,
        status='PartiallyFilled',
        submitted_at=datetime(2026, 3, 20, 13, tzinfo=timezone.utc),
        avg_fill_price=101.0,
        order_id='close-1',
        cancelled_stop_ids=['legacy-stop'],
    )
    store.record_execution(report)
    pos = store.get_position('MSFT')
    assert pos is not None
    assert pos.qty == 6
    assert any(row['order_id'] == 'close-1' for row in store.state['pending_orders'])


def test_runtime_state_can_sync_from_broker_snapshot(tmp_path: Path):
    store = RuntimeStateStore(tmp_path / 'state.json')
    snap = BrokerSyncSnapshot(
        timestamp=datetime(2026, 3, 20, tzinfo=timezone.utc),
        positions=[BrokerPositionSnapshot(symbol='MSFT', side=PositionSide.SHORT, qty=5, avg_cost=300.0)],
        open_orders=[
            BrokerOrderSnapshot(order_id='11', symbol='MSFT', side='BUY', qty=5, status='Submitted', order_type='STP', stop_price=315.0, remaining_qty=5),
            BrokerOrderSnapshot(order_id='12', symbol='MSFT', side='SELL', qty=10, status='PartiallyFilled', order_type='MKT', filled_qty=3, remaining_qty=7),
        ],
        account=BrokerAccountSnapshot(
            timestamp=datetime(2026, 3, 20, tzinfo=timezone.utc),
            net_liquidation=123456.0,
            available_funds=65432.0,
            unrealized_pnl=1200.0,
            realized_pnl=-50.0,
        ),
    )
    store.sync_from_broker(snap)
    pos = store.get_position('MSFT')
    assert pos is not None
    assert pos.side == PositionSide.SHORT
    assert pos.stop_price == 315.0
    assert len(store.state['stop_orders']) == 1
    assert len(store.state['pending_orders']) == 1
    assert store.state['account_snapshot']['net_liquidation'] == 123456.0


def test_reconciliation_plan_detects_stop_qty_drift(tmp_path: Path):
    store = RuntimeStateStore(tmp_path / 'state.json')
    store.upsert_position(
        symbol='AAA',
        side=PositionSide.LONG,
        qty=9,
        entry_price=100.0,
        entry_time=datetime(2026, 3, 20, tzinfo=timezone.utc),
        stop_price=95.0,
        last_price=100.0,
    )
    store.state['stop_orders'] = [{'order_id': 'stop-1', 'symbol': 'AAA', 'qty': 4, 'remaining_qty': 4, 'status': 'Submitted', 'side': 'SELL', 'order_type': 'STP', 'stop_price': 95.0}]
    plan = store.plan_reconciliation()
    assert any(action['action_type'] == 'RESIZE_STOP' for action in plan['actions'])
