from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, date

from trading_bot.types import EquityPoint, Position, PositionSide, TradeRecord


@dataclass(slots=True)
class PortfolioLedger:
    starting_cash: float
    cash: float = field(init=False)
    positions: dict[str, Position] = field(default_factory=dict)
    trades: list[TradeRecord] = field(default_factory=list)
    equity_curve: list[EquityPoint] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.cash = float(self.starting_cash)

    def update_mark(self, symbol: str, price: float) -> None:
        pos = self.positions.get(symbol)
        if pos:
            pos.last_price = price

    def open_position(self, symbol: str, side: PositionSide, qty: int, price: float, timestamp: datetime, stop_price: float, fee_bps: float) -> None:
        if qty <= 0:
            return
        if symbol in self.positions:
            raise ValueError(f"Position already open for {symbol}")
        fees = qty * price * (fee_bps / 10_000)
        if side == PositionSide.LONG:
            cash_change = -(qty * price + fees)
        else:
            cash_change = qty * price - fees
        self.cash += cash_change
        self.positions[symbol] = Position(symbol, side, qty, price, timestamp, stop_price, price)

    def close_position(self, symbol: str, price: float, timestamp: datetime, reason: str, fee_bps: float) -> None:
        pos = self.positions.pop(symbol)
        fees = pos.qty * price * (fee_bps / 10_000)
        if pos.side == PositionSide.LONG:
            gross = (price - pos.entry_price) * pos.qty
            cash_change = pos.qty * price - fees
        else:
            gross = (pos.entry_price - price) * pos.qty
            cash_change = -(pos.qty * price) - fees
        self.cash += cash_change
        self.trades.append(
            TradeRecord(
                symbol=symbol,
                side=pos.side,
                entry_time=pos.entry_time,
                exit_time=timestamp,
                qty=pos.qty,
                entry_price=pos.entry_price,
                exit_price=price,
                gross_pnl=gross,
                net_pnl=gross - fees,
                fees=fees,
                exit_reason=reason,
            )
        )

    def total_equity(self) -> float:
        return self.cash + sum(p.market_value() for p in self.positions.values())

    def gross_exposure(self) -> float:
        equity = max(self.total_equity(), 1e-9)
        gross_notional = sum(abs(p.qty * p.last_price) for p in self.positions.values())
        return gross_notional / equity

    def daily_realized_pnl(self, day: date) -> float:
        return sum(t.net_pnl for t in self.trades if t.exit_time.date() == day)

    def record_equity(self, timestamp: datetime) -> None:
        equity = self.total_equity()
        peak = max([p.equity for p in self.equity_curve], default=equity)
        drawdown = 0.0 if peak <= 0 else (equity - peak) / peak
        self.equity_curve.append(
            EquityPoint(
                timestamp=timestamp,
                equity=equity,
                cash=self.cash,
                gross_exposure=self.gross_exposure(),
                drawdown=drawdown,
            )
        )
