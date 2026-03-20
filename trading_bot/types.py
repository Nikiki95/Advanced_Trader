from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class TradeIntent(str, Enum):
    OPEN_LONG = "OPEN_LONG"
    CLOSE_LONG = "CLOSE_LONG"
    OPEN_SHORT = "OPEN_SHORT"
    CLOSE_SHORT = "CLOSE_SHORT"
    HOLD = "HOLD"


class PositionSide(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


@dataclass(slots=True)
class SentimentSnapshot:
    symbol: str
    timestamp: datetime
    score: float
    confidence: float
    source: str = "unknown"
    relevance_score: float = 1.0
    headline_risk: str = "low"
    event_flags: list[str] = field(default_factory=list)
    event_risk_score: float = 0.0
    contradiction_score: float = 0.0
    action_bias: str = "neutral"
    thesis: str = ""
    source_count: int = 0
    trading_stance: str = "neutral"
    event_regime: str = "normal"
    approval_policy: str = "auto"


@dataclass(slots=True)
class SignalSnapshot:
    symbol: str
    timestamp: datetime
    trend_score: float
    momentum_score: float
    mean_reversion_score: float
    sentiment_score: float
    final_score: float
    regime: str
    explanation: dict[str, float | str] = field(default_factory=dict)


@dataclass(slots=True)
class OrderIntent:
    symbol: str
    timestamp: datetime
    intent: TradeIntent
    score: float
    reason: str
    stop_atr: float


@dataclass(slots=True)
class Position:
    symbol: str
    side: PositionSide
    qty: int
    entry_price: float
    entry_time: datetime
    stop_price: float
    last_price: float

    def market_value(self) -> float:
        sign = 1 if self.side == PositionSide.LONG else -1
        return sign * self.qty * self.last_price

    def unrealized_pnl(self) -> float:
        if self.side == PositionSide.LONG:
            return (self.last_price - self.entry_price) * self.qty
        return (self.entry_price - self.last_price) * self.qty


@dataclass(slots=True)
class TradeRecord:
    symbol: str
    side: PositionSide
    entry_time: datetime
    exit_time: datetime
    qty: int
    entry_price: float
    exit_price: float
    gross_pnl: float
    net_pnl: float
    fees: float
    exit_reason: str


@dataclass(slots=True)
class EquityPoint:
    timestamp: datetime
    equity: float
    cash: float
    gross_exposure: float
    drawdown: float
