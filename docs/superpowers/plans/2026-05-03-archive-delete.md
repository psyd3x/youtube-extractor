---
title: Archive Delete — Implementation Plan
project: youtube-extractor
type: implementation-plan
status: ready
date: 2026-05-03
tags: [youtube-extractor, archive, delete, plan, mission-control]
description: Step-by-step implementation plan for the hard-delete feature. Five backend tasks (atomic ndjson rewriter, JobStore.remove_by_slug, delete_by_slug module, DELETE /archive/{slug} route, integration tests), four frontend tasks (MC proxy, useArmedAction hook, ArchiveList button, page handler), and one smoke + push task.
---

# Archive Delete Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hard-delete an archive entry from the YouTube Extractor: catalog row + `.md` in the Obsidian vault + both PDFs + every `jobs.ndjson` row tied to the same slug — exposed as `DELETE /archive/{slug}` on the extractor and a per-row two-click control in the Mission Control `/youtube` tab.

**Architecture:** Backend gets a new pure module `store/delete.py` orchestrating the deletes, a new shared atomic-rewrite helper `store/atomic.py`, and a new method `JobStore.remove_by_slug`. The FastAPI archive router gains a `DELETE /archive/{slug}` route that injects the live `JobStore` singleton from `api/jobs.py`. Mission Control gets a pass-through proxy and a small inline two-click confirm button on each `ArchiveList` row, backed by a reusable `useArmedAction` hook.

**Tech Stack:** Python 3.11, FastAPI, pytest, pydantic v2 — Next.js 14 App Router, React 18, TypeScript strict.

**Spec:** `docs/superpowers/specs/2026-05-03-archive-delete-design.md`

---

## File Structure

| Repo | Path | Action | Responsibility |
|---|---|---|---|
| youtube-extractor | `src/youtube_extractor/store/atomic.py` | Create | Shared atomic ndjson rewrite helper |
| youtube-extractor | `src/youtube_extractor/store/jobs.py` | Modify | Add `JobStore.remove_by_slug` |
| youtube-extractor | `src/youtube_extractor/store/delete.py` | Create | Orchestrate full archive-entry delete |
| youtube-extractor | `src/youtube_extractor/api/archive.py` | Modify | Wire `DELETE /archive/{slug}` route |
| youtube-extractor | `tests/test_atomic.py` | Create | Tests for the rewrite helper |
| youtube-extractor | `tests/test_store.py` | Modify | Add `remove_by_slug` test |
| youtube-extractor | `tests/test_delete.py` | Create | Tests for `delete_by_slug` |
| youtube-extractor | `tests/test_api_archive.py` | Modify | Add API integration tests for DELETE |
| youtube-extractor | `docs/manual-test-log.md` | Modify | Append smoke entry |
| mission-control | `src/app/api/youtube/archive/[slug]/route.ts` | Create | Pass-through DELETE proxy |
| mission-control | `src/app/youtube/_components/useArmedAction.ts` | Create | Two-click confirm hook |
| mission-control | `src/app/youtube/_components/ArchiveList.tsx` | Modify | Add delete button + onDelete prop |
| mission-control | `src/app/youtube/page.tsx` | Modify | onDelete handler + deleteError state |

---

## Wave A — Backend (TDD)

### Task 1: Atomic ndjson rewrite helper

**Files:**
- Create: `src/youtube_extractor/store/atomic.py`
- Create: `tests/test_atomic.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_atomic.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd ~/Youtube-extractor
source .venv/bin/activate
pytest tests/test_atomic.py -v
```

Expected: all five fail with `ModuleNotFoundError: No module named 'youtube_extractor.store.atomic'`.

- [ ] **Step 3: Implement the helper**

```python
# src/youtube_extractor/store/atomic.py
from __future__ import annotations

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
    Atomicity: writes to a sibling .tmp file, then os.replace — same-filesystem rename
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
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_atomic.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add src/youtube_extractor/store/atomic.py tests/test_atomic.py
git commit -m "feat(store): atomic ndjson rewrite helper with row predicate"
```

---

### Task 2: `JobStore.remove_by_slug`

**Files:**
- Modify: `src/youtube_extractor/store/jobs.py`
- Modify: `tests/test_store.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_store.py`:

