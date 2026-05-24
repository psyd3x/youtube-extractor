#!/usr/bin/env python3
"""Safely trim entries from output/jobs.ndjson (the job recovery log).

Always writes a timestamped backup it NEVER deletes, so a trim can always be
undone. By default it drops every row belonging to a job whose final status is
``failed`` (the usual "clear out dead jobs" case) and keeps everything else.

Usage:
    python scripts/trim_jobs.py --dry-run            # show what would change
    python scripts/trim_jobs.py                      # trim failed jobs (default)
    python scripts/trim_jobs.py --status failed queued   # trim multiple statuses
    python scripts/trim_jobs.py --path /custom/jobs.ndjson

Restore:
    cp output/jobs.ndjson.bak.<timestamp> output/jobs.ndjson
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

DEFAULT_PATH = Path(__file__).resolve().parent.parent / "output" / "jobs.ndjson"


def main() -> int:
    ap = argparse.ArgumentParser(description="Safely trim jobs.ndjson with a kept backup.")
    ap.add_argument("--path", type=Path, default=DEFAULT_PATH, help="jobs.ndjson path")
    ap.add_argument(
        "--status",
        nargs="+",
        default=["failed"],
        help="drop jobs whose FINAL status is one of these (default: failed)",
    )
    ap.add_argument("--dry-run", action="store_true", help="report only; write nothing")
    args = ap.parse_args()

    path: Path = args.path
    drop_statuses = set(args.status)

    if not path.exists():
        print(f"nothing to do: {path} does not exist")
        return 0

    rows: list[tuple[str, dict]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                rows.append((line, json.loads(line)))
            except json.JSONDecodeError:
                rows.append((line, {}))  # preserve unparseable lines verbatim

    final: dict[str, str | None] = {}
    for _line, rec in rows:
        jid = rec.get("id")
        if jid:
            final[jid] = rec.get("status")

    drop_ids = {jid for jid, st in final.items() if st in drop_statuses}
    kept = [line for line, rec in rows if rec.get("id") not in drop_ids]

    print(f"path:           {path}")
    print(f"rows:           {len(rows)}  jobs: {len(final)}")
    print(f"drop statuses:  {sorted(drop_statuses)}")
    print(f"jobs dropped:   {len(drop_ids)}  rows removed: {len(rows) - len(kept)}")
    print(f"jobs kept:      {len(final) - len(drop_ids)}  rows kept: {len(kept)}")

    if args.dry_run:
        print("dry-run: no changes written")
        return 0

    if not drop_ids:
        print("no matching jobs; leaving file untouched")
        return 0

    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = path.with_suffix(path.suffix + f".bak.{stamp}")
    shutil.copy2(path, backup)
    path.write_text(("\n".join(kept) + "\n") if kept else "", encoding="utf-8")
    print(f"backup kept at: {backup}")
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
