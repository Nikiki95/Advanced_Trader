from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class HeadlineItem:
    title: str
    summary: str
    link: str
    source_url: str


def fetch_headlines(symbol: str, feeds: list[str], limit_per_feed: int = 5) -> list[HeadlineItem]:
    try:
        import feedparser  # type: ignore
    except Exception:
        return []

    headlines: list[HeadlineItem] = []
    seen: set[str] = set()
    for template in feeds:
        url = template.replace('{ticker}', symbol)
        parsed = feedparser.parse(url)
        for entry in parsed.entries[:limit_per_feed]:
            title = str(entry.get('title', '')).strip()
            if not title:
                continue
            key = title.lower()
            if key in seen:
                continue
            seen.add(key)
            headlines.append(
                HeadlineItem(
                    title=title,
                    summary=str(entry.get('summary', '')).strip(),
                    link=str(entry.get('link', '')).strip(),
                    source_url=url,
                )
            )
    return headlines