```python
def test_jobstore_remove_by_slug(tmp_path):
    from youtube_extractor.store.jobs import JobStore

    store = JobStore(tmp_path / "jobs.ndjson")
    j1 = JobRecord(id="j1", url="u1", status=JobStatus.queued)
    store.put(j1)
    j1.status = JobStatus.running
    j1.slug = "slug-A"
    store.put(j1)
    j1.status = JobStatus.done
    store.put(j1)

    j2 = JobRecord(id="j2", url="u2", status=JobStatus.done, slug="slug-B")
    store.put(j2)

    j3 = JobRecord(id="j3", url="u3", status=JobStatus.failed)  # no slug
    store.put(j3)

    removed = store.remove_by_slug("slug-A")
    assert removed == ["j1"]

    # In-memory state expunged
    assert store.get("j1") is None
    assert store.get("j2") is not None
    assert store.get("j3") is not None

    # File rewritten — no rows for j1 remain even though one of its rows had slug=null
    lines = (tmp_path / "jobs.ndjson").read_text().strip().splitlines()
    assert all('"j1"' not in line for line in lines)
    assert any('"j2"' in line for line in lines)
    assert any('"j3"' in line for line in lines)


def test_jobstore_remove_by_slug_no_match(tmp_path):
    from youtube_extractor.store.jobs import JobStore

    store = JobStore(tmp_path / "jobs.ndjson")
    store.put(JobRecord(id="j1", url="u1", status=JobStatus.done, slug="slug-X"))

    removed = store.remove_by_slug("slug-Z")
    assert removed == []
    assert store.get("j1") is not None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_store.py::test_jobstore_remove_by_slug tests/test_store.py::test_jobstore_remove_by_slug_no_match -v
```

Expected: both fail with `AttributeError: 'JobStore' object has no attribute 'remove_by_slug'`.

- [ ] **Step 3: Implement the method**

In `src/youtube_extractor/store/jobs.py` — add at the top of the file:

```python
from youtube_extractor.store.atomic import rewrite_ndjson_filtered
```

And append this method to the `JobStore` class (inside the class body, after `get`):

```python
    def remove_by_slug(self, slug: str) -> list[str]:
        """Remove every job whose latest state has the given slug.

        Drops the job from in-memory state AND rewrites the file to remove every
        row for those job ids (regardless of slug — covers earlier rows where slug
        may have been null). Returns the list of removed job ids.
        """
        with self._lock:
            ids_to_remove = [jid for jid, rec in self._mem.items() if rec.slug == slug]
            if not ids_to_remove:
                return []
            ids_set = set(ids_to_remove)
            rewrite_ndjson_filtered(self.path, predicate=lambda row: row.get("id") not in ids_set)
            for jid in ids_to_remove:
                self._mem.pop(jid, None)
            return ids_to_remove
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_store.py -v
```

Expected: existing 4 + new 2 = 6 passed.

- [ ] **Step 5: Commit**

```bash
git add src/youtube_extractor/store/jobs.py tests/test_store.py
git commit -m "feat(store): JobStore.remove_by_slug — drop in-memory + rewrite file"
```

---

### Task 3: `delete_by_slug` module

