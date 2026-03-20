from datetime import datetime, timezone
from pathlib import Path

from trading_bot.live.execution import BrokerAccountSnapshot, BrokerOrderSnapshot, BrokerPositionSnapshot, BrokerSyncSnapshot, ExecutionReport
from trading_bot.live.runner import build_live_runtime, process_retry_queue, reconcile_live_state, run_live_cycle
from trading_bot.types import PositionSide, TradeIntent


class FakeExecutor:
    def __init__(self, *args, **kwargs):
        self.calls = []
        self.stop_repairs = []
        self.resize_repairs = []
        self.cancelled = []

    def sync_account_snapshot(self, *args, **kwargs):
        return BrokerSyncSnapshot(
            timestamp=datetime(2026, 3, 20, tzinfo=timezone.utc),
            positions=[],
            open_orders=[],
            account=BrokerAccountSnapshot(
                timestamp=datetime(2026, 3, 20, tzinfo=timezone.utc),
                net_liquidation=100000.0,
                available_funds=80000.0,
            ),
        )

    def execute(self, **kwargs):
        self.calls.append(kwargs)
        return ExecutionReport(
            symbol=kwargs['symbol'],
            intent=kwargs['intent'].value,
            broker_side='SELL',
            requested_qty=kwargs['qty'],
            filled_qty=kwargs['qty'],
            remaining_qty=0,
            status='Filled',
            submitted_at=datetime(2026, 3, 20),
            avg_fill_price=200.0,
            order_id='99',
        )

    def ensure_protective_stop(self, **kwargs):
        self.stop_repairs.append(kwargs)
        return BrokerOrderSnapshot(
            order_id='new-stop',
            symbol=kwargs['symbol'],
            side='SELL' if kwargs['position_side'] == PositionSide.LONG else 'BUY',
            qty=kwargs['qty'],
            status='Submitted',
            order_type='STP',
            stop_price=kwargs['stop_price'],
            remaining_qty=kwargs['qty'],
        )

    def resize_protective_stop(self, **kwargs):
        self.resize_repairs.append(kwargs)
        return (
            BrokerOrderSnapshot(
                order_id='resized-stop',
                symbol=kwargs['symbol'],
                side='SELL' if kwargs['position_side'] == PositionSide.LONG else 'BUY',
                qty=kwargs['qty'],
                status='Submitted',
                order_type='STP',
                stop_price=kwargs['stop_price'],
                remaining_qty=kwargs['qty'],
            ),
            kwargs.get('existing_order_ids') or [],
        )

    def cancel_symbol_stops(self, symbol):
        self.cancelled.append(symbol)
        return ['old-stop']


