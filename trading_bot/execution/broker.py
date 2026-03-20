from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from trading_bot.types import PositionSide


class Broker(ABC):
    @abstractmethod
    def open_position(self, symbol: str, side: PositionSide, qty: int, price: float, timestamp: datetime, stop_price: float, fee_bps: float) -> None:
        raise NotImplementedError

    @abstractmethod
    def close_position(self, symbol: str, price: float, timestamp: datetime, reason: str, fee_bps: float) -> None:
        raise NotImplementedError