**Files:**
- Create: `src/youtube_extractor/store/delete.py`
- Create: `tests/test_delete.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_delete.py
import pytest

from youtube_extractor.config import settings
from youtube_extractor.models import JobRecord, JobStatus
from youtube_extractor.store.catalog import append_entry
from youtube_extractor.store.delete import (
    ArchiveEntryNotFound,
    DeleteResult,
    delete_by_slug,
)
from youtube_extractor.store.jobs import JobStore


def _setup(tmp_path, monkeypatch):
    """Point settings into tmp_path and return (vault, output_dir, jobs_store)."""
    vault = tmp_path / "vault"
    output = tmp_path / "output"
    vault.mkdir()
    output.mkdir()
    monkeypatch.setattr(settings, "obsidian_vault_path", vault)
    monkeypatch.setattr(settings, "output_dir", output)
    jobs_store = JobStore(output / "jobs.ndjson")
    return vault, output, jobs_store


def _seed_archive_row(catalog, vault, output, *, slug="2024-aaa-foo"):
    md = vault / f"{slug}.md"
    md.write_text("# md", encoding="utf-8")
    pdf_full = output / f"{slug}-full.pdf"
    pdf_full.write_bytes(b"%PDF-1.7 full")
    pdf_lazy = output / f"{slug}-lazy.pdf"
    pdf_lazy.write_bytes(b"%PDF-1.7 lazy")
    append_entry(
        catalog,
        {
            "slug": slug,
            "video_id": "aaa",
            "title": "Foo",
            "channel": "C",
            "url": "https://y/watch?v=aaa",
            "duration": 100,
            "extracted_at": 1.0,
            "md_path": str(md),
            "pdf_full_path": str(pdf_full),
            "pdf_lazy_path": str(pdf_lazy),
            "tags": [],
            "topics": [],
            "people": [],
        },
    )
    return md, pdf_full, pdf_lazy


def test_delete_happy_path(tmp_path, monkeypatch):
    vault, output, jobs = _setup(tmp_path, monkeypatch)
    catalog = output / "catalog.ndjson"
    md, pdf_full, pdf_lazy = _seed_archive_row(catalog, vault, output, slug="slug-A")

    # Two jobs tied to slug-A, one to slug-B
    j1 = JobRecord(id="j1", url="u", status=JobStatus.done, slug="slug-A")
    j2 = JobRecord(id="j2", url="u2", status=JobStatus.done, slug="slug-A")
    j3 = JobRecord(id="j3", url="u3", status=JobStatus.done, slug="slug-B")
    jobs.put(j1); jobs.put(j2); jobs.put(j3)

    result = delete_by_slug(settings, "slug-A", jobs)

    assert isinstance(result, DeleteResult)
    assert result.slug == "slug-A"
    assert result.md is True
    assert result.pdf_full is True
    assert result.pdf_lazy is True
    assert result.catalog_row is True
    assert result.jobs_removed == 2

    # Files gone
    assert not md.exists()
    assert not pdf_full.exists()
    assert not pdf_lazy.exists()

    # Catalog rewritten with no slug-A row
    rows = catalog.read_text(encoding="utf-8").splitlines()
    assert all('"slug-A"' not in line for line in rows)

    # Other job survives
    assert jobs.get("j3") is not None
    assert jobs.get("j1") is None
    assert jobs.get("j2") is None


def test_delete_missing_slug_raises(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    with pytest.raises(ArchiveEntryNotFound):
        delete_by_slug(settings, "does-not-exist", JobStore(tmp_path / "no.ndjson"))


def test_delete_artifact_files_already_missing(tmp_path, monkeypatch):
    vault, output, jobs = _setup(tmp_path, monkeypatch)
    catalog = output / "catalog.ndjson"
    md, pdf_full, pdf_lazy = _seed_archive_row(catalog, vault, output, slug="slug-A")
    md.unlink()  # md gone but catalog row references it

    result = delete_by_slug(settings, "slug-A", jobs)

    assert result.md is False
    assert result.pdf_full is True
    assert result.pdf_lazy is True
    assert result.catalog_row is True
    assert result.jobs_removed == 0
    # PDFs still got removed
    assert not pdf_full.exists()
    assert not pdf_lazy.exists()


def test_delete_atomic_rewrite_preserves_other_rows(tmp_path, monkeypatch):
    vault, output, jobs = _setup(tmp_path, monkeypatch)
    catalog = output / "catalog.ndjson"
    _seed_archive_row(catalog, vault, output, slug="slug-A")
    _seed_archive_row(catalog, vault, output, slug="slug-B")
    _seed_archive_row(catalog, vault, output, slug="slug-C")

    delete_by_slug(settings, "slug-B", jobs)

    text = catalog.read_text(encoding="utf-8")
    assert '"slug-A"' in text
    assert '"slug-B"' not in text
    assert '"slug-C"' in text
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_delete.py -v
```

Expected: all four fail with `ModuleNotFoundError: No module named 'youtube_extractor.store.delete'`.

- [ ] **Step 3: Implement the module**

```python
# src/youtube_extractor/store/delete.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from youtube_extractor.store.atomic import rewrite_ndjson_filtered
from youtube_extractor.store.catalog import find_by_video_id, read_all
from youtube_extractor.store.jobs import JobStore


class ArchiveEntryNotFound(Exception):
    """Raised when delete_by_slug is called with a slug not in the catalog."""


@dataclass
class DeleteResult:
    slug: str
    md: bool
    pdf_full: bool
    pdf_lazy: bool
    catalog_row: bool
    jobs_removed: int


def _find_by_slug(catalog: Path, slug: str) -> dict | None:
    for row in read_all(catalog):
        if row.get("slug") == slug:
            return row
    return None


def _unlink_if_present(p: Path) -> bool:
    """Return True if the file existed and was removed, False if it was already gone."""
    try:
        p.unlink()
        return True
    except FileNotFoundError:
        return False


def delete_by_slug(settings, slug: str, jobs: JobStore) -> DeleteResult:
    """Hard-delete every artifact tied to ``slug``: the .md in the Obsidian vault,
    both PDFs in the output dir, the catalog row, and every jobs.ndjson entry whose
    latest state has the same slug. Returns a per-step report.

    Raises ``ArchiveEntryNotFound`` if the slug is not in the catalog. Anything else
    (disk full, permission denied during rewrite) propagates.
    """
    catalog = settings.output_dir / "catalog.ndjson"

    row = _find_by_slug(catalog, slug)
    if row is None:
        raise ArchiveEntryNotFound(slug)

    md_removed = _unlink_if_present(Path(row["md_path"]))
    pdf_full_removed = _unlink_if_present(Path(row["pdf_full_path"]))
    pdf_lazy_removed = _unlink_if_present(Path(row["pdf_lazy_path"]))

    catalog_removed = rewrite_ndjson_filtered(catalog, predicate=lambda r: r.get("slug") != slug)
    jobs_removed_ids = jobs.remove_by_slug(slug)

    return DeleteResult(
        slug=slug,
        md=md_removed,
        pdf_full=pdf_full_removed,
        pdf_lazy=pdf_lazy_removed,
        catalog_row=catalog_removed > 0,
        jobs_removed=len(jobs_removed_ids),
    )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_delete.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add src/youtube_extractor/store/delete.py tests/test_delete.py
git commit -m "feat(store): delete_by_slug — hard-delete catalog row, .md, PDFs, jobs"
```

