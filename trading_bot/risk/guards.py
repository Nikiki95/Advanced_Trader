from __future__ import annotations

from dataclasses import dataclass

from trading_bot.config import RiskConfig
from trading_bot.types import PositionSide


@dataclass(slots=True)
class RiskGuard:
    config: RiskConfig

    def stop_price(self, side: PositionSide, entry_price: float, atr_value: float) -> float:
        distance = max(atr_value * self.config.stop_atr_multiple, 0.01)
        if side == PositionSide.LONG:
            return max(entry_price - distance, 0.01)
        return entry_price + distance

    def can_open_position(
        self,
        *,
        open_positions: int,
        gross_exposure: float,
        equity: float,
        cash: float,
        daily_pnl: float,
    ) -> bool:
        if open_positions >= self.config.max_positions:
            return False
        if equity <= 0:
            return False
        if gross_exposure > self.config.max_gross_exposure:
            return False
        if cash < equity * self.config.min_cash_buffer_pct:
            return False
        if daily_pnl <= -(equity * self.config.daily_loss_limit_pct):
            return False
        return True
