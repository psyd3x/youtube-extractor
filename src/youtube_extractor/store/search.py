from __future__ import annotations

from pathlib import Path

from .catalog import read_all

_FIELDS = ("title", "channel", "tags", "topics", "people")


def search_entries(path: Path, query: str) -> list[dict]:
    rows = read_all(path)
    q = (query or "").strip().lower()
    if not q:
        return rows
    results: list[dict] = []
    for row in rows:
        haystack_parts: list[str] = []
        for f in _FIELDS:
            v = row.get(f)
            if isinstance(v, str):
                haystack_parts.append(v)
            elif isinstance(v, list):
                haystack_parts.extend(str(x) for x in v)
        haystack = " ".join(haystack_parts).lower()
        if q in haystack:
            results.append(row)
    return results