---

### Task 4: `DELETE /archive/{slug}` route

**Files:**
- Modify: `src/youtube_extractor/api/archive.py`
- Modify: `tests/test_api_archive.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_api_archive.py`:

```python
def test_archive_delete_happy_path(tmp_path, monkeypatch):
    from youtube_extractor.models import JobRecord, JobStatus
    from youtube_extractor.api import jobs as jobs_module

    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setattr(settings, "output_dir", tmp_path)
    monkeypatch.setattr(settings, "obsidian_vault_path", vault)

    # Swap the API's jobs singleton to point at tmp.
    from youtube_extractor.store.jobs import JobStore
    fresh_jobs = JobStore(tmp_path / "jobs.ndjson")
    monkeypatch.setattr(jobs_module, "_jobs", fresh_jobs)

    # Seed catalog + artifacts + a matching job.
    md = vault / "slug-A.md"
    md.write_text("# md", encoding="utf-8")
    pdf_full = tmp_path / "slug-A-full.pdf"
    pdf_full.write_bytes(b"%PDF-1.7")
    pdf_lazy = tmp_path / "slug-A-lazy.pdf"
    pdf_lazy.write_bytes(b"%PDF-1.7")
    append_entry(
        tmp_path / "catalog.ndjson",
        {
            "slug": "slug-A", "video_id": "v", "title": "T", "channel": "C",
            "url": "https://y/watch?v=v", "duration": 1, "extracted_at": 1.0,
            "md_path": str(md), "pdf_full_path": str(pdf_full), "pdf_lazy_path": str(pdf_lazy),
            "tags": [], "topics": [], "people": [],
        },
    )
    fresh_jobs.put(JobRecord(id="j1", url="u", status=JobStatus.done, slug="slug-A"))

    app = create_app()
    client = TestClient(app)
    r = client.delete("/archive/slug-A")

    assert r.status_code == 200
    body = r.json()
    assert body["slug"] == "slug-A"
    assert body["md"] is True
    assert body["pdf_full"] is True
    assert body["pdf_lazy"] is True
    assert body["catalog_row"] is True
    assert body["jobs_removed"] == 1

    assert not md.exists()
    assert not pdf_full.exists()
    assert not pdf_lazy.exists()
    # Archive list reflects the deletion
    assert client.get("/archive").json() == []


def test_archive_delete_unknown_slug_returns_404(tmp_path, monkeypatch):
    from youtube_extractor.api import jobs as jobs_module
    from youtube_extractor.store.jobs import JobStore

    monkeypatch.setattr(settings, "output_dir", tmp_path)
    monkeypatch.setattr(settings, "obsidian_vault_path", tmp_path / "vault")
    monkeypatch.setattr(jobs_module, "_jobs", JobStore(tmp_path / "jobs.ndjson"))

    app = create_app()
    client = TestClient(app)
    r = client.delete("/archive/nope")
    assert r.status_code == 404
    assert "nope" in r.json()["detail"]
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_api_archive.py::test_archive_delete_happy_path tests/test_api_archive.py::test_archive_delete_unknown_slug_returns_404 -v
```

