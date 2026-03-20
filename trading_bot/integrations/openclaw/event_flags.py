from __future__ import annotations

from typing import Iterable

EVENT_PATTERNS: dict[str, tuple[str, ...]] = {
    'earnings': ('earnings', 'quarterly results', 'q1', 'q2', 'q3', 'q4', 'eps'),
    'guidance_change': ('guidance', 'outlook', 'forecast', 'reaffirmed', 'cuts forecast', 'raises forecast'),
    'lawsuit': ('lawsuit', 'sued', 'settlement', 'investigation', 'probe', 'sec'),
    'merger_acquisition': ('acquire', 'acquisition', 'merger', 'takeover', 'buyout'),
    'product_launch': ('launch', 'rollout', 'introduces', 'announces new', 'debut'),
    'management_change': ('ceo', 'cfo', 'chairman', 'steps down', 'resigns', 'appointed'),
    'analyst_rating': ('upgrade', 'downgrade', 'price target', 'analyst'),
    'financing': ('offering', 'debt sale', 'share sale', 'capital raise', 'convertible'),
}

HIGH_RISK_FLAGS = {'earnings', 'guidance_change', 'lawsuit', 'merger_acquisition', 'financing', 'management_change'}
EVENT_RISK_WEIGHTS = {
    'earnings': 0.7,
    'guidance_change': 0.9,
    'lawsuit': 0.95,
    'merger_acquisition': 0.8,
    'product_launch': 0.35,
    'management_change': 0.75,
    'analyst_rating': 0.3,
    'financing': 0.85,
}


def detect_event_flags(texts: Iterable[str]) -> list[str]:
    haystack = ' '.join([str(x or '') for x in texts]).lower()
    flags: list[str] = []
    for flag, patterns in EVENT_PATTERNS.items():
        if any(pat in haystack for pat in patterns):
            flags.append(flag)
    return sorted(set(flags))



def classify_headline_risk(flags: Iterable[str], *, avg_confidence: float = 0.0, abs_sentiment: float = 0.0, event_risk_score: float | None = None) -> str:
    flag_set = set(flags)
    risk_score = float(event_risk_score or 0.0)
    if risk_score >= 0.85 or flag_set & HIGH_RISK_FLAGS:
        return 'high'
    if risk_score >= 0.55 or avg_confidence >= 0.75 or abs_sentiment >= 0.40 or flag_set:
        return 'medium'
    return 'low'



def score_event_risk(flags: Iterable[str], *, explicit_event_risk: float | None = None) -> float:
    if explicit_event_risk is not None:
        return max(0.0, min(1.0, float(explicit_event_risk)))
    values = [EVENT_RISK_WEIGHTS.get(flag, 0.25) for flag in flags]
    if not values:
        return 0.0
    return round(max(values), 4)



def classify_action_bias(weighted_score: float, contradiction_score: float) -> str:
    if contradiction_score >= 0.65:
        return 'mixed'
    if weighted_score >= 0.15:
        return 'bullish'
    if weighted_score <= -0.15:
        return 'bearish'
    return 'neutral'
