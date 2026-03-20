# V2.2 upgrade notes

V2.2 focuses on live-trading resilience rather than changing the strategy itself.

## Main additions

- partial-fill aware runtime position management
- broker account summary persisted into runtime state
- protective stop reconciliation over multiple cycles
- persistent retry queue for broker repair work
- manual CLI commands for reconciliation and retry processing

## Why this matters

The original project and the earlier V2 / V2.1 line could lose track of the true live state whenever:

- an order only partially filled
- a stop quantity drifted away from the live position quantity
- stops were cancelled during an exit but the exit did not fully fill
- broker connectivity failed mid-repair

V2.2 keeps those mismatches visible and recoverable instead of silently assuming everything completed perfectly.