Expected: both fail with 405 Method Not Allowed (the route doesn't exist yet).

- [ ] **Step 3: Implement the route**

Replace the contents of `src/youtube_extractor/api/archive.py` with:

```python
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, HTTPException

from youtube_extractor.config import settings
from youtube_extractor.store.delete import ArchiveEntryNotFound, delete_by_slug
from youtube_extractor.store.search import search_entries

router = APIRouter()


@router.get("/archive")
async def archive(q: str = "") -> list[dict]:
    catalog = settings.output_dir / "catalog.ndjson"
    return search_entries(catalog, q)


@router.delete("/archive/{slug}")
async def delete_archive(slug: str) -> dict:
    # Late import so monkeypatching api.jobs._jobs in tests works.
    from youtube_extractor.api import jobs as jobs_module

    try:
        result = delete_by_slug(settings, slug, jobs_module._jobs)
    except ArchiveEntryNotFound:
        raise HTTPException(status_code=404, detail=f"slug not found: {slug}")
    return asdict(result)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_api_archive.py -v
```

Expected: existing 5 + new 2 = 7 passed.

- [ ] **Step 5: Run the full backend suite**

```bash
pytest -q
ruff check src tests
```

Expected: all green, no lint errors.

- [ ] **Step 6: Commit**

```bash
git add src/youtube_extractor/api/archive.py tests/test_api_archive.py
git commit -m "feat(api): DELETE /archive/{slug} — hard-delete entry + tied jobs"
```

---

## Wave B — Mission Control proxy + UI

### Task 5: MC proxy DELETE route

**Files:**
- Create: `~/OpenDeeDee/mission-control/src/app/api/youtube/archive/[slug]/route.ts`

- [ ] **Step 1: Write the proxy**

```typescript
// src/app/api/youtube/archive/[slug]/route.ts
import { NextResponse } from 'next/server'
import { ytFetch, ytErrorResponse } from '@/lib/youtube-extractor'

export const dynamic = 'force-dynamic'

export async function DELETE(_req: Request, { params }: { params: { slug: string } }) {
  try {
    const r = await ytFetch(`/archive/${encodeURIComponent(params.slug)}`, { method: 'DELETE' })
    const data = await r.json().catch(() => ({}))
    return NextResponse.json(data, { status: r.status })
  } catch (err) {
    return ytErrorResponse(err)
  }
}
```

- [ ] **Step 2: Verify it compiles in the existing build**

```bash
cd ~/OpenDeeDee/mission-control
npx tsc --noEmit 2>&1 | grep -E "youtube" | head
```

Expected: no errors related to youtube paths.

- [ ] **Step 3: Commit**

```bash
git add src/app/api/youtube/archive/\[slug\]/route.ts
git commit -m "feat(youtube): DELETE proxy for /api/youtube/archive/[slug]"
```

---

### Task 6: `useArmedAction` hook

**Files:**
- Create: `~/OpenDeeDee/mission-control/src/app/youtube/_components/useArmedAction.ts`

- [ ] **Step 1: Write the hook**

```typescript
// src/app/youtube/_components/useArmedAction.ts
import { useEffect, useRef, useState } from 'react'

/**
 * Two-click confirm pattern. First call to `arm()` sets `armed=true` and starts
 * a timer that auto-disarms after `timeoutMs`. Caller decides what to render in
 * each state. `setBusy(true)` while the actual action runs.
 */
export function useArmedAction(timeoutMs = 3000) {
  const [armed, setArmed] = useState(false)
  const [busy, setBusy] = useState(false)
  const tRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  function clearTimer() {
    if (tRef.current) {
      clearTimeout(tRef.current)
      tRef.current = null
    }
  }

  function arm() {
    setArmed(true)
    clearTimer()
    tRef.current = setTimeout(() => setArmed(false), timeoutMs)
  }

  function disarm() {
    setArmed(false)
    clearTimer()
  }

  useEffect(() => () => clearTimer(), [])

  return { armed, busy, setBusy, arm, disarm }
}
```

- [ ] **Step 2: Verify it compiles**

```bash
cd ~/OpenDeeDee/mission-control
npx tsc --noEmit 2>&1 | grep -E "youtube" | head
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add src/app/youtube/_components/useArmedAction.ts
git commit -m "feat(youtube): useArmedAction hook for two-click confirm UI"
```

---

### Task 7: ArchiveList row delete button

**Files:**
- Modify: `~/OpenDeeDee/mission-control/src/app/youtube/_components/ArchiveList.tsx`

- [ ] **Step 1: Replace the file with the version that takes onDelete and renders a delete button**

Full replacement contents:

```typescript
'use client'
import type { CatalogRow } from '../types'
import { useArmedAction } from './useArmedAction'

const isMacUA = (typeof navigator !== 'undefined' && /Macintosh/.test(navigator.userAgent))

export function ArchiveList({
  rows,
  onDelete,
}: {
  rows: CatalogRow[]
  onDelete: (slug: string) => Promise<void>
}) {
  if (rows.length === 0) {
    return <div style={{ padding: 20, color: '#6b6b98', fontSize: 12 }}>Nothing in the archive yet — paste a YouTube URL above.</div>
  }
  return (
    <div style={{ background: '#08090e', border: '1px solid #1a1a30', borderRadius: 8 }}>
      {rows.map((r, i) => (
        <RowItem key={r.slug} row={r} last={i === rows.length - 1} onDelete={onDelete} />
      ))}
    </div>
  )
}

function RowItem({
  row,
  last,
  onDelete,
}: {
  row: CatalogRow
  last: boolean
  onDelete: (slug: string) => Promise<void>
}) {
  const min = Math.round(row.duration / 60)
  const date = new Date(row.extracted_at * 1000).toISOString().slice(0, 10)
  const obsidianUrl = `obsidian://open?file=${encodeURIComponent(row.slug)}`
  const { armed, busy, setBusy, arm, disarm } = useArmedAction(3000)

  async function handleClick() {
    if (busy) return
    if (!armed) {
      arm()
      return
    }
    setBusy(true)
    disarm()
    try {
      await onDelete(row.slug)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{ display: 'flex', gap: 14, padding: '12px 14px', borderBottom: last ? 'none' : '1px solid #1a1a30' }}>
      <div style={{ width: 120, height: 68, background: '#1a1a30', borderRadius: 4, flexShrink: 0 }} />
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: '#e0e0f8', marginBottom: 2 }}>{row.title}</div>
        <div style={{ fontSize: 11, color: '#6b6b98', marginBottom: 6 }}>
          {row.channel} · {min}m · extracted {date}
          {row.topics.length ? ` · tags: ${row.topics.slice(0, 3).join(', ')}` : ''}
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          {isMacUA ? (
            <a href={obsidianUrl} style={btnPrimary}>Open .md in Obsidian</a>
          ) : (
            <a href={`/api/youtube/files/${row.slug}/md`} target="_blank" rel="noreferrer" style={btnPrimary}>View .md</a>
          )}
          <a href={`/api/youtube/files/${row.slug}/full`} target="_blank" rel="noreferrer" style={btnSecondary}>PDF FULL</a>
          <a href={`/api/youtube/files/${row.slug}/lazy`} target="_blank" rel="noreferrer" style={btnSecondary}>PDF LAZY</a>
          <span style={{ flex: 1 }} />
          <button
            type="button"
            onClick={handleClick}
            disabled={busy}
            title={armed ? 'Click again to permanently delete' : 'Delete entry + .md + PDFs'}
            style={armed ? btnDeleteArmed : btnDeleteIdle}
          >
            {busy ? '…' : armed ? '✗ Confirm delete' : '🗑'}
          </button>
        </div>
      </div>
    </div>
  )
}

