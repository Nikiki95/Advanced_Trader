from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import pandas as pd


REQUIRED_COLUMNS = ["Date", "Open", "High", "Low", "Close", "Volume"]


@dataclass(slots=True)
class CSVMarketDataProvider:
    csv_dir: Path

    def load(self, symbol: str, start: str | None = None, end: str | None = None) -> pd.DataFrame:
        path = self.csv_dir / f"{symbol}.csv"
        if not path.exists():
            raise FileNotFoundError(f"Missing price file for {symbol}: {path}")
        df = pd.read_csv(path)
        missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
        if missing:
            raise ValueError(f"{path} missing required columns: {missing}")
        df["Date"] = pd.to_datetime(df["Date"], utc=False)
        df = df.sort_values("Date").drop_duplicates("Date").reset_index(drop=True)
        if start:
            df = df[df["Date"] >= pd.Timestamp(start)]
        if end:
            df = df[df["Date"] <= pd.Timestamp(end)]
        return df.reset_index(drop=True)
