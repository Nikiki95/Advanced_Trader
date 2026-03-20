# TOOLS.md

## Local notes for this setup

- Repo root on the Pi is expected to look like `~/trading/ai-trading-bot-v3.5`.
- OpenClaw and the trading bot run on the same Raspberry Pi.
- IBKR TWS / Gateway is expected to be reachable on localhost unless the user says otherwise.
- Prefer paper-trading settings unless the user explicitly authorizes real execution.

## Safe assumptions

- Use relative repo paths where possible.
- Prefer read-only inspection before modifying config.
- Prefer bot CLI commands over ad-hoc file edits when both exist.

## Commands you may use for setup and checks

- `openclaw gateway status`
- `openclaw cron status`
- `openclaw cron list`
- `openclaw cron runs --id <jobId> --limit 20`
- `openclaw system heartbeat last`
- `trading-bot health --config <config>`
- `trading-bot monitor-live --config <config>`
- `trading-bot ingest-openclaw --config <config> --bundle <bundle>`
- `trading-bot export-operator-queue --config <config> --output-dir <dir>`
- `trading-bot import-operator-decisions --config <config> --input-dir <dir>`
- `trading-bot generate-session-policy-report --config <config> --output-dir <dir>`
- `trading-bot generate-guardrail-report --config <config> --output-dir <dir>`
- `trading-bot generate-portfolio-regime-report --config <config> --output-dir <dir>`
- `trading-bot export-review-playbooks --config <config> --output-dir <dir>`
- `trading-bot generate-shift-handoff --config <config> --output-dir <dir>`

## Ask the user before

- enabling `--execute`
- changing IBKR host / port / client ID
- exposing the Gateway beyond the trusted local network / tailnet
- choosing or rotating provider secrets
- adding or removing watchlist symbols
