# V3.1 OpenClaw Operations Design

V3.1 tightens the **Research + Operator bridge** for OpenClaw while keeping broker execution inside the trading bot.

## Functional split

- **OpenClaw**
  - collects news
  - rates article relevance per ticker
  - provides sentiment / confidence / event risk / action bias / thesis
  - exports pending approvals and alerts for an operator workflow
  - runs Cron / Heartbeat around the bot
- **Trading bot**
  - reads normalized sentiment snapshots
  - attenuates or blocks entries when event risk or contradiction is high
  - applies strategy, risk checks and execution gating
  - owns the live broker adapter, stops, recovery and reconciliation

## Core data flow

1. OpenClaw job writes a JSON or JSONL bundle with article-level research.
2. `ingest-openclaw` converts it into:
   - raw archive copy
   - normalized snapshot contract
   - updated `current_sentiment.json`
   - appended historical sentiment CSV
3. pre-market / intraday decision jobs run the bot with the latest snapshot.
4. `export-operator-queue` writes pending approvals and alerts plus review-ready markdown templates.
5. operator decisions written back as JSON are consumed by `import-operator-decisions`.

## Security boundary

OpenClaw is intentionally kept away from direct broker execution. The bridge is file-based and approval-based.
