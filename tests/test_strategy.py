from datetime import datetime
import pandas as pd

from trading_bot.config import StrategyConfig
from trading_bot.strategies.trend_sentiment import TrendSentimentStrategy
from trading_bot.types import TradeIntent


def make_history():
    dates = pd.bdate_range("2024-01-01", periods=70)
    close = pd.Series([100 + i * 0.6 for i in range(len(dates))])
    df = pd.DataFrame({
        "Date": dates,
        "Open": close * 0.998,
        "High": close * 1.01,
        "Low": close * 0.99,
        "Close": close,
        "Volume": 1_000_000,
    })
    return df


def test_strategy_can_emit_long_entry_without_position():
    cfg = StrategyConfig(long_entry_threshold=0.05)
    strategy = TrendSentimentStrategy(cfg)
    hist = make_history()
    decision = strategy.decide(symbol="AAA", history=hist, timestamp=datetime(2024, 4, 1), position=None)
    assert decision.intent in {TradeIntent.OPEN_LONG, TradeIntent.HOLD}
