# Live execution notes (V2.5)

V2.5 hardens the live path in four practical ways:

1. **Partial-fill aware state updates**
   - open and close fills now update runtime positions incrementally
   - a partially closed position stays open locally with the remaining quantity

2. **Protective stop reconciliation across cycles**
   - runtime state plans reconciliation actions from broker-synced positions, stops and pending orders
   - a mismatch between live position quantity and stop quantity triggers an `ENSURE_STOP` action
   - orphan stop orders trigger a cancel action

3. **Retry queue for broker-side repair work**
   - reconciliation failures are stored in a persistent retry queue
   - `trading-bot process-retries --execute` can replay them safely

4. **Account and PnL sync**
   - broker sync now stores net liquidation, available funds and realized / unrealized PnL when available
   - sizing and health output can use those values instead of stale local estimates

## New operational commands

```bash
trading-bot sync-state --config examples/config/demo.yaml
trading-bot reconcile-live --config examples/config/demo.yaml
trading-bot reconcile-live --config examples/config/demo.yaml --execute
trading-bot process-retries --config examples/config/demo.yaml
trading-bot process-retries --config examples/config/demo.yaml --execute
```

## Current live sequence

For an entry:

- sync broker state on startup when enabled
- compute decision and target stop
- submit market order
- persist the execution even if only part of the quantity filled
- place an initial stop for the filled quantity
- run reconciliation so later fills can resize the protective stop

For an exit:

- read the current quantity from persisted runtime state
- cancel symbol stop orders first when possible
- submit the closing market order
- if the exit only partially fills, keep the remaining position in runtime state
- next reconciliation cycle restores the correct protective stop size


## V2.5 operational addition

Use `recover-live` after a restart or reconnect to rebuild pending-order and bracket state from the latest broker snapshot before placing new trades.
