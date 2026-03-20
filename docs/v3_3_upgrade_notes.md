# V3.3 upgrade notes

V3.3 expands the OpenClaw bridge from "daily report + queue export" into a more operator-friendly workflow layer.

## New functional additions

- **Portfolio regime report**
  - aggregates symbol-level event regimes, approval policies and priorities
  - highlights portfolio-wide operator focus points
- **Symbol review playbooks**
  - one markdown + JSON playbook per elevated / blocked / operator-relevant symbol
  - includes current OpenClaw view, alerts, approvals and recommended operator actions
- **Shift handoff packet**
  - summarizes blocked symbols, critical symbols, pending approvals and active alerts
  - designed for human handoff between sessions or operating windows

## New CLI commands

```bash
trading-bot generate-portfolio-regime-report --config examples/config/demo.yaml --output-dir runtime/openclaw/reports
trading-bot export-review-playbooks --config examples/config/demo.yaml --output-dir runtime/openclaw/playbooks
trading-bot generate-shift-handoff --config examples/config/demo.yaml --output-dir runtime/openclaw/handoff
```
