# AI Trading Bot V3.5

This repository is a **V3.5 OpenClaw operations release** built on top of the V3.4 supervised-trading stack.
The main new step is a **real OpenClaw workspace pack** with a structured self-run to-do list, bootstrap notes, startup behavior, and local tool notes so OpenClaw can set up and operate most of the workflow on its own.

## What V3.5 adds

- **OpenClaw workspace pack** under `config/openclaw/workspace/`
- **structured self-run to-do list** for OpenClaw with explicit escalation points
- **bootstrap + boot instructions** so OpenClaw can continue setup across sessions
- **tooling notes** for this Pi + bot + IBKR + OpenClaw environment
- **clear ask-only-when-needed rules** for API keys, channels, symbols, and broker details

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
trading-bot ingest-openclaw --config examples/config/demo.yaml --bundle examples/data/openclaw/sample_bundle.json
trading-bot generate-session-policy-report --config examples/config/demo.yaml --output-dir runtime/openclaw/reports
trading-bot generate-guardrail-report --config examples/config/demo.yaml --output-dir runtime/openclaw/reports
trading-bot export-review-playbooks --config examples/config/demo.yaml --output-dir runtime/openclaw/playbooks
```

For the OpenClaw setup flow, start with:

- `config/openclaw/workspace/AGENTS.md`
- `config/openclaw/workspace/BOOTSTRAP.md`
- `config/openclaw/workspace/OPENCLAW_TODO.md`
- `docs/v3_5_upgrade_notes.md`