const btnPrimary: React.CSSProperties = { background: '#6366f1', color: 'white', padding: '4px 10px', borderRadius: 4, fontSize: 11, fontWeight: 500, textDecoration: 'none' }
const btnSecondary: React.CSSProperties = { background: 'transparent', border: '1px solid #1a1a30', color: '#a0a0c8', padding: '4px 10px', borderRadius: 4, fontSize: 11, textDecoration: 'none' }
const btnDeleteIdle: React.CSSProperties = { background: 'transparent', border: '1px solid #1a1a30', color: '#6b6b98', padding: '4px 8px', borderRadius: 4, fontSize: 12, cursor: 'pointer' }
const btnDeleteArmed: React.CSSProperties = { background: '#ef4444', border: '1px solid #ef4444', color: 'white', padding: '4px 10px', borderRadius: 4, fontSize: 11, fontWeight: 600, cursor: 'pointer' }
```

- [ ] **Step 2: Verify it compiles** (will fail until Task 8 wires the prop)

```bash
cd ~/OpenDeeDee/mission-control
npx tsc --noEmit 2>&1 | grep -E "youtube" | head -5
```

Expected: one error in `page.tsx` complaining that `<ArchiveList />` is missing the `onDelete` prop. That's fine — Task 8 fixes it.

- [ ] **Step 3: Commit**

```bash
git add src/app/youtube/_components/ArchiveList.tsx
git commit -m "feat(youtube): per-row two-click delete control on ArchiveList"
```

---

### Task 8: page.tsx onDelete handler + deleteError state

**Files:**
- Modify: `~/OpenDeeDee/mission-control/src/app/youtube/page.tsx`

- [ ] **Step 1: Replace the file with the version that wires onDelete**

Full replacement contents:

```typescript
'use client'
import { useEffect, useState } from 'react'
import { PasteForm } from './_components/PasteForm'
import { ActiveJobs } from './_components/ActiveJobs'
import { ArchiveList } from './_components/ArchiveList'
import { SearchBox } from './_components/SearchBox'
import type { CatalogRow, JobView } from './types'

