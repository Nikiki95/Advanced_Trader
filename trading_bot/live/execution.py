from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from trading_bot.types import PositionSide, TradeIntent


class ExecutionUnavailableError(RuntimeError):
    pass


class BrokerSyncError(RuntimeError):
    pass


def broker_action_for_intent(intent: TradeIntent) -> str:
    mapping = {
        TradeIntent.OPEN_LONG: 'BUY',
        TradeIntent.CLOSE_LONG: 'SELL',
        TradeIntent.OPEN_SHORT: 'SELL',
        TradeIntent.CLOSE_SHORT: 'BUY',
    }
    try:
        return mapping[intent]
    except KeyError as exc:
        raise ValueError(f'No broker action for intent {intent}') from exc


@dataclass(slots=True)
class BrokerPositionSnapshot:
    symbol: str
    side: PositionSide
    qty: int
    avg_cost: float
    market_price: float | None = None

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out['side'] = self.side.value
        return out


@dataclass(slots=True)
class BrokerOrderSnapshot:
    order_id: str
    symbol: str
    side: str
    qty: int
    status: str
    order_type: str
    stop_price: float | None = None
    limit_price: float | None = None
    parent_id: str | None = None
    filled_qty: int = 0
    remaining_qty: int = 0
    avg_fill_price: float | None = None
    perm_id: str | None = None
    oca_group: str | None = None
    transmit: bool | None = None
    child_order_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class BrokerFillSnapshot:
    execution_id: str
    order_id: str | None
    symbol: str
    side: str
    qty: int
    price: float
    timestamp: datetime
    commission: float | None = None
    realized_pnl: float | None = None
    liquidity: int | None = None
    parent_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out['timestamp'] = self.timestamp.isoformat()
        return out


@dataclass(slots=True)
class BrokerAccountSnapshot:
    timestamp: datetime
    net_liquidation: float | None = None
    available_funds: float | None = None
    total_cash_value: float | None = None
    buying_power: float | None = None
    unrealized_pnl: float | None = None
    realized_pnl: float | None = None
    account: str | None = None

    def to_dict(self) -> dict[str, Any]:
        out = asdict(self)
        out['timestamp'] = self.timestamp.isoformat()
        return out


@dataclass(slots=True)
class BrokerSyncSnapshot:
    timestamp: datetime
    positions: list[BrokerPositionSnapshot] = field(default_factory=list)
    open_orders: list[BrokerOrderSnapshot] = field(default_factory=list)
    account: BrokerAccountSnapshot | None = None
    recent_fills: list[BrokerFillSnapshot] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            'timestamp': self.timestamp.isoformat(),
            'positions': [p.to_dict() for p in self.positions],
            'open_orders': [o.to_dict() for o in self.open_orders],
            'account': self.account.to_dict() if self.account else None,
            'recent_fills': [f.to_dict() for f in self.recent_fills],
        }


@dataclass(slots=True)
class ExecutionReport:
    symbol: str
    intent: str
    broker_side: str
    requested_qty: int
    filled_qty: int
    status: str
    submitted_at: datetime
    avg_fill_price: float | None = None
    order_id: str | None = None
    stop_order_id: str | None = None
    stop_price: float | None = None
    stop_status: str | None = None
    cancelled_stop_ids: list[str] = field(default_factory=list)
    remaining_qty: int | None = None
    parent_order_id: str | None = None
    bracket_id: str | None = None
    child_order_ids: list[str] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            'symbol': self.symbol,
            'intent': self.intent,
            'broker_side': self.broker_side,
            'requested_qty': self.requested_qty,
            'filled_qty': self.filled_qty,
            'remaining_qty': self.remaining_qty,
            'status': self.status,
            'submitted_at': self.submitted_at.isoformat(),
            'avg_fill_price': self.avg_fill_price,
            'order_id': self.order_id,
            'stop_order_id': self.stop_order_id,
            'stop_price': self.stop_price,
            'stop_status': self.stop_status,
            'cancelled_stop_ids': list(self.cancelled_stop_ids),
            'parent_order_id': self.parent_order_id,
            'bracket_id': self.bracket_id,
            'child_order_ids': list(self.child_order_ids),
            'raw': self.raw,
        }


