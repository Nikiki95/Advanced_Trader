from trading_bot.risk.position_sizing import size_from_risk


def test_size_from_risk_obeys_cash_and_risk():
    qty = size_from_risk(
        equity=100_000,
        cash=20_000,
        entry_price=100,
        stop_price=95,
        risk_per_trade=0.01,
        max_symbol_weight=0.35,
    )
    assert qty == 200