export default function YouTubePage() {
  const [archive, setArchive] = useState<CatalogRow[]>([])
  const [activeJobs, setActiveJobs] = useState<JobView[]>([])
  const [query, setQuery] = useState('')
  const [deleteError, setDeleteError] = useState<string | null>(null)

  async function refreshArchive(q = '') {
    const url = q ? `/api/youtube/archive?q=${encodeURIComponent(q)}` : '/api/youtube/archive'
    const r = await fetch(url, { cache: 'no-store' })
    if (r.ok) setArchive(await r.json())
  }

  useEffect(() => { refreshArchive() }, [])

  // Auto-clear delete error after 8 seconds.
  useEffect(() => {
    if (!deleteError) return
    const t = setTimeout(() => setDeleteError(null), 8000)
    return () => clearTimeout(t)
  }, [deleteError])

  // Poll active jobs
  useEffect(() => {
    if (activeJobs.length === 0) return
    const id = setInterval(async () => {
      const updated: JobView[] = []
      let anyDone = false
      for (const j of activeJobs) {
        const jid = j.job_id ?? j.id
        if (!jid) continue
        const r = await fetch(`/api/youtube/jobs/${jid}`, { cache: 'no-store' })
        if (r.ok) {
          const view = await r.json() as JobView
          if (view.status === 'done' || view.status === 'failed') anyDone = true
          updated.push(view)
        } else {
          updated.push(j)
        }
      }
      setActiveJobs(updated)
      if (anyDone) refreshArchive(query)
    }, 2000)
    return () => clearInterval(id)
  }, [activeJobs.length, query])

  async function onSubmit(url: string) {
    const r = await fetch('/api/youtube/jobs', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    })
    if (r.ok) {
      const j = await r.json() as JobView
      setActiveJobs(prev => [...prev, j])
    }
  }

  async function onDelete(slug: string) {
    // Optimistic remove
    setArchive(prev => prev.filter(r => r.slug !== slug))
    try {
      const r = await fetch(`/api/youtube/archive/${encodeURIComponent(slug)}`, { method: 'DELETE' })
      if (!r.ok) {
        setDeleteError(`Delete failed (${r.status}). Refreshing.`)
      } else {
        setDeleteError(null)
      }
    } catch (e) {
      setDeleteError(`Network error: ${(e as Error).message}`)
    } finally {
      // Reconcile with server in either case.
      await refreshArchive(query)
    }
  }

  return (
    <div style={{ padding: 20 }}>
      <header style={{ marginBottom: 14 }}>
        <h1 style={{ margin: 0, fontSize: 18, fontWeight: 700 }}>YouTube Extractor</h1>
        <p style={{ margin: '4px 0 0', fontSize: 12, color: '#a0a0c8' }}>
          Paste a video link — get .md in Obsidian + 2 PDFs (FULL + LAZY)
        </p>
      </header>

      <PasteForm onSubmit={onSubmit} />
      <ActiveJobs jobs={activeJobs} />
      {deleteError && (
        <div style={{ marginBottom: 12, padding: '8px 12px', background: '#3f1d1d', border: '1px solid #ef4444', borderRadius: 6, color: '#fca5a5', fontSize: 12 }}>
          {deleteError}
        </div>
      )}
      <SearchBox value={query} onChange={(q) => { setQuery(q); refreshArchive(q) }} count={archive.length} />
      <ArchiveList rows={archive} onDelete={onDelete} />
    </div>
  )
}
```

- [ ] **Step 2: Verify the build is clean**

```bash
cd ~/OpenDeeDee/mission-control
npm run build 2>&1 | tail -10
```

Expected: build succeeds, `/youtube` route listed in the output.

- [ ] **Step 3: Restart MC**

```bash
launchctl stop com.deedee.dashboard && launchctl start com.deedee.dashboard
```

- [ ] **Step 4: Smoke probe** (do not sleep — issue the curl directly; if it 000s, retry once)

```bash
curl -sm 10 -o /dev/null -w "/youtube → %{http_code}\n" http://localhost:3000/youtube
```

Expected: 200.

- [ ] **Step 5: Commit**

```bash
git add src/app/youtube/page.tsx
git commit -m "feat(youtube): wire onDelete handler + inline error banner"
```

---

## Wave C — End-to-end smoke + finalize

### Task 9: Manual E2E smoke + log entry

**Files:**
- Modify: `~/Youtube-extractor/docs/manual-test-log.md`

- [ ] **Step 1: Pre-flight — confirm both services healthy and the launchd extractor is current**

```bash
curl -s http://127.0.0.1:18765/health | python3 -m json.tool
launchctl list | grep -E "youtube-extractor|dashboard"
```

Expected: extractor `status: ok`, both launchd statuses 0 (or first column = a positive PID and the second column an exit code from the previous instance — what matters is the first column being a PID).

If the extractor service is running pre-Task-4 code (no DELETE route), restart it after the backend lands:

```bash
launchctl stop com.deedee.youtube-extractor && launchctl start com.deedee.youtube-extractor
```

- [ ] **Step 2: Identify a throwaway entry to delete**

```bash
rtk proxy curl -s http://localhost:3000/api/youtube/archive | python3 -c "import json,sys; rows = json.load(sys.stdin); [print(r['slug'], '·', r['title']) for r in rows]"
```

Pick one slug to delete. If the only entry is the 3Blue1Brown smoke video, extract a fresh throwaway first via the UI (paste an URL, wait for done) before deleting it — preserve the original smoke entry.

- [ ] **Step 3: Open the browser to `http://localhost:3000/youtube`**

