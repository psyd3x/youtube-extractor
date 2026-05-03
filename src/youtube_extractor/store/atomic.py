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

    Atomicity is at the visibility level: concurrent readers always see either the old
    or the new file, never a partial. This is NOT crash-durable -- without fsync, a
    power loss between os.replace and the kernel flush can lose both the rewrite and
    the original. Matches the durability story of the rest of this codebase
    (JobStore.put is plain append, no fsync). On any failure before os.replace, the
    original file is left untouched and the temp file is removed.

    Caller must serialize concurrent rewrites of the same path -- two callers racing
    will each create their own temp file and last-writer-wins on os.replace, silently
    dropping one filter's deletions.
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
                    # Write the original line back -- avoids non-ASCII re-encoding
                    # and keeps kept rows byte-identical to what the writer emitted.
                    out.write(line + "\n")
                else:
                    removed += 1
        os.replace(tmp_path, path)
        return removed
    except Exception:
        if tmp_path.exists():
            with contextlib.suppress(OSError):
                tmp_path.unlink()
        raise
