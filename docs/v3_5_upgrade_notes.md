# V3.5 Upgrade Notes

V3.5 is an **OpenClaw workspace + operations checklist release**.
It does not move OpenClaw closer to broker execution. Instead, it makes the OpenClaw side more usable as a semi-autonomous research and operations assistant.

## What V3.5 adds

- a real `config/openclaw/workspace/` pack
- `AGENTS.md` for this bot workspace
- `BOOTSTRAP.md` for first-run onboarding
- `BOOT.md` for startup continuation
- `TOOLS.md` with local Pi / bot / IBKR notes
- `OPENCLAW_TODO.md` as the main structured execution checklist
- `OPENCLAW_STATUS.md` as a simple progress log
- synced `HEARTBEAT.md` content between repo config and workspace

## Intended use

1. Point OpenClaw at a workspace directory.
2. Copy or link the files from `config/openclaw/workspace/` into that workspace.
3. Let OpenClaw work through `OPENCLAW_TODO.md`.
4. It should ask the user only when API keys, messaging targets, watchlist symbols, aliases, or IBKR connection details are missing.
5. Otherwise, it should continue setup and operations work autonomously.

## Scope boundary

OpenClaw remains:
- research / sentiment / relevance / event-regime support
- approvals / alerts / reports / operator support
- cron / heartbeat / scheduling assistant

OpenClaw still does **not** directly own:
- broker execution
- live broker-state mutation
- autonomous approval of risky trades
