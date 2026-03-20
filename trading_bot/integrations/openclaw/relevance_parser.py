from __future__ import annotations

from typing import Any


def normalize_symbol(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip().upper()
    return text or None


def alias_candidates(symbol: str, alias_map: dict[str, list[str]] | None = None) -> list[str]:
    aliases = list((alias_map or {}).get(symbol.upper(), []))
    merged = [symbol.upper(), *aliases]
    out: list[str] = []
    seen: set[str] = set()
    for item in merged:
        key = str(item).strip().lower()
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(str(item).strip())
    return out


def infer_relevance(article: dict[str, Any], *, symbol: str, alias_map: dict[str, list[str]] | None = None) -> float:
    explicit = article.get('relevance_score')
    if explicit is not None:
        try:
            return max(0.0, min(1.0, float(explicit)))
        except Exception:
            pass
    aliases = alias_candidates(symbol, alias_map)
    title = str(article.get('title') or '')
    summary = str(article.get('summary') or article.get('body') or '')
    company = str(article.get('company') or '')
    text = f"{title} {summary} {company}".lower()
    hits = sum(1 for alias in aliases if alias.lower() in text)
    if hits >= 2:
        return 0.9
    if hits == 1:
        return 0.7
    return 0.25


def article_is_relevant(article: dict[str, Any], *, symbol: str, min_relevance: float, alias_map: dict[str, list[str]] | None = None) -> bool:
    if bool(article.get('relevant')):
        return True
    return infer_relevance(article, symbol=symbol, alias_map=alias_map) >= min_relevance
