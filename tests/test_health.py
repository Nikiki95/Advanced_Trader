from pathlib import Path

from trading_bot.live.status import collect_health_snapshot
from trading_bot.live.state import RuntimeStateStore


def test_health_snapshot_includes_runtime_state_counts(tmp_path: Path):
    cfg = tmp_path / 'cfg.yaml'
    cfg.write_text(
        'universe:\n  symbols: [AAA]\n'
        'market_data:\n  source: csv\n  csv_dir: ../data/prices\n'
        'sentiment:\n  path: sentiment.csv\n  current_json_path: current.json\n'
        'compatibility:\n  timezone: Europe/Berlin\n  sessions:\n    us:\n      start_cet: "14:00"\n      end_cet: "21:30"\n      watchlist: [AAA]\n'
        'live:\n  state_path: runtime/live_state.json\n',
        encoding='utf-8'
    )
    store = RuntimeStateStore(tmp_path / 'runtime' / 'live_state.json')
    store.upsert_position(symbol='AAA', side='LONG', qty=2, entry_price=10.0, entry_time=__import__('datetime').datetime(2026, 3, 20), stop_price=9.0)
    store.enqueue_retry_action({'action_type': 'ENSURE_STOP', 'symbol': 'AAA', 'position_side': 'LONG', 'qty': 2, 'stop_price': 9.0}, reason='test')
    store.state['account_snapshot'] = {'net_liquidation': 123.0, 'available_funds': 45.0, 'unrealized_pnl': 1.5, 'realized_pnl': -0.5}
    store.save()
    snap = collect_health_snapshot(cfg)
    assert snap.position_count == 1
    assert snap.retry_queue_count == 1
    assert snap.net_liquidation == 123.0
    assert snap.state_path.endswith('runtime/live_state.json')
