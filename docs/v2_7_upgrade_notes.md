# V2.7 Upgrade Notes

V2.7 focuses on workflow-level resume and broker-timeout handling.

## What changed

- Timed-out cancel workflows can now generate retry actions according to policy.
- Timed-out replace workflows can enqueue a pending replacement stop and retry it later.
- Health output now shows pending replace queue size and broker timeout events.
- Live runtime can apply workflow-resume actions on startup instead of only reviewing raw pending orders.

## New live config knobs

```yaml
live:
  workflow_timeout_minutes: 20
  cancel_timeout_policy: retry_cancel
  replace_timeout_policy: retry_replace
  max_workflow_resume_attempts: 3
  resume_workflows_on_start: true
```
