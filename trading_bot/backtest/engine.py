from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import pandas as pd

from trading_bot.config import AppConfig
from trading_bot.data.market import CSVMarketDataProvider
from trading_bot.data.sentiment import HistoricalSentimentStore
from trading_bot.execution.paper_broker import PaperBroker
from trading_bot.portfolio.ledger import PortfolioLedger
from trading_bot.risk.guards import RiskGuard
from trading_bot.risk.position_sizing import size_from_risk
from trading_bot.strategies.trend_sentiment import TrendSentimentStrategy
from trading_bot.types import OrderIntent, PositionSide, TradeIntent


@dataclass(slots=True)
class PendingInstruction:
    symbol: str
    intent: TradeIntent
    score: float
    reason: str
    stop_atr: float


@dataclass(slots=True)
class BacktestResult:
    ledger: PortfolioLedger
    orders: list[dict] = field(default_factory=list)


class BacktestEngine:
    def __init__(self, config: AppConfig):
        if not config.backtest:
            raise ValueError("Backtest config is required")
        self.config = config
        self.market = CSVMarketDataProvider(Path(config.market_data.csv_dir))
        self.sentiment = HistoricalSentimentStore(Path(config.sentiment.path)) if config.sentiment.path else None
        self.strategy = TrendSentimentStrategy(config.strategy, self.sentiment)
        self.risk = RiskGuard(config.risk)
        self.ledger = PortfolioLedger(config.risk.starting_cash)
        self.broker = PaperBroker(self.ledger)
        self.pending: dict[pd.Timestamp, list[PendingInstruction]] = {}
        self.orders: list[dict] = []

    def run(self) -> BacktestResult:
        data = {
            symbol: self.market.load(symbol, self.config.backtest.start, self.config.backtest.end)
            for symbol in self.config.universe.symbols
        }
        calendar = sorted(set().union(*(set(df["Date"]) for df in data.values())))
        warmup = self.config.strategy.warmup_bars

        for current_date in calendar:
            self._execute_pending(current_date, data)
            self._check_stops(current_date, data)
            self._mark_portfolio(current_date, data)
            self.ledger.record_equity(pd.Timestamp(current_date).to_pydatetime())
            next_date = self._next_calendar_date(calendar, current_date)
            if next_date is None:
                continue
            for symbol, df in data.items():
                idxs = df.index[df["Date"] == current_date].tolist()
                if not idxs:
                    continue
                idx = idxs[0]
                if idx + 1 >= len(df) or idx + 1 < warmup:
                    continue
                history = df.iloc[: idx + 1].copy()
                position = self.ledger.positions.get(symbol)
                decision = self.strategy.decide(
                    symbol=symbol,
                    history=history,
                    timestamp=pd.Timestamp(current_date).to_pydatetime(),
                    position=position,
                )
                if decision.intent != TradeIntent.HOLD:
                    self.pending.setdefault(pd.Timestamp(next_date), []).append(
                        PendingInstruction(
                            symbol=decision.symbol,
                            intent=decision.intent,
                            score=decision.score,
                            reason=decision.reason,
                            stop_atr=decision.stop_atr,
                        )
                    )
        self._force_close_final_positions(data, calendar[-1])
        return BacktestResult(self.ledger, self.orders)

    def _next_calendar_date(self, calendar: list[pd.Timestamp], current_date: pd.Timestamp):
        idx = calendar.index(current_date)
        if idx + 1 >= len(calendar):
            return None
        return calendar[idx + 1]

    def _bar_for_date(self, df: pd.DataFrame, current_date: pd.Timestamp):
        view = df[df["Date"] == current_date]
        return None if view.empty else view.iloc[0]

    def _execute_pending(self, current_date: pd.Timestamp, data: dict[str, pd.DataFrame]) -> None:
        instructions = self.pending.pop(pd.Timestamp(current_date), [])
        for ins in instructions:
            df = data[ins.symbol]
            bar = self._bar_for_date(df, current_date)
            if bar is None:
                continue
            fill = self._apply_slippage(float(bar["Open"]), ins.intent)
            timestamp = pd.Timestamp(current_date).to_pydatetime()
            if ins.intent in {TradeIntent.CLOSE_LONG, TradeIntent.CLOSE_SHORT}:
                if ins.symbol in self.ledger.positions:
                    self.broker.close_position(ins.symbol, fill, timestamp, ins.reason, self.config.backtest.fee_bps)
                    self.orders.append({"timestamp": timestamp, "symbol": ins.symbol, "intent": ins.intent.value, "price": fill})
                continue
            if not self.config.backtest.allow_shorting and ins.intent == TradeIntent.OPEN_SHORT:
                continue
            equity = self.ledger.total_equity()
            cash = self.ledger.cash
            daily_pnl = self.ledger.daily_realized_pnl(timestamp.date())
            if not self.risk.can_open_position(
                open_positions=len(self.ledger.positions),
                gross_exposure=self.ledger.gross_exposure(),
                equity=equity,
                cash=cash,
                daily_pnl=daily_pnl,
            ):
                continue
            side = PositionSide.LONG if ins.intent == TradeIntent.OPEN_LONG else PositionSide.SHORT
            stop_price = self.risk.stop_price(side, fill, ins.stop_atr)
            qty = size_from_risk(
                equity=equity,
                cash=cash,
                entry_price=fill,
                stop_price=stop_price,
                risk_per_trade=self.config.risk.risk_per_trade,
                max_symbol_weight=self.config.risk.max_symbol_weight,
            )
            if qty <= 0 or ins.symbol in self.ledger.positions:
                continue
            self.broker.open_position(ins.symbol, side, qty, fill, timestamp, stop_price, self.config.backtest.fee_bps)
            self.orders.append({"timestamp": timestamp, "symbol": ins.symbol, "intent": ins.intent.value, "price": fill, "qty": qty})

    def _check_stops(self, current_date: pd.Timestamp, data: dict[str, pd.DataFrame]) -> None:
        for symbol, pos in list(self.ledger.positions.items()):
            df = data[symbol]
            bar = self._bar_for_date(df, current_date)
            if bar is None:
                continue
            timestamp = pd.Timestamp(current_date).to_pydatetime()
            if pos.side == PositionSide.LONG and float(bar["Low"]) <= pos.stop_price:
                self.broker.close_position(symbol, pos.stop_price, timestamp, "stop_loss", self.config.backtest.fee_bps)
            elif pos.side == PositionSide.SHORT and float(bar["High"]) >= pos.stop_price:
                self.broker.close_position(symbol, pos.stop_price, timestamp, "stop_loss", self.config.backtest.fee_bps)

    def _mark_portfolio(self, current_date: pd.Timestamp, data: dict[str, pd.DataFrame]) -> None:
        for symbol, df in data.items():
            bar = self._bar_for_date(df, current_date)
            if bar is not None:
                self.ledger.update_mark(symbol, float(bar["Close"]))

    def _force_close_final_positions(self, data: dict[str, pd.DataFrame], final_date: pd.Timestamp) -> None:
        timestamp = pd.Timestamp(final_date).to_pydatetime()
        for symbol in list(self.ledger.positions.keys()):
            df = data[symbol]
            bar = self._bar_for_date(df, final_date)
            if bar is None:
                continue
            self.broker.close_position(symbol, float(bar["Close"]), timestamp, "end_of_backtest", self.config.backtest.fee_bps)
            self.ledger.update_mark(symbol, float(bar["Close"]))
        self.ledger.record_equity(timestamp)

    def _apply_slippage(self, price: float, intent: TradeIntent) -> float:
        bps = self.config.backtest.slippage_bps / 10_000
        if intent in {TradeIntent.OPEN_LONG, TradeIntent.CLOSE_SHORT}:
            return price * (1 + bps)
        return price * (1 - bps)
