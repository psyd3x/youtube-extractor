import json
from pathlib import Path

import pytest

from youtube_extractor.store.atomic import rewrite_ndjson_filtered


def _write_ndjson(p: Path, rows: list[dict]) -> None:
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def _read_ndjson(p: Path) -> list[dict]:
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_rewrite_drops_matching_rows(tmp_path):
    p = tmp_path / "rows.ndjson"
    _write_ndjson(p, [{"id": "a"}, {"id": "b"}, {"id": "a"}])
    removed = rewrite_ndjson_filtered(p, predicate=lambda r: r["id"] != "a")
    assert removed == 2
    assert _read_ndjson(p) == [{"id": "b"}]


def test_rewrite_no_matches_is_noop(tmp_path):
    p = tmp_path / "rows.ndjson"
    _write_ndjson(p, [{"id": "x"}, {"id": "y"}])
    removed = rewrite_ndjson_filtered(p, predicate=lambda r: True)
    assert removed == 0
    assert _read_ndjson(p) == [{"id": "x"}, {"id": "y"}]


def test_rewrite_missing_file_is_noop(tmp_path):
    p = tmp_path / "rows.ndjson"
    removed = rewrite_ndjson_filtered(p, predicate=lambda r: True)
    assert removed == 0
    assert not p.exists()


def test_rewrite_skips_blank_and_corrupt_lines(tmp_path):
    p = tmp_path / "rows.ndjson"
    p.write_text('{"id":"a"}\n\n{not json}\n{"id":"b"}\n', encoding="utf-8")
    removed = rewrite_ndjson_filtered(p, predicate=lambda r: r["id"] != "a")
    # Only the parseable {"id":"a"} row counts as removed; corrupt and blank lines drop.
    assert removed == 1
    assert _read_ndjson(p) == [{"id": "b"}]


def test_rewrite_is_atomic_no_partial_file(tmp_path, monkeypatch):
    """If os.replace fails, original file must be intact and no temp file left behind."""
    p = tmp_path / "rows.ndjson"
    _write_ndjson(p, [{"id": "a"}])

    import os
    real_replace = os.replace

    def boom(src, dst):  # type: ignore[no-untyped-def]
        raise OSError("disk full")

    monkeypatch.setattr("youtube_extractor.store.atomic.os.replace", boom)

    with pytest.raises(OSError):
        rewrite_ndjson_filtered(p, predicate=lambda r: False)

    # Original file unchanged.
    assert _read_ndjson(p) == [{"id": "a"}]
    # No leftover .tmp files in the directory.
    leftovers = [f for f in tmp_path.iterdir() if f.suffix == ".tmp"]
    assert leftovers == []

    # restore
    monkeypatch.setattr("youtube_extractor.store.atomic.os.replace", real_replace)


def test_rewrite_predicate_raises_leaves_original_intact(tmp_path):
    """A predicate that raises must not corrupt the original file or leave a .tmp."""
    p = tmp_path / "rows.ndjson"
    _write_ndjson(p, [{"id": "a"}, {"id": "b"}])

    def boom(row):
        raise RuntimeError("predicate failed")

    with pytest.raises(RuntimeError):
        rewrite_ndjson_filtered(p, predicate=boom)

    # Original intact
    assert _read_ndjson(p) == [{"id": "a"}, {"id": "b"}]
    # No .tmp leftovers
    leftovers = [f for f in tmp_path.iterdir() if f.suffix == ".tmp"]
    assert leftovers == []
