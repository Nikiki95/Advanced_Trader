# V2.5 Upgrade Notes

V2.5 hardens the live runtime around restart-resume and broker-order auditing.

## What changed

- Added `working_order_workflows` in runtime state
- Added `resume-live` CLI command
- Added stronger `fill_cursor` with execution-id tracking
- Added `fill_sync_windows` audit trail
- Broker order snapshots now preserve `perm_id`, `oca_group`, `transmit` and derived `child_order_ids`
- Bracket groups retain live child-order visibility from broker sync

## Why it matters

These additions reduce ambiguity after restarts and make it easier to review stale working orders, partially filled entries that still need protection, and parent/child drift in live order trees.
