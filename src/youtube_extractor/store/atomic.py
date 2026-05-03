from __future__ import annotations

import contextlib
import json
import os
import tempfile
from collections.abc import Callable
from pathlib import Path


def rewrite_ndjson_filtered(path: Path, predicate: Callable[[dict], bool]) -> int:
    """Atomically rewrite an ndjson file keeping only rows where predicate(row) is True.

    Returns the count of parseable rows that were removed (i.e. predicate returned False).
    Blank lines and unparseable lines are silently dropped and do not count toward the
    removed total.

    If the file does not exist, returns 0 and creates nothing.
    Atomicity: writes to a sibling .tmp file, then os.replace -- same-filesystem rename
    is atomic on macOS APFS, ext4, and tmpfs. On any failure the original file is left
    untouched and the temp file is removed.
    """
    if not path.exists():
        return 0

    removed = 0
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as out:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if predicate(row):
                    out.write(json.dumps(row) + "\n")
                else:
                    removed += 1
        os.replace(tmp_path, path)
        return removed
    except Exception:
        if tmp_path.exists():
            with contextlib.suppress(OSError):
                tmp_path.unlink()
        raise
