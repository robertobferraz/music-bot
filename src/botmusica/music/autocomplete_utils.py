from __future__ import annotations


def merge_suggestions(
    *,
    query: str,
    history_values: list[str],
    cache_values: list[str],
    limit: int,
) -> list[str]:
    current_lower = query.casefold().strip()
    merged: list[str] = []
    seen: set[str] = set()

    for value in history_values + cache_values:
        normalized = value.strip()
        if not normalized:
            continue
        lower = normalized.casefold()
        if current_lower and current_lower not in lower:
            continue
        if lower in seen:
            continue
        seen.add(lower)
        merged.append(normalized)
        if len(merged) >= limit:
            break
    return merged
