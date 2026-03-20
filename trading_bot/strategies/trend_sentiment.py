from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import pandas as pd

from trading_bot.config import StrategyConfig
from trading_bot.data.sentiment import HistoricalSentimentStore
from trading_bot.signals.composite import CompositeSignalEngine
from trading_bot.signals.technicals import latest_feature_block
from trading_bot.strategies.base import Strategy
from trading_bot.types import OrderIntent, Position, PositionSide, TradeIntent


@dataclass(slots=True)
class TrendSentimentStrategy(Strategy):
    config: StrategyConfig
    sentiment_store: HistoricalSentimentStore | None = None

    def __post_init__(self) -> None:
        self.engine = CompositeSignalEngine(self.config)

    def decide(
        self,
        *,
        symbol: str,
        history: pd.DataFrame,
        timestamp: datetime,
        position: Position | None,
    ) -> OrderIntent:
        sentiment = self.sentiment_store.get_latest_asof(symbol, timestamp) if self.sentiment_store else None
        signal = self.engine.score(symbol, history, timestamp, sentiment)
        feats = latest_feature_block(history)
        stop_atr = max(float(feats["atr"]), 0.01)

        if position is None and sentiment is not None:
            if sentiment.relevance_score < 0.45:
                return OrderIntent(symbol, timestamp, TradeIntent.HOLD, signal.final_score, 'blocked by low-relevance openclaw research', stop_atr)
            if sentiment.event_risk_score >= 0.85 and sentiment.headline_risk == 'high':
                return OrderIntent(symbol, timestamp, TradeIntent.HOLD, signal.final_score, 'blocked by high-risk event regime', stop_atr)
            if sentiment.contradiction_score >= 0.7:
                return OrderIntent(symbol, timestamp, TradeIntent.HOLD, signal.final_score, 'blocked by contradictory openclaw research', stop_atr)
            if getattr(sentiment, 'event_regime', 'normal') in {'binary_event_lockdown', 'contradictory_tape'}:
                return OrderIntent(symbol, timestamp, TradeIntent.HOLD, signal.final_score, f"blocked by openclaw regime {getattr(sentiment, 'event_regime', 'normal')}", stop_atr)
            if getattr(sentiment, 'approval_policy', 'auto') == 'block_new_entries':
                return OrderIntent(symbol, timestamp, TradeIntent.HOLD, signal.final_score, 'blocked by openclaw approval policy', stop_atr)

        if position is None:
            if signal.final_score >= self.config.long_entry_threshold:
                return OrderIntent(symbol, timestamp, TradeIntent.OPEN_LONG, signal.final_score, 'long entry threshold met', stop_atr)
            if signal.final_score <= self.config.short_entry_threshold:
                return OrderIntent(symbol, timestamp, TradeIntent.OPEN_SHORT, signal.final_score, 'short entry threshold met', stop_atr)
            return OrderIntent(symbol, timestamp, TradeIntent.HOLD, signal.final_score, 'no entry', stop_atr)

        if position.side == PositionSide.LONG and signal.final_score <= self.config.long_exit_threshold:
            return OrderIntent(symbol, timestamp, TradeIntent.CLOSE_LONG, signal.final_score, 'long exit threshold met', stop_atr)
        if position.side == PositionSide.SHORT and signal.final_score >= self.config.short_exit_threshold:
            return OrderIntent(symbol, timestamp, TradeIntent.CLOSE_SHORT, signal.final_score, 'short exit threshold met', stop_atr)
        return OrderIntent(symbol, timestamp, TradeIntent.HOLD, signal.final_score, 'hold existing position', stop_atr)
