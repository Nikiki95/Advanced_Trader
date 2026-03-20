from datetime import datetime, timezone
from pathlib import Path

from trading_bot.live.state import RuntimeStateStore
from trading_bot.live.status import collect_health_snapshot


def test_workflow_resume_generates_retry_replace_and_queue(tmp_path: Path):
    store = RuntimeStateStore(tmp_path / 'state.json')
    store.register_stop_resize_workflow(
        symbol='AAA',
        order_ids=['old-stop'],
        replacement_order_id='new-stop',
        desired_qty=9,
        desired_stop_price=95.0,
        position_side='LONG',
    )
    workflow = store.state['order_workflows'][0]
    workflow['state'] = 'AWAITING_REPLACE_CONFIRM'
    workflow['updated_at'] = datetime(2026, 3, 20, 8, 0, tzinfo=timezone.utc).isoformat()
    review = store.plan_working_order_resume(
        workflow_timeout_minutes=1,
        replace_timeout_policy='retry_replace',
        max_resume_attempts=2,
    )
    actions = [row['action_type'] for row in review['actions']]
    assert 'RETRY_REPLACE_STOP' in actions
    assert len(store.active_pending_replace_queue()) == 1


def test_workflow_resume_generates_retry_cancel_for_timeout(tmp_path: Path):
    store = RuntimeStateStore(tmp_path / 'state.json')
    store.state['stop_orders'] = [
        {
            'order_id': 'legacy-stop',
            'symbol': 'AAA',
            'qty': 5,
            'remaining_qty': 5,
            'status': 'Submitted',
            'side': 'SELL',
            'order_type': 'STP',
            'stop_price': 95.0,
        }
    ]
    store.register_cancel_workflow(symbol='AAA', order_ids=['legacy-stop'])
    workflow = store.state['order_workflows'][0]
    workflow['updated_at'] = datetime(2026, 3, 20, 8, 0, tzinfo=timezone.utc).isoformat()
    review = store.plan_working_order_resume(
        workflow_timeout_minutes=1,
        cancel_timeout_policy='retry_cancel',
        max_resume_attempts=2,
    )
    assert any(row['action_type'] == 'CANCEL_ORDER_IDS' for row in review['actions'])
    assert store.state['broker_timeouts']


def test_health_snapshot_reports_pending_replace_queue(tmp_path: Path):
    cfg = tmp_path / 'cfg.yaml'
    cfg.write_text(
        'universe:\n  symbols: [AAA]\n'
        'market_data:\n  source: csv\n  csv_dir: ../data/prices\n'
        'sentiment:\n  path: sentiment.csv\n  current_json_path: current.json\n'
        'compatibility:\n  timezone: Europe/Berlin\n  sessions:\n    us:\n      start_cet: "14:00"\n      end_cet: "21:30"\n      watchlist: [AAA]\n'
        'live:\n  state_path: runtime/live_state.json\n',
        encoding='utf-8',
    )
    store = RuntimeStateStore(tmp_path / 'runtime' / 'live_state.json')
    store.queue_pending_replace(
        workflow_id='wf-1',
        symbol='AAA',
        desired_qty=3,
        desired_stop_price=9.5,
        position_side='LONG',
    )
    store.note_broker_timeout(workflow_id='wf-1', symbol='AAA', category='stop_resize_replace', policy='retry_replace', note='timeout test')
    snap = collect_health_snapshot(cfg)
    assert snap.pending_replace_queue_count == 1
    assert snap.broker_timeout_count == 1
