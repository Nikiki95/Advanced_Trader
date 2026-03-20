from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo


@dataclass(slots=True)
class SessionSnapshot:
    timezone: str
    now: datetime
    active_session: str | None
    market_open: bool
    reason: str
    watchlist: list[str]


def _parse_minutes(hhmm: str) -> int:
    hour, minute = [int(x) for x in hhmm.split(':', 1)]
    return hour * 60 + minute


def resolve_session(raw_cfg: dict, now: datetime | None = None) -> SessionSnapshot:
    compat = raw_cfg.get('compatibility', {})
    tz_name = compat.get('timezone', 'Europe/Berlin')
    tz = ZoneInfo(tz_name)
    local_now = now.astimezone(tz) if now is not None and now.tzinfo else datetime.now(tz) if now is None else now.replace(tzinfo=tz)
    sessions = compat.get('sessions', {})
    holidays = compat.get('holidays', {})
    if local_now.weekday() >= 5:
        return SessionSnapshot(tz_name, local_now, None, False, 'weekend', [])
    today = local_now.strftime('%Y-%m-%d')
    minutes = local_now.hour * 60 + local_now.minute
    for name, payload in sessions.items():
        start = payload.get('start_cet') or payload.get('start')
        end = payload.get('end_cet') or payload.get('end')
        if not start or not end:
            continue
        if today in holidays.get(name, []):
            continue
        if _parse_minutes(start) <= minutes <= _parse_minutes(end):
            return SessionSnapshot(
                timezone=tz_name,
                now=local_now,
                active_session=name,
                market_open=True,
                reason='within configured trading window',
                watchlist=[str(x).upper() for x in payload.get('watchlist', [])],
            )
    # fallback: nearest by clock to preserve original eu/us split behavior
    if 'eu' in sessions and minutes < _parse_minutes((sessions.get('us') or {}).get('start_cet', '14:00')):
        payload = sessions['eu']
        return SessionSnapshot(tz_name, local_now, 'eu', False, 'outside trading window', [str(x).upper() for x in payload.get('watchlist', [])])
    if 'us' in sessions:
        payload = sessions['us']
        return SessionSnapshot(tz_name, local_now, 'us', False, 'outside trading window', [str(x).upper() for x in payload.get('watchlist', [])])
    return SessionSnapshot(tz_name, local_now, None, False, 'no configured session', [])
