# V2.5 upgrade notes

V2.5 extends the live stack with restart-aware order lifecycle handling.

## New in V2.5

- runtime `fill_history`
- runtime `order_history`
- runtime `bracket_groups`
- `recover-live` CLI command
- fill-based pending-order recovery after broker sync
- bracket-status review (`protected`, `degraded`, `closed`)

## Why this matters

The V2.5 state model knew about current positions, open orders and stop orders, but it still had limited visibility into what happened **between** runs. If the process restarted while orders were working, local state could lag behind broker reality. V2.5 reduces that gap by using broker fills plus persisted lifecycle metadata.

## Operational recommendation

Use the sequence below after any restart or IBKR reconnect:

```bash
trading-bot recover-live --config examples/config/demo.yaml
trading-bot reconcile-live --config examples/config/demo.yaml
trading-bot health --config examples/config/demo.yaml
```

Start with dry runs first. Only add `--execute` once the recovery output matches your broker state.
