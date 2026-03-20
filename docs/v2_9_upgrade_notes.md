# V2.9 upgrade notes

V2.9 shifts the project from mostly internal live-hardening to **operator-facing supervised trading support**.

## Functional additions

- active operator alerts for warnings, manual-review workflows and pending approvals
- approval requests for configured live actions before orders are sent
- operator monitoring board (`monitor-live`)
- approve/reject flow for pending requests (`decide-approval`)
- acknowledge/resolve flow for alerts (`resolve-alert`)

## Typical supervised workflow

1. Run `trading-bot monitor-live --config ...`
2. Review active alerts and pending approvals
3. Approve or reject the relevant request
4. Re-run `trading-bot run-live --config ... --execute`
5. Resolve alerts once the situation is handled

## Example config

```yaml
live:
  require_operator_approval: true
  approval_intents: [OPEN_SHORT]
  approval_notional_threshold: 5000
  approval_ttl_minutes: 120
  block_when_manual_review_active: true
```
