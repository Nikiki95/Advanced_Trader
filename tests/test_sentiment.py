from pathlib import Path
from datetime import datetime

from trading_bot.data.sentiment import HistoricalSentimentStore


def test_asof_lookup_uses_latest_past_snapshot(tmp_path: Path):
    path = tmp_path / "sentiment.csv"
    path.write_text(
        """timestamp,symbol,score,confidence,source
2024-01-01,AAA,0.1,0.6,a
2024-01-03,AAA,0.4,0.9,b
2024-01-05,AAA,-0.1,0.7,c
""",
        encoding="utf-8",
    )
    store = HistoricalSentimentStore(path)
    snap = store.get_latest_asof("AAA", datetime(2024, 1, 4))
    assert snap is not None
    assert snap.score == 0.4
    assert snap.source == "b"
