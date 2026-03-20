from trading_bot.live.execution import broker_action_for_intent
from trading_bot.types import TradeIntent


def test_broker_action_mapping_is_explicit_and_correct():
    assert broker_action_for_intent(TradeIntent.OPEN_LONG) == 'BUY'
    assert broker_action_for_intent(TradeIntent.CLOSE_LONG) == 'SELL'
    assert broker_action_for_intent(TradeIntent.OPEN_SHORT) == 'SELL'
    assert broker_action_for_intent(TradeIntent.CLOSE_SHORT) == 'BUY'
