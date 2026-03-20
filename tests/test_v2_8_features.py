from datetime import datetime, timezone
from pathlib import Path

from trading_bot.live.state import RuntimeStateStore
from trading_bot.live.status import collect_health_snapshot


def test_workflow_resume_timeout_escalates_to_manual_review(tmp_path: Path):
    store = RuntimeStateStore(tmp_path / 'state.json')
    store.register_stop_resize_workflow(
        symbol='AAA',
        order_ids=['old-stop'],
        replacement_order_id='new-stop',
        desired_qty=10,
        desired_stop_price=95.0,
        position_side='LONG',
    )
    workflow = store.state['order_workflows'][0]
    workflow['state'] = 'AWAITING_REPLACE_CONFIRM'
    workflow['resume_count'] = 2
    workflow['updated_at'] = datetime(2026, 3, 20, 8, 0, tzinfo=timezone.utc).isoformat()
    review = store.plan_working_order_resume(workflow_timeout_minutes=1, max_resume_attempts=2)
    assert any(row['action_type'] == 'MARK_WORKFLOW_MANUAL_REVIEW' for row in review['actions'])


def test_workflow_resume_action_is_persisted(tmp_path: Path):
    store = RuntimeStateStore(tmp_path / 'state.json')
    store.register_cancel_workflow(symbol='AAA', order_ids=['stop-1'])
    workflow = store.state['order_workflows'][0]
    workflow['updated_at'] = datetime(2026, 3, 20, 8, 0, tzinfo=timezone.utc).isoformat()
    review = store.plan_working_order_resume(workflow_timeout_minutes=1, cancel_timeout_policy='retry_cancel', max_resume_attempts=3)
    assert any(row['action_type'] == 'CANCEL_ORDER_IDS' for row in review['actions'])
    assert store.active_workflow_resume_queue()


def test_health_snapshot_reports_workflow_escalations(tmp_path: Path):
    cfg = tmp_path / 'cfg.yaml'
    cfg.write_text(
        """
universe:
  symbols: [AAA]
market_data:
  source: csv
  csv_dir: ../data/prices
sentiment:
  path: sentiment.csv
  current_json_path: current.json
compatibility:
  timezone: Europe/Berlin
  sessions:
    us:
      start_cet: "14:00"
      end_cet: "21:30"
      watchlist: [AAA]
live:
  state_path: runtime/live_state.json
""".strip() + "\n",
        encoding='utf-8',
    )
    store = RuntimeStateStore(tmp_path / 'runtime' / 'live_state.json')
    wf = store.register_cancel_workflow(symbol='AAA', order_ids=['stop-1'])
    store.mark_workflow_manual_review(str(wf['workflow_id']), note='needs operator review')
    snap = collect_health_snapshot(cfg)
    assert snap.manual_review_workflow_count == 1
    assert snap.workflow_escalation_count == 1
