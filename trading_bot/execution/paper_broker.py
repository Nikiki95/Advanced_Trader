from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from trading_bot.execution.broker import Broker
from trading_bot.portfolio.ledger import PortfolioLedger
from trading_bot.types import PositionSide


@dataclass(slots=True)
class PaperBroker(Broker):
    ledger: PortfolioLedger

    def open_position(self, symbol: str, side: PositionSide, qty: int, price: float, timestamp: datetime, stop_price: float, fee_bps: float) -> None:
        self.ledger.open_position(symbol, side, qty, price, timestamp, stop_price, fee_bps)

    def close_position(self, symbol: str, price: float, timestamp: datetime, reason: str, fee_bps: float) -> None:
        self.ledger.close_position(symbol, price, timestamp, reason, fee_bps)
