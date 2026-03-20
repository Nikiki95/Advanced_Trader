from trading_bot.sentiment.pipeline import score_headlines


class Item:
    def __init__(self, title: str, summary: str = ''):
        self.title = title
        self.summary = summary


def test_score_headlines_recognizes_positive_bias():
    score, confidence, summary = score_headlines([
        Item('Company beats earnings and shows strong growth'),
        Item('Analysts upgrade stock after rally'),
    ])
    assert score > 0
    assert confidence > 0
    assert 'Company' in summary
