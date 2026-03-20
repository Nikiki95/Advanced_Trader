# Architecture

## Core flow

1. Load historical market data and historical sentiment snapshots.
2. For each trading day, execute pending orders at the next open.
3. Check stop losses against the current bar range.
4. Mark all positions to the close.
5. Generate new close-based decisions for the next session.

This prevents accidental lookahead bias and keeps fills tied to actual positions.

## Key abstractions

- `TradeIntent`: internal trading intention such as `OPEN_LONG` or `CLOSE_SHORT`
- `Broker`: execution interface
- `PortfolioLedger`: source of truth for positions, cash, trades and equity
- `HistoricalSentimentStore`: timestamp-aware sentiment retrieval
- `TrendSentimentStrategy`: explainable strategy layer

## Design choices

### Intent is not broker action
The strategy never emits fake venue actions such as `SHORT` or `COVER`.
It emits **intent**, and the execution layer translates that into the venue-specific buy/sell operation.

### Stops are attached after fills
Stops depend on the real fill price and the actual position size, so they are only created when the order is filled.

### Historical sentiment uses as-of lookup
A backtest must not reuse today's sentiment file for every date in the past. The store only exposes snapshots available at or before the decision timestamp.
