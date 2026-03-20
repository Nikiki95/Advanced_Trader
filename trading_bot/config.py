from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import yaml


@dataclass(slots=True)
class UniverseConfig:
    symbols: list[str]


@dataclass(slots=True)
class MarketDataConfig:
    source: str = "csv"
    csv_dir: str = "examples/data/prices"


@dataclass(slots=True)
class SentimentConfig:
    path: str | None = None
    current_json_path: str | None = None


@dataclass(slots=True)
class StrategyWeights:
    trend: float = 0.35
    momentum: float = 0.25
    mean_reversion: float = 0.10
    sentiment: float = 0.30


@dataclass(slots=True)
class StrategyConfig:
    warmup_bars: int = 30
    long_entry_threshold: float = 0.35
    short_entry_threshold: float = -0.35
    long_exit_threshold: float = -0.05
    short_exit_threshold: float = 0.05
    weights: StrategyWeights = field(default_factory=StrategyWeights)


@dataclass(slots=True)
class RiskConfig:
    starting_cash: float = 100_000.0
    risk_per_trade: float = 0.01
    max_positions: int = 4
    max_gross_exposure: float = 1.50
    min_cash_buffer_pct: float = 0.10
    stop_atr_multiple: float = 2.0
    daily_loss_limit_pct: float = 0.03
    max_symbol_weight: float = 0.35


@dataclass(slots=True)
class BacktestConfig:
    start: str
    end: str
    slippage_bps: float = 5.0
    fee_bps: float = 1.0
    allow_shorting: bool = True


@dataclass(slots=True)
class AppConfig:
    universe: UniverseConfig
    market_data: MarketDataConfig = field(default_factory=MarketDataConfig)
    sentiment: SentimentConfig = field(default_factory=SentimentConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    backtest: BacktestConfig | None = None


def _merge(cls, payload: dict[str, Any]):
    values = {}
    for name in cls.__dataclass_fields__:
        if name in payload:
            values[name] = payload[name]
    return cls(**values)


def load_raw_config(path: str | Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def resolve_relative_path(config_path: str | Path, value: str | None) -> str | None:
    if not value:
        return value
    p = Path(value)
    if p.is_absolute():
        return str(p)
    return str((Path(config_path).resolve().parent / p).resolve())


def load_config(path: str | Path) -> AppConfig:
    payload = load_raw_config(path)

    universe_payload = payload.get("universe", {})
    strategy_payload = dict(payload.get("strategy", {}) or {})
    weights_payload = strategy_payload.pop("weights", {}) or {}

    cfg = AppConfig(
        universe=_merge(UniverseConfig, universe_payload),
        market_data=_merge(MarketDataConfig, payload.get("market_data", {}) or {}),
        sentiment=_merge(SentimentConfig, payload.get("sentiment", {}) or {}),
        strategy=StrategyConfig(
            **{k: v for k, v in strategy_payload.items() if k in StrategyConfig.__dataclass_fields__ and k != "weights"},
            weights=_merge(StrategyWeights, weights_payload),
        ),
        risk=_merge(RiskConfig, payload.get("risk", {}) or {}),
        backtest=_merge(BacktestConfig, payload.get("backtest", {}) or {}) if payload.get("backtest") else None,
    )
    if not cfg.universe.symbols:
        raise ValueError("At least one symbol is required in universe.symbols")
    cfg.market_data.csv_dir = resolve_relative_path(path, cfg.market_data.csv_dir) or cfg.market_data.csv_dir
    cfg.sentiment.path = resolve_relative_path(path, cfg.sentiment.path)
    cfg.sentiment.current_json_path = resolve_relative_path(path, cfg.sentiment.current_json_path)
    return cfg
