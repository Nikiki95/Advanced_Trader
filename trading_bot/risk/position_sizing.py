from __future__ import annotations

import math


def size_from_risk(
    *,
    equity: float,
    cash: float,
    entry_price: float,
    stop_price: float,
    risk_per_trade: float,
    max_symbol_weight: float,
) -> int:
    if entry_price <= 0:
        return 0
    risk_budget = max(equity, 0) * max(risk_per_trade, 0)
    unit_risk = abs(entry_price - stop_price)
    if unit_risk <= 0:
        return 0
    qty_by_risk = math.floor(risk_budget / unit_risk)
    max_notional = equity * max_symbol_weight
    qty_by_weight = math.floor(max_notional / entry_price)
    qty_by_cash = math.floor(max(cash, 0) / entry_price)
    qty = min(qty_by_risk, qty_by_weight, qty_by_cash)
    return max(qty, 0)
