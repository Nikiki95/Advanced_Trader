# V3.4 upgrade notes

## Functional additions

- Session-aware OpenClaw policies per symbol (`block`, `review`, `normal`)
- Operator decision tiers (`routine`, `elevated`, `critical`, `blocked`)
- Portfolio-wide guardrails that can escalate to operator-only mode
- New reports:
  - session policy report
  - portfolio guardrail report
- Operator approvals now carry decision-tier, session-policy and guardrail context
- Health / monitoring now surface guardrail severity and directive counts

## New CLI commands

- `trading-bot generate-session-policy-report --config ... --output-dir ...`
- `trading-bot generate-guardrail-report --config ... --output-dir ...`

## Intended use

V3.4 does not give OpenClaw broker control. It makes OpenClaw better at:

- defining when fresh entries should slow down
- surfacing when operator review should be stricter
- turning portfolio context into actionable guardrails for supervised trading
