from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pandas as pd

from trading_bot.data.sentiment import HistoricalSentimentStore
from trading_bot.strategies.trend_sentiment import TrendSentimentStrategy
from trading_bot.config import StrategyConfig
from trading_bot.types import TradeIntent



def _history_df() -> pd.DataFrame:
    dates = pd.date_range('2025-01-01', periods=80, freq='D')
    close = pd.Series(range(100, 180)) * 1.0
    return pd.DataFrame({
        'Date': dates,
        'Open': close - 1,
        'High': close + 1,
        'Low': close - 2,
        'Close': close,
        'Volume': 1000,
    })



def test_strategy_blocks_high_risk_event_open(tmp_path: Path):
    csv_path = tmp_path / 'sentiment.csv'
    csv_path.write_text(
        'timestamp,symbol,score,confidence,source,summary,relevance_score,event_risk_score,contradiction_score,headline_risk,action_bias,source_count,thesis,event_flags\n'
        '2026-03-20T07:15:00Z,AAA,0.9,0.95,openclaw_v3,test,0.95,0.91,0.1,high,bullish,2,High risk despite bullish tone,earnings|guidance_change\n',
        encoding='utf-8',
    )
    store = HistoricalSentimentStore(csv_path)
    strategy = TrendSentimentStrategy(StrategyConfig(), sentiment_store=store)
    decision = strategy.decide(symbol='AAA', history=_history_df(), timestamp=datetime(2026, 3, 20, 12, 0, 0), position=None)
    assert decision.intent == TradeIntent.HOLD
    assert 'high-risk event' in decision.reason



def test_strategy_blocks_contradictory_news_open(tmp_path: Path):
    csv_path = tmp_path / 'sentiment.csv'
    csv_path.write_text(
        'timestamp,symbol,score,confidence,source,summary,relevance_score,event_risk_score,contradiction_score,headline_risk,action_bias,source_count,thesis,event_flags\n'
        '2026-03-20T07:15:00Z,AAA,0.6,0.9,openclaw_v3,test,0.95,0.35,0.82,medium,mixed,3,Mixed market reaction,product_launch|analyst_rating\n',
        encoding='utf-8',
    )
    store = HistoricalSentimentStore(csv_path)
    strategy = TrendSentimentStrategy(StrategyConfig(), sentiment_store=store)
    decision = strategy.decide(symbol='AAA', history=_history_df(), timestamp=datetime(2026, 3, 20, 12, 0, 0), position=None)
    assert decision.intent == TradeIntent.HOLD
    assert 'contradictory openclaw research' in decision.reason
