# V3.2 upgrade notes

V3.2 tightens the OpenClaw bridge around three functional areas:

- event regime classification per symbol
- approval policies derived from OpenClaw research
- operator daily reports with prioritized symbols

## New functional pieces

- `event_regime` and `approval_policy` are now written into OpenClaw snapshot contracts
- strategy logic blocks fresh entries for lockdown / contradictory regimes
- live approval gating can escalate based on OpenClaw policy, not only static config
- `generate-ops-report` creates markdown + JSON daily operator reports

## New commands

```bash
trading-bot generate-ops-report --config examples/config/demo.yaml --output-dir examples/runtime/openclaw/reports
```
