from __future__ import annotations

import math
import numpy as np
import pandas as pd


def sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window).mean()


def ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0)
    down = -delta.clip(upper=0)
    gain = up.ewm(alpha=1 / period, adjust=False).mean()
    loss = down.ewm(alpha=1 / period, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    return out.fillna(50)


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high_low = df["High"] - df["Low"]
    high_close = (df["High"] - df["Close"].shift(1)).abs()
    low_close = (df["Low"] - df["Close"].shift(1)).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def macd_hist(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.Series:
    line = ema(close, fast) - ema(close, slow)
    sig = ema(line, signal)
    return line - sig


def bollinger_zscore(close: pd.Series, window: int = 20, num_std: float = 2.0) -> pd.Series:
    mean = sma(close, window)
    std = close.rolling(window).std(ddof=0)
    upper = mean + num_std * std
    lower = mean - num_std * std
    width = (upper - lower).replace(0, np.nan)
    z = (close - mean) / (width / 2)
    return z.fillna(0).clip(-3, 3)


def latest_feature_block(df: pd.DataFrame) -> dict[str, float | str]:
    if len(df) < 30:
        raise ValueError("Need at least 30 bars for technical features")
    close = df["Close"]
    ma_fast = sma(close, 20)
    ma_slow = sma(close, 50)
    rsi_series = rsi(close)
    macd_series = macd_hist(close)
    atr_series = atr(df)
    bbz = bollinger_zscore(close)
    latest_close = float(close.iloc[-1])
    trend_strength = 0.0
    if ma_slow.iloc[-1] and not math.isnan(ma_slow.iloc[-1]):
        trend_strength = float((ma_fast.iloc[-1] - ma_slow.iloc[-1]) / ma_slow.iloc[-1])
    regime = "bull" if ma_fast.iloc[-1] >= ma_slow.iloc[-1] else "bear"
    return {
        "close": latest_close,
        "ma_fast": float(ma_fast.iloc[-1]),
        "ma_slow": float(ma_slow.iloc[-1]),
        "trend_strength": float(np.clip(trend_strength * 10, -1, 1)),
        "rsi": float(rsi_series.iloc[-1]),
        "macd_hist": float(np.tanh(macd_series.iloc[-1] * 5)),
        "atr": float(atr_series.iloc[-1]),
        "bb_zscore": float(bbz.iloc[-1]),
        "regime": regime,
    }
