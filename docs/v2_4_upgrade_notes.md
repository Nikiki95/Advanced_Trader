# V2.5 upgrade notes

V2.5 tightens live-trading operations with four practical changes:

1. **Fill cursor + lookback filtering**
   - sync ingests only fills newer than the last seen timestamp (plus a configurable lookback window)
   - reduces duplicates and enables restart recovery without scanning unbounded history

2. **Order lifecycle state machine**
   - each order gets a derived lifecycle state (`WORKING`, `PARTIALLY_FILLED`, `FILLED`, `CANCELLED`, `UNKNOWN`)
   - transitions are stored in `order_lifecycle` and reflected in `order_history` rows

3. **More precise parent/child cancel actions**
   - orphan stop orders prefer `CANCEL_ORDER_IDS` (scoped) instead of cancelling all stops for the symbol

4. **Optional SQLite runtime state**
   - if `live.state_path` ends with `.db`, the runtime state is stored in SQLite instead of a JSON file
   - journal paths ending in `.db` are also stored as a table of events

## Config additions

```yaml
live:
  fills_lookback_minutes: 1440
  state_path: ../runtime/live_state.json   # or ../runtime/live_state.db
  execution_journal_path: ../runtime/execution_journal.jsonl   # or ../runtime/runtime_events.db
```
