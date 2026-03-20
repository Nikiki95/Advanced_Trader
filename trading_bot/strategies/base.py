from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
import pandas as pd

from trading_bot.types import OrderIntent, Position


class Strategy(ABC):
    @abstractmethod
    def decide(
        self,
        *,
        symbol: str,
        history: pd.DataFrame,
        timestamp: datetime,
        position: Position | None,
    ) -> OrderIntent:
        raise NotImplementedError
