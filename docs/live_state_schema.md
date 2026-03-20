# Runtime state schema (V2.5)

The default runtime state file is `runtime/live_state.json`.

It stores:

- `positions`: symbol-keyed open positions
- `orders`: broker-known non-stop orders
- `pending_orders`: still-working orders with remaining quantity
- `stop_orders`: protective stop orders
- `fills`: recent execution reports
- `retry_queue`: deferred reconciliation actions that failed against the broker
- `last_reconciliation`: the latest stop / orphan-order repair plan
- `reconciliation_history`: recent reconciliation snapshots
- `account_snapshot`: broker-side equity, cash and PnL summary when available
- `last_decisions`: last strategy decisions
- `run_history`: recent live-cycle summaries
- `cash_estimate`: local working estimate used when no broker account snapshot is available
- `last_sync_at`: last successful IBKR reconciliation timestamp

The execution journal is written separately as JSONL so each run, sync and execution can be inspected line by line.


## V2.5 additions

The runtime state now also persists:

- `order_history`: append-only lifecycle snapshots for working and recovered orders
- `fill_history`: broker and local fills used during restart recovery
- `bracket_groups`: parent/child order groupings for protective stops
- `last_recovery` and `recovery_history`: summaries of restart-aware lifecycle repair
