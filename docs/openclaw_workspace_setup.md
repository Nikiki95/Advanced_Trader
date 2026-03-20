# OpenClaw Workspace Setup for V3.5

This release adds a workspace-ready OpenClaw packet under `config/openclaw/workspace/`.

## Copy into the real workspace

Typical default workspace from OpenClaw docs is `~/.openclaw/workspace`.

Copy these files into the real workspace:

- `AGENTS.md`
- `BOOTSTRAP.md`
- `BOOT.md`
- `TOOLS.md`
- `USER.md`
- `HEARTBEAT.md`
- `OPENCLAW_TODO.md`
- `OPENCLAW_STATUS.md`

## Recommended first turn to OpenClaw

Tell OpenClaw:

> Use the workspace checklist in OPENCLAW_TODO.md. Only ask me when a listed blocker is missing. Otherwise continue autonomously and update OPENCLAW_STATUS.md.

## Good first validations

- `openclaw gateway status`
- `openclaw cron status`
- `openclaw system heartbeat last`
- `trading-bot health --config config/bot/paper.pi.yaml`
- `trading-bot monitor-live --config config/bot/paper.pi.yaml`
