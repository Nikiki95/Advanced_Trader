from __future__ import annotations

from typing import Any

TIERS = ('routine', 'elevated', 'critical', 'blocked')


def tier_rank(value: str | None) -> int:
    order = {'routine': 0, 'elevated': 1, 'critical': 2, 'blocked': 3}
    return order.get(str(value or 'routine').lower(), 0)


def max_tier(*values: str | None) -> str:
    ranked = sorted((str(v or 'routine').lower() for v in values), key=tier_rank)
    return ranked[-1] if ranked else 'routine'


def classify_decision_tier(
    *,
    action_type: str,
    notional: float,
    contract: dict[str, Any] | None,
    session_policy: dict[str, Any] | None = None,
    portfolio_guardrails: dict[str, Any] | None = None,
) -> tuple[str, list[str]]:
    contract = contract or {}
    session_policy = session_policy or {}
    portfolio_guardrails = portfolio_guardrails or {}
    reasons: list[str] = []
    tier = 'routine'

    policy = str(contract.get('approval_policy') or 'auto')
    regime = str(contract.get('event_regime') or 'normal')
    headline_risk = str(contract.get('headline_risk') or 'low')
    event_risk = float(contract.get('event_risk_score') or 0.0)
    contradiction = float(contract.get('contradiction_score') or 0.0)

    if policy == 'block_new_entries' and action_type in {'OPEN_LONG', 'OPEN_SHORT'}:
        return 'blocked', [f'openclaw policy blocks fresh entries under regime {regime}']

    if regime == 'binary_event_lockdown' and action_type in {'OPEN_LONG', 'OPEN_SHORT'}:
        return 'blocked', ['binary event lockdown is active']

    if policy in {'review_new_entries', 'review_shorts', 'review_large_or_risky'}:
        tier = max_tier(tier, 'elevated')
        reasons.append(f'approval policy={policy}')
    if regime in {'headline_fragile', 'contradictory_tape'}:
        tier = max_tier(tier, 'elevated')
        reasons.append(f'event regime={regime}')
    if headline_risk == 'high' or event_risk >= 0.8 or contradiction >= 0.65:
        tier = max_tier(tier, 'critical')
        reasons.append('headline/event risk is elevated')
    if abs(float(notional)) >= 10000:
        tier = max_tier(tier, 'critical')
        reasons.append('large notional request')
    elif abs(float(notional)) >= 5000:
        tier = max_tier(tier, 'elevated')
        reasons.append('medium notional request')

    mode = str(session_policy.get('entry_mode') or 'normal')
    if mode == 'block' and action_type in {'OPEN_LONG', 'OPEN_SHORT'}:
        return 'blocked', [f"session policy blocks fresh entries during {session_policy.get('session_name') or 'current session'}"]
    if mode == 'review' and action_type in {'OPEN_LONG', 'OPEN_SHORT'}:
        tier = max_tier(tier, 'elevated')
        reasons.append(f"session policy requires review during {session_policy.get('session_name') or 'current session'}")
    floor = str(session_policy.get('approval_tier_floor') or 'routine')
    if floor in TIERS:
        tier = max_tier(tier, floor)
        if floor != 'routine':
            reasons.append(f'session tier floor={floor}')

    directives = set((portfolio_guardrails or {}).get('directives') or [])
    if 'freeze_new_entries' in directives and action_type in {'OPEN_LONG', 'OPEN_SHORT'}:
        return 'blocked', ['portfolio guardrail freezes fresh entries']
    if 'review_all_new_entries' in directives and action_type in {'OPEN_LONG', 'OPEN_SHORT'}:
        tier = max_tier(tier, 'critical')
        reasons.append('portfolio guardrail requires review for all new entries')
    if 'review_all_shorts' in directives and action_type == 'OPEN_SHORT':
        tier = max_tier(tier, 'critical')
        reasons.append('portfolio guardrail requires review for all shorts')
    if 'reduce_size' in directives:
        tier = max_tier(tier, 'elevated')
        reasons.append('portfolio guardrail suggests reduced size')
    if 'operator_only' in directives:
        tier = max_tier(tier, 'critical')
        reasons.append('operator-only mode is active')

    return tier, reasons
