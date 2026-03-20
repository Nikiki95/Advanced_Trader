from __future__ import annotations

from dataclasses import dataclass
import math

from trading_bot.portfolio.ledger import PortfolioLedger


@dataclass(slots=True)
class BacktestSummary:
    total_return_pct: float
    max_drawdown_pct: float
    win_rate_pct: float
    trades: int
    profit_factor: float
    avg_trade: float
    ending_equity: float


def summarize(ledger: PortfolioLedger) -> BacktestSummary:
    ending_equity = ledger.total_equity()
    total_return_pct = ((ending_equity / ledger.starting_cash) - 1) * 100
    trades = len(ledger.trades)
    wins = [t.net_pnl for t in ledger.trades if t.net_pnl > 0]
    losses = [t.net_pnl for t in ledger.trades if t.net_pnl < 0]
    win_rate = (len(wins) / trades * 100) if trades else 0.0
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else math.inf if gross_profit > 0 else 0.0
    avg_trade = sum(t.net_pnl for t in ledger.trades) / trades if trades else 0.0
    max_drawdown_pct = abs(min((p.drawdown for p in ledger.equity_curve), default=0.0)) * 100
    return BacktestSummary(
        total_return_pct=total_return_pct,
        max_drawdown_pct=max_drawdown_pct,
        win_rate_pct=win_rate,
        trades=trades,
        profit_factor=profit_factor,
        avg_trade=avg_trade,
        ending_equity=ending_equity,
    )
