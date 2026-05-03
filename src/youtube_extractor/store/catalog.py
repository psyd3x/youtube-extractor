from __future__ import annotations

import json
from pathlib import Path


def append_entry(path: Path, entry: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def read_all(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def find_by_video_id(path: Path, video_id: str) -> dict | None:
    for row in read_all(path):
        if row.get("video_id") == video_id:
            return row
    return None
