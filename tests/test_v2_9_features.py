from datetime import datetime, timezone
from pathlib import Path

from trading_bot.live.execution import BrokerAccountSnapshot, BrokerOrderSnapshot, BrokerSyncSnapshot, ExecutionReport
from trading_bot.live.runner import build_live_runtime, decide_operator_request, monitor_live_state, resolve_operator_alert, run_live_cycle
from trading_bot.live.status import collect_health_snapshot
from trading_bot.types import TradeIntent


class FakeExecutor:
    def __init__(self):
        self.calls = []

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
        return BrokerOrderSnapshot(
            order_id='stop-1',
            symbol=kwargs['symbol'],
            side='BUY' if kwargs['position_side'].value == 'SHORT' else 'SELL',
            qty=kwargs['qty'],
            status='Submitted',
            order_type='STP',
            stop_price=kwargs['stop_price'],
            remaining_qty=kwargs['qty'],
        )


def _demo_cfg(tmp_path: Path, *, require_approval: bool = True) -> Path:
    root = Path(__file__).resolve().parents[1]
    cfg_src = root / 'examples' / 'config' / 'demo.yaml'
    cfg_path = tmp_path / 'demo.yaml'
    cfg_text = cfg_src.read_text(encoding='utf-8')
    prices_dir = (root / 'examples' / 'data' / 'prices').as_posix()
    sent_csv = (root / 'examples' / 'data' / 'sentiment_snapshots.csv').as_posix()
    current_json = (root / 'examples' / 'data' / 'current_sentiment.json').as_posix()
    cfg_text = cfg_text.replace('../data/prices', prices_dir).replace('../data/sentiment_snapshots.csv', sent_csv).replace('../data/current_sentiment.json', current_json)
    cfg_text += '\nlive:\n  state_path: runtime/live_state.json\n  execution_journal_path: runtime/execution_journal.jsonl\n  sync_on_start: false\n  process_retry_queue: false\n  reconcile_protection_on_start: false\n  require_operator_approval: %s\n  approval_intents: [OPEN_SHORT]\n  approval_ttl_minutes: 120\n  broker:\n    host: 127.0.0.1\n    port: 4002\n    client_id: 7\n' % ('true' if require_approval else 'false')
    cfg_path.write_text(cfg_text, encoding='utf-8')
    return cfg_path


def test_run_live_cycle_blocks_short_until_operator_approval(tmp_path: Path, monkeypatch):
    cfg_path = _demo_cfg(tmp_path, require_approval=True)
    runtime = build_live_runtime(cfg_path)
    fake = FakeExecutor()
    monkeypatch.setattr('trading_bot.live.runner._build_executor', lambda raw: fake)

    class FakeStrategy:
        def decide(self, **kwargs):
            return type('D', (), {'intent': TradeIntent.OPEN_SHORT, 'score': -0.8, 'reason': 'forced short', 'stop_atr': 1.0})()

    monkeypatch.setattr('trading_bot.live.runner.TrendSentimentStrategy', lambda *args, **kwargs: FakeStrategy())
    monkeypatch.setattr('trading_bot.live.runner.resolve_session', lambda raw: type('S', (), {'now': datetime(2026, 3, 20), 'active_session': 'us', 'market_open': True, 'reason': 'test', 'watchlist': ['AAA']})())

    result = run_live_cycle(runtime, execute=True)
    assert not result['executions']
    approvals = runtime.state.active_approval_requests()
    assert len(approvals) == 1
    assert approvals[0]['action_type'] == 'OPEN_SHORT'
    assert fake.calls == []
    assert any('operator approval' in row for row in result['warnings'])


def test_approved_request_is_consumed_and_allows_execution(tmp_path: Path, monkeypatch):
    cfg_path = _demo_cfg(tmp_path, require_approval=True)
    runtime = build_live_runtime(cfg_path)
    fake = FakeExecutor()
    monkeypatch.setattr('trading_bot.live.runner._build_executor', lambda raw: fake)

    class FakeStrategy:
        def decide(self, **kwargs):
            return type('D', (), {'intent': TradeIntent.OPEN_SHORT, 'score': -0.8, 'reason': 'forced short', 'stop_atr': 1.0})()

    monkeypatch.setattr('trading_bot.live.runner.TrendSentimentStrategy', lambda *args, **kwargs: FakeStrategy())
    monkeypatch.setattr('trading_bot.live.runner.resolve_session', lambda raw: type('S', (), {'now': datetime(2026, 3, 20), 'active_session': 'us', 'market_open': True, 'reason': 'test', 'watchlist': ['AAA']})())

    first = run_live_cycle(runtime, execute=True)
    approval_id = runtime.state.active_approval_requests()[0]['approval_id']
    decide_operator_request(runtime, approval_id=approval_id, approve=True, operator='alice', note='approved for supervised paper test')
    second = run_live_cycle(runtime, execute=True)

    assert fake.calls
    assert second['executions']
    assert second['approvals_used'][0]['approval_id'] == approval_id
    assert not runtime.state.active_approval_requests()
    assert first['warnings']


def test_monitor_snapshot_reports_alerts_and_approvals(tmp_path: Path):
    cfg_path = _demo_cfg(tmp_path, require_approval=True)
    runtime = build_live_runtime(cfg_path)
    runtime.state.create_operator_alert(category='manual_review', severity='critical', message='AAA requires manual review', symbol='AAA')
    runtime.state.request_operator_approval(action_type='OPEN_SHORT', symbol='AAA', reason='short requires approval', payload={'qty': 4})

    result = monitor_live_state(runtime)
    snap = collect_health_snapshot(cfg_path)

    assert 'Operator Board' in result['operator_board']
    assert snap.active_alert_count >= 1
    assert snap.pending_approval_count == 1
    assert snap.last_monitor_at is not None


def test_alert_can_be_acknowledged_and_resolved(tmp_path: Path):
    cfg_path = _demo_cfg(tmp_path, require_approval=False)
    runtime = build_live_runtime(cfg_path)
    alert = runtime.state.create_operator_alert(category='runtime_warning', severity='warning', message='test alert', symbol='AAA')

    acknowledged = resolve_operator_alert(runtime, alert_id=alert['alert_id'], operator='alice', note='seen', acknowledge_only=True)
    assert acknowledged['status'] == 'acknowledged'
    resolved = resolve_operator_alert(runtime, alert_id=alert['alert_id'], operator='alice', note='fixed', acknowledge_only=False)
    assert resolved['status'] == 'resolved'
