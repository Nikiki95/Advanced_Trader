# V2.6 Upgrade Notes

V2.6 focuses on multi-cycle live execution hardening.

## New capabilities

- explicit persisted `order_workflows` for broker-side operational tasks
- `RESIZE_STOP` reconciliation action
- cancel-confirm and replace-confirm tracking across sync cycles
- optional SQLite audit sink via `live.audit_path`

## Runtime behavior

When reconciliation detects an existing stop with drifted quantity, side or stop price, V2.6 now creates a `RESIZE_STOP` action instead of treating everything as a fresh `ENSURE_STOP`.

Applied broker actions register an order workflow:

- `cancel_confirm`: waits until broker sync no longer reports the targeted order ids
- `stop_resize`: waits for old stop ids to disappear and for a matching replacement protective stop to be visible

## New config

```yaml
live:
  audit_path: ../runtime/audit.db
```

If `audit_path` ends in `.db`, audit events are written to SQLite table `audit_events`.
