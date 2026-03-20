# OPENCLAW_TODO.md

Use this file as the **primary execution checklist** for the OpenClaw side of the trading setup.
Move from top to bottom. If an item is already complete, mark it complete and continue.
Ask the user only when the step says **ASK USER** or when the item is truly blocked.

---

## Phase 0 — Ground rules

- [ ] Read `AGENTS.md`, `TOOLS.md`, `USER.md`, and `HEARTBEAT.md`.
- [ ] Confirm the active repo path on the Pi.
- [ ] Confirm the active bot config path (preferred target: `config/bot/paper.pi.yaml`).
- [ ] Confirm OpenClaw workspace path and that these workspace files are being injected.

### Blocking questions for this phase

Ask only if missing:
- **ASK USER:** What exact repo path should be treated as canonical on the Pi?
- **ASK USER:** Which bot config file should be treated as the live paper-trading config?

---

## Phase 1 — OpenClaw runtime readiness

- [ ] Check `openclaw gateway status`.
- [ ] Check `openclaw cron status`.
- [ ] Check `openclaw system heartbeat last`.
- [ ] Verify the Gateway config path in use.
- [ ] Verify the workspace directory is writable.
- [ ] Verify a messaging surface is configured for alerts/approvals.

### Blocking questions for this phase

Ask only if missing:
- **ASK USER:** Which messaging target should receive alerts and approvals?
- **ASK USER:** Which model provider/auth profile should OpenClaw use?
- **ASK USER:** If the configured provider requires it, please supply or configure the API key/auth profile.

---

## Phase 2 — Trading-bot runtime readiness

- [ ] Verify Python environment / venv exists.
- [ ] Run `trading-bot health --config <config>`.
- [ ] Run `trading-bot monitor-live --config <config>`.
- [ ] Verify runtime directories exist:
  - `runtime/openclaw/inbox`
  - `runtime/openclaw/operator_queue`
  - `runtime/openclaw/reports`
  - `runtime/openclaw/playbooks`
  - `runtime/openclaw/handoff`
  - `runtime/logs`
- [ ] Verify the bot can read/write these runtime paths.

### Blocking questions for this phase

Ask only if missing:
- **ASK USER:** Should missing runtime directories be created automatically?

---

## Phase 3 — Symbol / relevance setup

- [ ] Inspect the watchlist in the active bot config.
- [ ] Inspect the alias map file.
- [ ] Check that every symbol has at least one company-name alias for news relevance.
- [ ] Check for obviously broken or stale aliases.
- [ ] Prepare a suggested alias update if gaps are found.

### Blocking questions for this phase

Ask only if missing:
- **ASK USER:** Please confirm the final watchlist symbols.
- **ASK USER:** Please confirm or provide missing company-name aliases for any uncovered symbols.

---

## Phase 4 — IBKR paper connectivity

- [ ] Inspect the bot config for IBKR host / port / client ID.
- [ ] Verify it points to the intended paper endpoint.
- [ ] Run `trading-bot sync-state --config <config>`.
- [ ] Run `trading-bot reconcile-live --config <config>`.
- [ ] Run `trading-bot recover-live --config <config>`.
- [ ] Record whether connectivity succeeded, degraded, or failed.

### Blocking questions for this phase

Ask only if missing:
- **ASK USER:** Please confirm IBKR host, port, and client ID for paper trading.
- **ASK USER:** If sync fails, is TWS/Gateway currently running on the Pi?

---

## Phase 5 — OpenClaw ingest path

- [ ] Check whether a bundle exists in `runtime/openclaw/inbox/latest_bundle.json`.
- [ ] If a bundle exists, run `trading-bot ingest-openclaw --config <config> --bundle <bundle>`.
- [ ] If no bundle exists, use the sample bundle to verify the path end to end.
- [ ] Verify that the latest sentiment snapshot/current sentiment file updates.
- [ ] Generate at least one report after ingest:
  - session policy report
  - guardrail report
  - portfolio regime report

### Blocking questions for this phase

Ask only if missing:
- **ASK USER:** Should I use the sample OpenClaw bundle for a first pipeline test, or do you already have a real incoming bundle source?

---

## Phase 6 — Operator workflow

- [ ] Run `trading-bot export-operator-queue --config <config> --output-dir runtime/openclaw/operator_queue`.
- [ ] Verify approvals and alerts export correctly.
- [ ] Run playbook and handoff exports.
- [ ] Verify the output location the operator will actually review.
- [ ] If operator-decision files already exist, import them and confirm the flow.

### Blocking questions for this phase

Ask only if missing:
- **ASK USER:** Where should operator review happen — local files only, or a specific chat/channel target too?

---

## Phase 7 — Scheduling

- [ ] Verify the intended scheduling owner:
  - Linux cron on Pi
  - OpenClaw cron
  - hybrid
- [ ] If OpenClaw cron is chosen, add or review jobs for:
  - overnight sentiment build
  - pre-market decision
  - intraday sentiment refresh
  - intraday decision check
  - end-of-day reconcile/report
- [ ] Verify heartbeat is scoped to monitoring only.
- [ ] Confirm there is no path that lets OpenClaw place broker orders directly.

### Blocking questions for this phase

Ask only if missing:
- **ASK USER:** Should scheduling be managed by Linux cron, OpenClaw cron, or both?
- **ASK USER:** Which timezone should the operational schedule use if not Europe/Berlin / America/New_York split?

---

## Phase 8 — Final supervised-paper readiness review

- [ ] Summarize configured provider/auth method.
- [ ] Summarize messaging target.
- [ ] Summarize watchlist + alias coverage.
- [ ] Summarize IBKR paper connectivity state.
- [ ] Summarize whether ingest, reports, approvals, and heartbeat are all functioning.
- [ ] List any blockers that still require user input.
- [ ] Explicitly confirm that real execution is still disabled unless the user says otherwise.

### Final rule

If all phases are green except optional enhancements, propose the next smallest safe step.
Do **not** switch to real execution on your own.
