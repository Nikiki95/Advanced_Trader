from datetime import datetime, timezone
from pathlib import Path

from trading_bot.live.execution import BrokerFillSnapshot, BrokerPositionSnapshot, BrokerSyncSnapshot, ExecutionReport
from trading_bot.live.runner import build_live_runtime, recover_live_state
from trading_bot.live.state import RuntimeStateStore
from trading_bot.types import PositionSide


class RecoveryExecutor:
    def __init__(self, snapshot):
        self.snapshot = snapshot

    def sync_account_snapshot(self, *args, **kwargs):
        return self.snapshot

    def ensure_protective_stop(self, **kwargs):
        raise AssertionError('not expected in dry recovery test')

    def cancel_symbol_stops(self, symbol):
        return []


def test_runtime_state_recovery_uses_fill_history_to_resolve_pending_order(tmp_path: Path):
    store = RuntimeStateStore(tmp_path / 'state.json')
    store.state['pending_orders'] = [
        {
            'order_id': 'entry-1',
            'symbol': 'AAA',
            'qty': 5,
            'filled_qty': 0,
            'remaining_qty': 5,
            'status': 'Submitted',
        }
    ]
    store.record_broker_fills(
        [
            BrokerFillSnapshot(
                execution_id='fill-1',
                order_id='entry-1',
                symbol='AAA',
                side='BUY',
                qty=5,
                price=101.0,
                timestamp=datetime(2026, 3, 20, tzinfo=timezone.utc),
            )
        ]
    )
    report = store.recover_order_lifecycle()
    assert not store.state['pending_orders']
    assert report['recovered_orders'][0]['resolution'] == 'filled_from_history'


def test_runtime_state_tracks_bracket_group_from_entry_execution(tmp_path: Path):
    store = RuntimeStateStore(tmp_path / 'state.json')
    report = ExecutionReport(
        symbol='AAPL',
        intent='OPEN_LONG',
        broker_side='BUY',
        requested_qty=10,
        filled_qty=10,
        remaining_qty=0,
        status='Filled',
        submitted_at=datetime(2026, 3, 20, tzinfo=timezone.utc),
        avg_fill_price=150.0,
        order_id='parent-1',
        parent_order_id='parent-1',
        bracket_id='bracket-1',
        stop_order_id='stop-1',
        stop_price=145.0,
        stop_status='Submitted',
        child_order_ids=['stop-1'],
    )
    store.record_execution(report)
    assert store.state['bracket_groups']
    group = store.state['bracket_groups'][0]
    assert group['bracket_id'] == 'bracket-1'
    assert group['status'] == 'protected'
    assert 'stop-1' in group['stop_order_ids']


def test_recover_live_state_flags_degraded_bracket_without_active_stop(tmp_path: Path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    cfg_src = root / 'examples' / 'config' / 'demo.yaml'
    cfg_path = tmp_path / 'demo.yaml'
    cfg_text = cfg_src.read_text(encoding='utf-8')
    prices_dir = (root / 'examples' / 'data' / 'prices').as_posix()
    sent_csv = (root / 'examples' / 'data' / 'sentiment_snapshots.csv').as_posix()
    current_json = (root / 'examples' / 'data' / 'current_sentiment.json').as_posix()
    cfg_text = cfg_text.replace('../data/prices', prices_dir).replace('../data/sentiment_snapshots.csv', sent_csv).replace('../data/current_sentiment.json', current_json)
    cfg_text += '\nlive:\n  state_path: runtime/live_state.json\n  execution_journal_path: runtime/execution_journal.jsonl\n  sync_on_start: true\n  recover_on_start: true\n  reconcile_protection_on_start: false\n  process_retry_queue: false\n  broker:\n    host: 127.0.0.1\n    port: 4002\n    client_id: 7\n'
    cfg_path.write_text(cfg_text, encoding='utf-8')

    runtime = build_live_runtime(cfg_path)
    runtime.state.state['bracket_groups'] = [
        {
            'bracket_id': 'bracket-1',
            'symbol': 'AAA',
            'parent_order_id': 'parent-1',
            'stop_order_ids': ['stop-1'],
            'child_order_ids': ['stop-1'],
            'status': 'open',
            'created_at': datetime(2026, 3, 19, tzinfo=timezone.utc).isoformat(),
            'last_seen_at': datetime(2026, 3, 19, tzinfo=timezone.utc).isoformat(),
            'position_side': 'LONG',
        }
    ]
    runtime.state.save()

    snapshot = BrokerSyncSnapshot(
        timestamp=datetime(2026, 3, 20, tzinfo=timezone.utc),
        positions=[BrokerPositionSnapshot(symbol='AAA', side=PositionSide.LONG, qty=5, avg_cost=100.0)],
        open_orders=[],
        recent_fills=[],
    )
    monkeypatch.setattr('trading_bot.live.runner._build_executor', lambda raw: RecoveryExecutor(snapshot))
    result = recover_live_state(runtime, execute=False)
    assert any('no active protective stop' in warning for warning in result['warnings'])
    assert runtime.state.state['last_recovery']['bracket_review'][0]['status'] == 'degraded'
