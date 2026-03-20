# BOOTSTRAP.md

You are being initialized for the **AI Trading Bot V3.5** on a Raspberry Pi.
Your goal is to complete as much setup as possible without unnecessary questions.

## Rules

- Ask the user only when a missing value is truly blocking.
- Ask for **one blocking item at a time**.
- If a step is already complete, mark it complete and move on.
- Keep all setup notes inside this workspace.

## First questions only if missing

Check `USER.md`, `TOOLS.md`, and `OPENCLAW_TODO.md` first. Ask the user only if one of these is still unknown:

1. Which model provider/auth profile should OpenClaw use?
2. Which messaging surface should receive alerts and approvals?
3. Which watchlist symbols should the bot operate on?
4. Confirm IBKR paper host/port/client ID.

## After first-run

When the workspace is ready enough for normal operation, leave `BOOTSTRAP.md` in place only if there are still onboarding blockers.
Otherwise, the agent may archive or delete it according to the user's preference.
