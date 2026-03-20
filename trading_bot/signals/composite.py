from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import numpy as np
import pandas as pd

from trading_bot.config import StrategyConfig
from trading_bot.signals.technicals import latest_feature_block
from trading_bot.integrations.openclaw.regime import sentiment_regime_multiplier
from trading_bot.types import SentimentSnapshot, SignalSnapshot


@dataclass(slots=True)
class CompositeSignalEngine:
    config: StrategyConfig

    def score(self, symbol: str, history: pd.DataFrame, timestamp: datetime, sentiment: SentimentSnapshot | None) -> SignalSnapshot:
        feats = latest_feature_block(history)
        trend = float(np.clip(feats["trend_strength"], -1, 1))
        rsi = float(feats["rsi"])
        macd = float(feats["macd_hist"])
        bb_z = float(feats["bb_zscore"])
        regime = str(feats["regime"])

        momentum = float(np.clip((50 - abs(rsi - 50)) / 50 * np.sign(macd if macd != 0 else 1), -1, 1))
        mean_reversion = float(np.clip(-bb_z / 2, -1, 1))

        sent_score = 0.0
        sent_conf = 0.0
        relevance_mult = 1.0
        risk_mult = 1.0
        contradiction_mult = 1.0
        bias_adjust = 0.0
        regime_mult = 1.0
        if sentiment is not None:
            sent_conf = float(np.clip(sentiment.confidence, 0, 1))
            relevance_mult = float(np.clip(sentiment.relevance_score, 0, 1))
            risk_mult = float(np.clip(1.0 - (sentiment.event_risk_score * 0.6), 0.2, 1.0))
            contradiction_mult = float(np.clip(1.0 - (sentiment.contradiction_score * 0.7), 0.2, 1.0))
            base_sent = float(np.clip(sentiment.score, -1, 1)) * sent_conf
            regime_mult = float(np.clip(sentiment_regime_multiplier(getattr(sentiment, 'event_regime', 'normal')), 0.1, 1.0))
            if sentiment.action_bias == 'bullish' and base_sent > 0:
                bias_adjust = 0.05
            elif sentiment.action_bias == 'bearish' and base_sent < 0:
                bias_adjust = -0.05
            elif sentiment.action_bias == 'mixed':
                bias_adjust = 0.0
            sent_score = float(np.clip(base_sent * relevance_mult * risk_mult * contradiction_mult * regime_mult + bias_adjust, -1, 1))

        w = self.config.weights
        final_score = (
            trend * w.trend
            + momentum * w.momentum
            + mean_reversion * w.mean_reversion
            + sent_score * w.sentiment
        )
        final_score = float(np.clip(final_score, -1, 1))
        return SignalSnapshot(
            symbol=symbol,
            timestamp=timestamp,
            trend_score=trend,
            momentum_score=momentum,
            mean_reversion_score=mean_reversion,
            sentiment_score=sent_score,
            final_score=final_score,
            regime=regime,
            explanation={
                "rsi": round(rsi, 4),
                "macd_hist": round(macd, 4),
                "bb_zscore": round(bb_z, 4),
                "sentiment_confidence": round(sent_conf, 4),
                "sentiment_relevance": round(relevance_mult, 4),
                "sentiment_risk_multiplier": round(risk_mult, 4),
                "sentiment_contradiction_multiplier": round(contradiction_mult, 4),
                "sentiment_bias_adjust": round(bias_adjust, 4),
                "headline_risk": getattr(sentiment, 'headline_risk', 'low') if sentiment is not None else 'low',
                "action_bias": getattr(sentiment, 'action_bias', 'neutral') if sentiment is not None else 'neutral',
                "event_regime": getattr(sentiment, 'event_regime', 'normal') if sentiment is not None else 'normal',
                "approval_policy": getattr(sentiment, 'approval_policy', 'auto') if sentiment is not None else 'auto',
                "sentiment_regime_multiplier": round(regime_mult, 4),
            },
        )