@dataclass(slots=True)
class IBKRExecutor:
    host: str
    port: int
    client_id: int
    account: str | None = None

    def _require_ib(self):
        try:
            from ib_insync import IB, MarketOrder, StopOrder, Stock
        except Exception as exc:
            raise ExecutionUnavailableError('ib_insync is not installed. Install with pip install -e .[ibkr]') from exc
        return IB, MarketOrder, StopOrder, Stock

    def _connect(self):
        IB, MarketOrder, StopOrder, Stock = self._require_ib()
        ib = IB()
        try:
            ib.connect(self.host, self.port, clientId=self.client_id, readonly=False, timeout=10)
        except Exception as exc:
            raise BrokerSyncError(f'Unable to connect to IBKR at {self.host}:{self.port}: {exc}') from exc
        return ib, MarketOrder, StopOrder, Stock

    def _wait_for_terminal_status(self, ib, trade, timeout_seconds: int):
        deadline = datetime.now(timezone.utc).timestamp() + timeout_seconds
        terminal = {'Filled', 'Cancelled', 'Inactive', 'ApiCancelled'}
        partial = {'Submitted', 'PreSubmitted', 'PartiallyFilled'}
        while datetime.now(timezone.utc).timestamp() < deadline:
            ib.sleep(0.5)
            status = getattr(trade.orderStatus, 'status', '')
            if status in terminal:
                break
            if status in partial and getattr(trade.orderStatus, 'filled', 0):
                break
        return getattr(trade.orderStatus, 'status', 'Unknown')

    def _cancel_symbol_stops(self, ib, symbol: str) -> list[str]:
        cancelled: list[str] = []
        try:
            for trade in ib.openTrades():
                contract = getattr(trade, 'contract', None)
                order = getattr(trade, 'order', None)
                status = getattr(getattr(trade, 'orderStatus', None), 'status', '')
                if contract is None or order is None:
                    continue
                if getattr(contract, 'symbol', '').upper() != symbol.upper():
                    continue
                if getattr(order, 'orderType', '').upper() != 'STP':
                    continue
                if status in {'Cancelled', 'Filled', 'Inactive', 'ApiCancelled'}:
                    continue
                ib.cancelOrder(order)
                cancelled.append(str(getattr(order, 'orderId', '')))
        except Exception:
            return cancelled
        return cancelled

    def cancel_symbol_stops(self, symbol: str) -> list[str]:
        ib, _, _, _ = self._connect()
        try:
            return self._cancel_symbol_stops(ib, symbol)
        finally:
            ib.disconnect()

    def cancel_order_by_id(self, order_id: str) -> bool:
        ib, _, _, _ = self._connect()
        try:
            for trade in ib.openTrades():
                order = getattr(trade, 'order', None)
                if order is None:
                    continue
                if str(getattr(order, 'orderId', '')) != str(order_id):
                    continue
                ib.cancelOrder(order)
                return True
            return False
        finally:
            ib.disconnect()


    def cancel_orders(self, order_ids: list[str]) -> list[str]:
        cancelled: list[str] = []
        for oid in order_ids:
            try:
                if self.cancel_order_by_id(str(oid)):
                    cancelled.append(str(oid))
            except Exception:
                continue
        return cancelled

    def resize_protective_stop(
        self,
        *,
        symbol: str,
        position_side: PositionSide,
        qty: int,
        stop_price: float,
        existing_order_ids: list[str] | None = None,
        exchange: str = 'SMART',
        currency: str = 'USD',
        timeout_seconds: int = 10,
    ) -> tuple[BrokerOrderSnapshot, list[str]]:
        cancelled = self.cancel_orders([str(x) for x in (existing_order_ids or []) if x]) if existing_order_ids else []
        stop = self.ensure_protective_stop(
            symbol=symbol,
            position_side=position_side,
            qty=qty,
            stop_price=stop_price,
            exchange=exchange,
            currency=currency,
            timeout_seconds=timeout_seconds,
        )
        return stop, cancelled

    def ensure_protective_stop(
        self,
        *,
        symbol: str,
        position_side: PositionSide,
        qty: int,
        stop_price: float,
        exchange: str = 'SMART',
        currency: str = 'USD',
        timeout_seconds: int = 10,
    ) -> BrokerOrderSnapshot:
        if qty <= 0:
            raise ValueError('qty must be positive')
        ib, _, StopOrder, Stock = self._connect()
        try:
            contract = Stock(symbol, exchange, currency)
            ib.qualifyContracts(contract)
            self._cancel_symbol_stops(ib, symbol)
            side = 'SELL' if position_side == PositionSide.LONG else 'BUY'
            order_kwargs = {'account': self.account} if self.account else {}
            trade = ib.placeOrder(contract, StopOrder(side, qty, float(stop_price), **order_kwargs))
            status = self._wait_for_terminal_status(ib, trade, timeout_seconds)
            raw_order = getattr(trade, 'order', None)
            raw_status = getattr(trade, 'orderStatus', None)
            return BrokerOrderSnapshot(
                order_id=str(getattr(raw_order, 'orderId', '')),
                symbol=symbol.upper(),
                side=side,
                qty=int(getattr(raw_order, 'totalQuantity', qty) or qty),
                status=str(status),
                order_type='STP',
                stop_price=float(stop_price),
                filled_qty=int(getattr(raw_status, 'filled', 0) or 0),
                remaining_qty=int(getattr(raw_status, 'remaining', qty) or 0),
                avg_fill_price=float(getattr(raw_status, 'avgFillPrice', 0.0) or 0.0) or None,
            )
        finally:
            ib.disconnect()

    def _place_entry_bracket(
        self,
        ib,
        MarketOrder,
        StopOrder,
        contract,
        *,
        side: str,
        qty: int,
        stop_price: float,
        timeout_seconds: int,
    ) -> tuple[Any, Any, str | None, str | None, str | None, str | None, int, int, float | None, str]:
        order_kwargs = {'account': self.account} if self.account else {}
        parent = MarketOrder(side, qty, **order_kwargs)
        parent.transmit = False
        parent_trade = ib.placeOrder(contract, parent)
        ib.sleep(0.25)
        parent_id = getattr(getattr(parent_trade, 'order', None), 'orderId', None)
        opposite = 'SELL' if side == 'BUY' else 'BUY'
        stop = StopOrder(opposite, qty, float(stop_price), **order_kwargs)
        if parent_id is not None:
            stop.parentId = int(parent_id)
        stop.transmit = True
        stop_trade = ib.placeOrder(contract, stop)
        status = self._wait_for_terminal_status(ib, parent_trade, timeout_seconds)
        filled_qty = int(getattr(parent_trade.orderStatus, 'filled', 0) or 0)
        remaining_qty = int(getattr(parent_trade.orderStatus, 'remaining', max(qty - filled_qty, 0)) or 0)
        fill_price = getattr(parent_trade.orderStatus, 'avgFillPrice', None)
        fill_price = float(fill_price) if fill_price not in (None, '') else None
        ib.sleep(0.25)
        stop_status = getattr(stop_trade.orderStatus, 'status', 'Submitted')
        stop_order_id = getattr(getattr(stop_trade, 'order', None), 'orderId', None)
        order_id = getattr(getattr(parent_trade, 'order', None), 'orderId', None)
        bracket_id = str(parent_id if parent_id is not None else order_id) if (parent_id is not None or order_id is not None) else None
        return parent_trade, stop_trade, str(order_id) if order_id is not None else None, str(stop_order_id) if stop_order_id is not None else None, str(parent_id) if parent_id is not None else None, bracket_id, filled_qty, remaining_qty, fill_price, str(status)

    def execute(
        self,
        *,
        symbol: str,
        intent: TradeIntent,
        qty: int,
        stop_price: float | None,
        exchange: str = 'SMART',
        currency: str = 'USD',
        timeout_seconds: int = 20,
    ) -> ExecutionReport:
        if qty <= 0:
            raise ValueError('qty must be positive')
        if intent == TradeIntent.HOLD:
            return ExecutionReport(
                symbol=symbol,
                intent=intent.value,
                broker_side='NONE',
                requested_qty=qty,
                filled_qty=0,
                remaining_qty=0,
                status='skipped',
                submitted_at=datetime.now(timezone.utc),
            )

        ib, MarketOrder, StopOrder, Stock = self._connect()
        try:
            contract = Stock(symbol, exchange, currency)
            ib.qualifyContracts(contract)
            cancelled_stop_ids: list[str] = []
            if intent in {TradeIntent.CLOSE_LONG, TradeIntent.CLOSE_SHORT}:
                cancelled_stop_ids = self._cancel_symbol_stops(ib, symbol)
            side = broker_action_for_intent(intent)
            order_kwargs = {'account': self.account} if self.account else {}

            stop_order_id = None
            stop_status = None
            parent_order_id = None
            bracket_id = None
            child_order_ids: list[str] = []

            if intent in {TradeIntent.OPEN_LONG, TradeIntent.OPEN_SHORT} and stop_price is not None:
                trade, stop_trade, order_id, stop_order_id, parent_order_id, bracket_id, filled_qty, remaining_qty, fill_price, status = self._place_entry_bracket(
                    ib,
                    MarketOrder,
                    StopOrder,
                    contract,
                    side=side,
                    qty=qty,
                    stop_price=float(stop_price),
                    timeout_seconds=timeout_seconds,
                )
                stop_status = getattr(stop_trade.orderStatus, 'status', 'Submitted')
                if stop_order_id:
                    child_order_ids.append(stop_order_id)
            else:
                trade = ib.placeOrder(contract, MarketOrder(side, qty, **order_kwargs))
                status = self._wait_for_terminal_status(ib, trade, timeout_seconds)
                filled_qty = int(getattr(trade.orderStatus, 'filled', 0) or 0)
                remaining_qty = int(getattr(trade.orderStatus, 'remaining', max(qty - filled_qty, 0)) or 0)
                fill_price = getattr(trade.orderStatus, 'avgFillPrice', None)
                fill_price = float(fill_price) if fill_price not in (None, '') else None
                raw_order_id = getattr(getattr(trade, 'order', None), 'orderId', None)
                order_id = str(raw_order_id) if raw_order_id is not None else None

            return ExecutionReport(
                symbol=symbol,
                intent=intent.value,
                broker_side=side,
                requested_qty=qty,
                filled_qty=filled_qty,
                remaining_qty=remaining_qty,
                status=status,
                submitted_at=datetime.now(timezone.utc),
                avg_fill_price=fill_price,
                order_id=order_id,
                stop_order_id=stop_order_id,
                stop_price=float(stop_price) if stop_price is not None else None,
                stop_status=stop_status,
                cancelled_stop_ids=cancelled_stop_ids,
                parent_order_id=parent_order_id or order_id,
                bracket_id=bracket_id or order_id,
                child_order_ids=child_order_ids,
                raw={
                    'exchange': exchange,
                    'currency': currency,
                    'account': self.account,
                },
            )
        finally:
            ib.disconnect()

    @staticmethod
    def _safe_float(value: Any) -> float | None:
        try:
            if value in (None, ''):
                return None
            return float(value)
        except Exception:
            return None

    @staticmethod
    def _safe_int(value: Any) -> int | None:
        try:
            if value in (None, ''):
                return None
            return int(value)
        except Exception:
            return None

    def sync_account_snapshot(self, *, fills_since: datetime | None = None, fills_lookback_minutes: int = 1440) -> BrokerSyncSnapshot:
        ib, _, _, _ = self._connect()
        try:
            if self.account:
                positions = ib.positions(self.account)
            else:
                positions = ib.positions()
            position_rows: list[BrokerPositionSnapshot] = []
            for pos in positions:
                qty = int(getattr(pos, 'position', 0) or 0)
                if qty == 0:
                    continue
                contract = getattr(pos, 'contract', None)
                symbol = getattr(contract, 'symbol', None)
                if not symbol:
                    continue
                side = PositionSide.LONG if qty > 0 else PositionSide.SHORT
                position_rows.append(
                    BrokerPositionSnapshot(
                        symbol=str(symbol).upper(),
                        side=side,
                        qty=abs(qty),
                        avg_cost=float(getattr(pos, 'avgCost', 0.0) or 0.0),
                        market_price=None,
                    )
                )

            order_rows: list[BrokerOrderSnapshot] = []
            child_map: dict[str, list[str]] = {}
            raw_order_rows: list[tuple[Any, Any, Any, Any]] = []
            for trade in ib.openTrades():
                contract = getattr(trade, 'contract', None)
                order = getattr(trade, 'order', None)
                order_status = getattr(trade, 'orderStatus', None)
                if contract is None or order is None:
                    continue
                symbol = getattr(contract, 'symbol', None)
                if not symbol:
                    continue
                raw_order_rows.append((trade, contract, order, order_status))
                parent_id = str(getattr(order, 'parentId', '')) if getattr(order, 'parentId', None) else None
                order_id = str(getattr(order, 'orderId', ''))
                if parent_id and order_id:
                    child_map.setdefault(parent_id, []).append(order_id)
            for trade, contract, order, order_status in raw_order_rows:
                symbol = getattr(contract, 'symbol', None)
                total_qty = int(getattr(order, 'totalQuantity', 0) or 0)
                filled_qty = int(getattr(order_status, 'filled', 0) or 0)
                remaining_qty = int(getattr(order_status, 'remaining', max(total_qty - filled_qty, 0)) or 0)
                order_id = str(getattr(order, 'orderId', ''))
                order_rows.append(
                    BrokerOrderSnapshot(
                        order_id=order_id,
                        symbol=str(symbol).upper(),
                        side=str(getattr(order, 'action', '')),
                        qty=total_qty,
                        status=str(getattr(order_status, 'status', 'Unknown')),
                        order_type=str(getattr(order, 'orderType', '')),
                        stop_price=float(getattr(order, 'auxPrice', 0.0) or 0.0) if getattr(order, 'orderType', '').upper() == 'STP' else None,
                        limit_price=float(getattr(order, 'lmtPrice', 0.0) or 0.0) if getattr(order, 'orderType', '').upper() == 'LMT' else None,
                        parent_id=str(getattr(order, 'parentId', '')) if getattr(order, 'parentId', None) else None,
                        filled_qty=filled_qty,
                        remaining_qty=remaining_qty,
                        avg_fill_price=self._safe_float(getattr(order_status, 'avgFillPrice', None)),
                        perm_id=str(getattr(order, 'permId', '')) if getattr(order, 'permId', None) else None,
                        oca_group=str(getattr(order, 'ocaGroup', '')) if getattr(order, 'ocaGroup', None) else None,
                        transmit=bool(getattr(order, 'transmit', True)) if getattr(order, 'transmit', None) is not None else None,
                        child_order_ids=list(child_map.get(order_id, [])),
                    )
                )

            fill_rows: list[BrokerFillSnapshot] = []
            try:
                now_utc = datetime.now(timezone.utc)
                lookback_cutoff = now_utc.timestamp() - (int(fills_lookback_minutes) * 60)
                for fill in ib.fills():
                    contract = getattr(fill, 'contract', None)
                    execution = getattr(fill, 'execution', None)
                    if contract is None or execution is None:
                        continue
                    symbol = getattr(contract, 'symbol', None)
                    if not symbol:
                        continue
                    exec_time = getattr(execution, 'time', None)
                    if isinstance(exec_time, datetime):
                        fill_time = exec_time.astimezone(timezone.utc) if exec_time.tzinfo else exec_time.replace(tzinfo=timezone.utc)
                    else:
                        fill_time = datetime.now(timezone.utc)
                    if fill_time.timestamp() < lookback_cutoff:
                        continue
                    if fills_since is not None and fill_time <= fills_since:
                        continue
                    commission_report = getattr(fill, 'commissionReport', None)
                    fill_rows.append(
                        BrokerFillSnapshot(
                            execution_id=str(getattr(execution, 'execId', '')),
                            order_id=str(getattr(execution, 'orderId', '')) if getattr(execution, 'orderId', None) is not None else None,
                            symbol=str(symbol).upper(),
                            side=str(getattr(execution, 'side', '')),
                            qty=abs(int(float(getattr(execution, 'shares', 0) or 0))),
                            price=float(getattr(execution, 'price', 0.0) or 0.0),
                            timestamp=fill_time,
                            commission=self._safe_float(getattr(commission_report, 'commission', None)) if commission_report else None,
                            realized_pnl=self._safe_float(getattr(commission_report, 'realizedPNL', None)) if commission_report else None,
                            liquidity=self._safe_int(getattr(execution, 'liquidation', None)),
                            parent_id=None,
                        )
                    )
            except Exception:
                fill_rows = []

            account = None
            try:
                rows = ib.accountSummary(self.account) if self.account else ib.accountSummary()
                tags = {getattr(row, 'tag', ''): getattr(row, 'value', None) for row in rows}
                account = BrokerAccountSnapshot(
                    timestamp=datetime.now(timezone.utc),
                    net_liquidation=self._safe_float(tags.get('NetLiquidation')),
                    available_funds=self._safe_float(tags.get('AvailableFunds')),
                    total_cash_value=self._safe_float(tags.get('TotalCashValue')),
                    buying_power=self._safe_float(tags.get('BuyingPower')),
                    unrealized_pnl=self._safe_float(tags.get('UnrealizedPnL')),
                    realized_pnl=self._safe_float(tags.get('RealizedPnL')),
                    account=self.account,
                )
            except Exception:
                account = None

            return BrokerSyncSnapshot(
                timestamp=datetime.now(timezone.utc),
                positions=position_rows,
                open_orders=order_rows,
                account=account,
                recent_fills=fill_rows,
            )
        finally:
            ib.disconnect()