- Confirm the sidebar entry now reads `🎬 YT Extractor` (not "YouTube").
- Locate the throwaway row in the archive list.
- Click 🗑 → button widens to red "✗ Confirm delete".
- Wait 3s without clicking → button reverts to 🗑. Confirms auto-disarm.
- Click 🗑 again → red confirm.
- Click "✗ Confirm delete" → row disappears immediately (optimistic).

- [ ] **Step 4: Verify on disk**

```bash
SLUG="<the slug you deleted>"
ls ~/.claude/obsidian-mind/youtube/ | grep -F "$SLUG" || echo "  md gone OK"
ls ~/Youtube-extractor/output/ | grep -F "$SLUG" || echo "  pdfs gone OK"
grep -F "$SLUG" ~/Youtube-extractor/output/catalog.ndjson || echo "  catalog row gone OK"
grep -F "$SLUG" ~/Youtube-extractor/output/jobs.ndjson || echo "  jobs row gone OK"
```

Expected: all four print "OK".

- [ ] **Step 5: Verify the API matches**

```bash
rtk proxy curl -s http://localhost:3000/api/youtube/archive | python3 -c "import json,sys; print(f\"entries: {len(json.load(sys.stdin))}\")"
```

Expected: count one less than before.

- [ ] **Step 6: Negative path — delete an unknown slug via API**

```bash
rtk proxy curl -s -o /dev/null -w "%{http_code}\n" -X DELETE http://localhost:3000/api/youtube/archive/totally-bogus-slug-xyz
```

Expected: 404.

- [ ] **Step 7: Append the smoke entry to the log**

Add a new line at the end of the existing list in `docs/manual-test-log.md`:

```markdown
- 2026-05-03: archive-delete smoke — created throwaway entry, two-click confirm in UI nuked it, verified .md / PDFs / catalog row / jobs.ndjson row all gone, sidebar reads "YT Extractor", DELETE on unknown slug returns 404 via MC proxy.
```

- [ ] **Step 8: Commit and report unpushed counts**

```bash
cd ~/Youtube-extractor
git add docs/manual-test-log.md
git commit -m "docs: log archive-delete E2E smoke"
git log --oneline origin/main..HEAD
echo "---"
cd ~/OpenDeeDee/mission-control
git log --oneline origin/main..HEAD
```

Stop here. Pushing both repos is Dexter's call (per global CLAUDE.md "Don't push without asking").

---

## Self-review

**Spec coverage check** — every spec section maps to a task:

| Spec section | Implementing task |
|---|---|
| §3.1 Operation order | Task 3 (delete_by_slug) |
| §3.2 Module signature | Task 3 |
| §3.3 Atomic rewrite helper | Task 1 |
| §3.4 API integration | Task 4 |
| §3.5 Response shape | Task 3 + Task 4 (TestClient asserts shape) |
| §4 MC proxy | Task 5 |
| §5.1 useArmedAction hook | Task 6 |
| §5.2 Row integration | Task 7 |
| §5.3 Page integration | Task 8 |
| §5.4 No native confirm | Task 7 (inline two-click implementation) |
| §6 Error handling table | Task 8 (page handler) + Task 4 (404) |
| §7.1 Backend unit tests | Task 1 + Task 3 |
| §7.2 Backend integration tests | Task 4 |
| §7.4 Manual smoke | Task 9 |
| §8 Acceptance criteria | All tasks combined |
| §9 File-level summary | Mirrored in this plan's File Structure table |

**Placeholder scan:** none — every code step has full content. No "TBD", no "implement later", no "similar to Task N".

**Type consistency:**
- `DeleteResult` fields used identically in Task 3 (definition), Task 4 (API response shape), Task 4 tests (TestClient asserts).
- `ArchiveEntryNotFound` raised in Task 3, caught in Task 4.
- `JobStore.remove_by_slug(slug) -> list[str]` defined in Task 2, called in Task 3.
- `rewrite_ndjson_filtered(path, predicate) -> int` defined in Task 1, called in Task 2 + Task 3.
- `onDelete: (slug: string) => Promise<void>` typed identically in Task 7 (ArchiveList prop) and Task 8 (page handler).
- `useArmedAction` returns the same `{armed, busy, setBusy, arm, disarm}` in Task 6 (definition) and Task 7 (consumption).

---

## Execution choice

Plan complete and saved to `docs/superpowers/plans/2026-05-03-archive-delete.md`. Two execution options:

**1. Subagent-Driven (recommended)** — fresh subagent per task, review between tasks. Wave A backend tasks (1-4) are sequential because they each build on the previous module. Wave B Tasks 5 + 6 can run as 2 parallel agents (no shared files); Tasks 7 + 8 sequential after them. Task 9 manual.

**2. Inline Execution** — run tasks in this session via executing-plans, batch with checkpoints.
