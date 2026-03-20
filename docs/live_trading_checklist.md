# Live Trading Checklist

Before connecting this repo to a real broker, add or verify the following:

- broker adapter with idempotent order handling
- fill and partial-fill reconciliation
- cancel/replace logic
- market calendar support with holidays and half-days
- retry and timeout handling for market data and broker APIs
- structured audit logging
- secrets handling via environment variables or vault
- circuit breakers for daily loss, stale prices and missing data
- deployment pipeline with commit hash logging
- paper-trading burn-in period before any live rollout

This repository is intentionally conservative and keeps the default execution mode in paper/backtest territory.