class FlakyExecutor(FakeExecutor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fail_once = True

    def ensure_protective_stop(self, **kwargs):
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError('temporary gateway failure')
        return super().ensure_protective_stop(**kwargs)


def _demo_cfg(tmp_path: Path) -> Path:
    root = Path(__file__).resolve().parents[1]
    cfg_src = root / 'examples' / 'config' / 'demo.yaml'
    cfg_path = tmp_path / 'demo.yaml'
    cfg_text = cfg_src.read_text(encoding='utf-8')
    prices_dir = (root / 'examples' / 'data' / 'prices').as_posix()
    sent_csv = (root / 'examples' / 'data' / 'sentiment_snapshots.csv').as_posix()
    current_json = (root / 'examples' / 'data' / 'current_sentiment.json').as_posix()
    cfg_text = cfg_text.replace('../data/prices', prices_dir).replace('../data/sentiment_snapshots.csv', sent_csv).replace('../data/current_sentiment.json', current_json)
    cfg_text += '\nlive:\n  state_path: runtime/live_state.json\n  execution_journal_path: runtime/execution_journal.jsonl\n  sync_on_start: false\n  process_retry_queue: true\n  reconcile_protection_on_start: true\n  broker:\n    host: 127.0.0.1\n    port: 4002\n    client_id: 7\n'
    cfg_path.write_text(cfg_text, encoding='utf-8')
    return cfg_path


def test_run_live_cycle_uses_persisted_position_qty_for_exit(tmp_path: Path, monkeypatch):
    cfg_path = _demo_cfg(tmp_path)
    runtime = build_live_runtime(cfg_path)
    runtime.state.upsert_position(
        symbol='AAA',
        side='LONG',
        qty=7,
        entry_price=100.0,
        entry_time=datetime(2026, 3, 19),
        stop_price=95.0,
        last_price=100.0,
    )
    fake = FakeExecutor()
    monkeypatch.setattr('trading_bot.live.runner._build_executor', lambda raw: fake)

    class FakeStrategy:
        def decide(self, **kwargs):
            return type('D', (), {'intent': TradeIntent.CLOSE_LONG, 'score': -0.5, 'reason': 'forced exit', 'stop_atr': 1.0})()

    monkeypatch.setattr('trading_bot.live.runner.TrendSentimentStrategy', lambda *args, **kwargs: FakeStrategy())
    monkeypatch.setattr('trading_bot.live.runner.resolve_session', lambda raw: type('S', (), {'now': datetime(2026, 3, 20), 'active_session': 'us', 'market_open': True, 'reason': 'test', 'watchlist': ['AAA']})())

    result = run_live_cycle(runtime, execute=True)
    trade_execs = [row for row in result['executions'] if row.get('requested_qty') is not None]
    assert trade_execs[0]['requested_qty'] == 7
    assert runtime.state.get_position('AAA') is None


def test_reconcile_live_repairs_mismatched_stop_qty(tmp_path: Path, monkeypatch):
    cfg_path = _demo_cfg(tmp_path)
    runtime = build_live_runtime(cfg_path)
    runtime.state.upsert_position(
        symbol='AAA',
        side='LONG',
        qty=9,
        entry_price=100.0,
        entry_time=datetime(2026, 3, 19, tzinfo=timezone.utc),
        stop_price=95.0,
        last_price=100.0,
    )
    runtime.state.state['stop_orders'] = [{'order_id': 'legacy-stop', 'symbol': 'AAA', 'qty': 4, 'remaining_qty': 4, 'status': 'Submitted', 'side': 'SELL', 'order_type': 'STP', 'stop_price': 95.0}]
    fake = FakeExecutor()
    monkeypatch.setattr('trading_bot.live.runner._build_executor', lambda raw: fake)
    monkeypatch.setattr(fake, 'sync_account_snapshot', lambda *args, **kwargs: BrokerSyncSnapshot(
        timestamp=datetime(2026, 3, 20, tzinfo=timezone.utc),
        positions=[BrokerPositionSnapshot(symbol='AAA', side=PositionSide.LONG, qty=9, avg_cost=100.0)],
        open_orders=[BrokerOrderSnapshot(order_id='legacy-stop', symbol='AAA', side='SELL', qty=4, status='Submitted', order_type='STP', stop_price=95.0, remaining_qty=4)],
    ))
    result = reconcile_live_state(runtime, execute=True)
    assert any(item['action']['action_type'] == 'RESIZE_STOP' for item in result['applied'])
    assert fake.resize_repairs[0]['qty'] == 9


def test_retry_queue_can_replay_failed_reconciliation(tmp_path: Path, monkeypatch):
    cfg_path = _demo_cfg(tmp_path)
    runtime = build_live_runtime(cfg_path)
    runtime.state.enqueue_retry_action({'action_type': 'ENSURE_STOP', 'symbol': 'AAA', 'position_side': 'LONG', 'qty': 5, 'stop_price': 95.0}, reason='seeded')
    flaky = FlakyExecutor()
    monkeypatch.setattr('trading_bot.live.runner._build_executor', lambda raw: flaky)
    result_first = process_retry_queue(runtime, execute=True)
    assert result_first['warnings']
    assert runtime.state.active_retry_actions()
    result_second = process_retry_queue(runtime, execute=True)
    assert not result_second['warnings']
    assert not runtime.state.active_retry_actions()
