from datetime import datetime, timedelta, timezone
from pathlib import Path

from trading_bot.live.execution import BrokerFillSnapshot, BrokerOrderSnapshot, BrokerSyncSnapshot
from trading_bot.live.state import RuntimeStateStore


def test_fill_cursor_tracks_execution_id_and_sync_windows(tmp_path: Path):
    store = RuntimeStateStore(tmp_path / 'state.json')
    fill = BrokerFillSnapshot(
        execution_id='exec-1',
        order_id='order-1',
        symbol='AAA',
        side='BUY',
        qty=2,
        price=10.0,
        timestamp=datetime(2026, 3, 20, tzinfo=timezone.utc),
    )
    store.record_broker_fills([fill])
    cursor = store.state['fill_cursor']
    assert cursor['last_seen_execution_id'] == 'exec-1'
    assert len(store.state['fill_sync_windows']) == 1
    assert store.state['fill_sync_windows'][0]['new_count'] == 1


def test_broker_sync_rebuilds_child_order_visibility(tmp_path: Path):
    store = RuntimeStateStore(tmp_path / 'state.json')
    snap = BrokerSyncSnapshot(
        timestamp=datetime(2026, 3, 20, tzinfo=timezone.utc),
        positions=[],
        open_orders=[
            BrokerOrderSnapshot(order_id='1', symbol='AAA', side='BUY', qty=5, status='Submitted', order_type='LMT', child_order_ids=['2', '3']),
            BrokerOrderSnapshot(order_id='2', symbol='AAA', side='SELL', qty=5, status='Submitted', order_type='STP', parent_id='1'),
        ],
    )
    store.sync_from_broker(snap)
    groups = store.state['bracket_groups']
    assert groups
    group = groups[0]
    assert '2' in group['child_order_ids']
    assert '2' in group['live_children']


def test_working_order_resume_detects_stale_and_unprotected_orders(tmp_path: Path):
    store = RuntimeStateStore(tmp_path / 'state.json')
    old_ts = (datetime.now(timezone.utc) - timedelta(minutes=90)).isoformat()
    store.state['pending_orders'] = [
        {
            'order_id': 'ord-1',
            'symbol': 'AAA',
            'qty': 10,
            'filled_qty': 0,
            'remaining_qty': 10,
            'status': 'Submitted',
            'order_type': 'LMT',
            'submitted_at': old_ts,
        },
        {
            'order_id': 'ord-2',
            'symbol': 'BBB',
            'qty': 10,
            'filled_qty': 4,
            'remaining_qty': 6,
            'status': 'PartiallyFilled',
            'order_type': 'LMT',
            'submitted_at': old_ts,
        },
    ]
    store.state['positions'] = {
        'BBB': {
            'symbol': 'BBB',
            'side': 'LONG',
            'qty': 4,
            'entry_price': 10.0,
            'entry_time': datetime(2026, 3, 20, tzinfo=timezone.utc).isoformat(),
            'stop_price': 9.0,
            'last_price': 10.0,
            'source': 'test',
        }
    }
    review = store.plan_working_order_resume(stale_after_minutes=30)
    kinds = {row['workflow_type'] for row in review['workflows']}
    assert 'review_stale_order' in kinds
    assert 'resume_protection' in kinds
