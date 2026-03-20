from __future__ import annotations

from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "examples" / "data"
PRICES = OUT / "prices"
PRICES.mkdir(parents=True, exist_ok=True)

rng = np.random.default_rng(42)
dates = pd.bdate_range("2024-01-01", "2024-06-28")

for symbol, drift, phase in [("AAA", 0.0010, 0.0), ("BBB", -0.0002, 1.3)]:
    price = 100.0
    rows = []
    for i, dt in enumerate(dates):
        season = np.sin(i / 9 + phase) * 0.6
        move = drift + season * 0.003 + rng.normal(0, 0.012)
        open_ = price * (1 + rng.normal(0, 0.004))
        close = max(5.0, open_ * (1 + move))
        high = max(open_, close) * (1 + abs(rng.normal(0, 0.006)))
        low = min(open_, close) * (1 - abs(rng.normal(0, 0.006)))
        vol = int(1_000_000 + rng.normal(0, 120_000))
        rows.append((dt, open_, high, low, close, vol))
        price = close
    pd.DataFrame(rows, columns=["Date", "Open", "High", "Low", "Close", "Volume"]).to_csv(PRICES / f"{symbol}.csv", index=False)

sent_rows = []
for dt in dates[::5]:
    sent_rows.append((dt, "AAA", 0.35 + rng.normal(0, 0.12), 0.80, "demo_feed"))
    sent_rows.append((dt, "BBB", -0.20 + rng.normal(0, 0.15), 0.75, "demo_feed"))

pd.DataFrame(sent_rows, columns=["timestamp", "symbol", "score", "confidence", "source"]).to_csv(OUT / "sentiment_snapshots.csv", index=False)
print("Demo data written to", OUT)
