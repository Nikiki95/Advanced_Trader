from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from trading_bot.live.execution import BrokerOrderSnapshot, BrokerSyncSnapshot
from trading_bot.live.state import RuntimeStateStore
from trading_bot.types import PositionSide


def test_stop_resize_workflow_confirms_after_sync(tmp_path: Path):
    store = RuntimeStateStore(tmp_path / "state.json")
    store.register_stop_resize_workflow(
        symbol="AAA",
        order_ids=["old-stop"],
        replacement_order_id="new-stop",
        desired_qty=9,
        desired_stop_price=95.0,
        position_side="LONG",
    )
    store.state["stop_orders"] = [
        {
            "order_id": "new-stop",
            "symbol": "AAA",
            "qty": 9,
            "remaining_qty": 9,
            "status": "Submitted",
            "side": "SELL",
            "order_type": "STP",
            "stop_price": 95.0,
        }
    ]
    store.confirm_order_workflows()
    active = store.active_order_workflows()
    assert not active
    assert store.state["order_workflows"][0]["state"] == "PROTECTED"


def test_reconciliation_prefers_resize_stop_when_stop_exists_with_drift(tmp_path: Path):
    store = RuntimeStateStore(tmp_path / "state.json")
    store.upsert_position(
        symbol="AAA",
        side=PositionSide.LONG,
        qty=7,
        entry_price=100.0,
        entry_time=datetime(2026, 3, 20, tzinfo=timezone.utc),
        stop_price=96.0,
        last_price=100.0,
    )
    store.state["stop_orders"] = [
        {
            "order_id": "stop-1",
            "symbol": "AAA",
            "qty": 5,
            "remaining_qty": 5,
            "status": "Submitted",
            "side": "SELL",
            "order_type": "STP",
            "stop_price": 95.0,
        }
    ]
    plan = store.plan_reconciliation()
    resize = [a for a in plan["actions"] if a["action_type"] == "RESIZE_STOP"]
    assert resize
    assert resize[0]["existing_order_ids"] == ["stop-1"]


def test_audit_db_receives_run_event(tmp_path: Path):
    audit_path = tmp_path / "audit.db"
    store = RuntimeStateStore(tmp_path / "state.json", audit_path=audit_path)
    store.record_run([], [], {"session": "us"}, [], reconciliation={})
    conn = sqlite3.connect(str(audit_path))
    try:
        row = conn.execute("SELECT COUNT(*) FROM audit_events").fetchone()
        assert row[0] >= 1
    finally:
        conn.close()
