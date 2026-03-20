from __future__ import annotations

from typing import Iterable

BINARY_EVENT_FLAGS = {'earnings', 'guidance_change', 'lawsuit', 'merger_acquisition', 'financing', 'management_change'}
RISK_EVENT_FLAGS = {'lawsuit', 'guidance_change', 'financing', 'management_change'}


def classify_event_regime(*, event_flags: Iterable[str], event_risk_score: float, contradiction_score: float, action_bias: str, headline_risk: str) -> str:
    flags = {str(x) for x in event_flags}
    risk = float(event_risk_score or 0.0)
    contradiction = float(contradiction_score or 0.0)
    bias = str(action_bias or 'neutral')
    headline = str(headline_risk or 'low').lower()
    if contradiction >= 0.72:
        return 'contradictory_tape'
    if risk >= 0.90 or (risk >= 0.82 and flags & BINARY_EVENT_FLAGS):
        return 'binary_event_lockdown'
    if headline == 'high' and risk >= 0.75 and bias == 'bearish':
        return 'risk_off_newsflow'
    if headline == 'high' and risk >= 0.75 and bias == 'bullish':
        return 'event_driven_breakout'
    if risk >= 0.60 and flags & RISK_EVENT_FLAGS:
        return 'headline_fragile'
    if bias == 'bullish' and contradiction <= 0.35 and risk <= 0.45:
        return 'risk_on_supportive'
    if bias == 'bearish' and contradiction <= 0.35 and risk <= 0.55:
        return 'risk_off_supportive'
    return 'normal'


def choose_approval_policy(*, event_regime: str, trading_stance: str, event_risk_score: float, contradiction_score: float, action_bias: str) -> str:
    regime = str(event_regime or 'normal')
    stance = str(trading_stance or 'neutral')
    risk = float(event_risk_score or 0.0)
    contradiction = float(contradiction_score or 0.0)
    bias = str(action_bias or 'neutral')
    if regime == 'binary_event_lockdown' or stance == 'block_new_entries':
        return 'block_new_entries'
    if regime == 'contradictory_tape' or contradiction >= 0.72:
        return 'review_new_entries'
    if regime in {'headline_fragile', 'event_driven_breakout'} or risk >= 0.70:
        return 'review_large_or_risky'
    if bias == 'bearish' or stance == 'favor_short':
        return 'review_shorts'
    return 'auto'


def sentiment_regime_multiplier(regime: str) -> float:
    mapping = {
        'binary_event_lockdown': 0.15,
        'contradictory_tape': 0.35,
        'headline_fragile': 0.55,
        'risk_off_newsflow': 0.75,
        'event_driven_breakout': 0.85,
        'risk_on_supportive': 1.0,
        'risk_off_supportive': 0.9,
        'normal': 0.95,
    }
    return float(mapping.get(str(regime or 'normal'), 0.8))


def daily_report_priority(*, event_regime: str, approval_policy: str, event_risk_score: float, contradiction_score: float) -> str:
    regime = str(event_regime or 'normal')
    policy = str(approval_policy or 'auto')
    risk = float(event_risk_score or 0.0)
    contradiction = float(contradiction_score or 0.0)
    if policy == 'block_new_entries' or regime == 'binary_event_lockdown' or risk >= 0.85:
        return 'critical'
    if policy != 'auto' or contradiction >= 0.6 or regime in {'headline_fragile', 'contradictory_tape', 'event_driven_breakout'}:
        return 'elevated'
    return 'normal'
