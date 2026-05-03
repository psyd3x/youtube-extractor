---
title: Archive Delete — Design Spec
project: youtube-extractor
type: design-spec
status: approved
date: 2026-05-03
tags: [youtube-extractor, archive, delete, design-spec, mission-control]
description: Adds a hard-delete capability to the YouTube Extractor archive — one user action removes the catalog row, the .md from the Obsidian vault, both PDFs from disk, and every jobs.ndjson row tied to the same slug. Covers backend module, FastAPI endpoint, MC proxy route, and the inline two-click confirm UI.
---

# Archive Delete — Design Spec

Successor to [[2026-05-03-youtube-extractor-design]] (the base extractor spec). Implementation tracked in [[2026-05-03-archive-delete]] (plan, written next).

**Date:** 2026-05-03
**Status:** Approved
**Project:** youtube-extractor (+ OpenDeeDee/mission-control proxy + UI)

## 1. Purpose

Let the user remove an archive entry from the YouTube Extractor — completely. One action nukes the catalog row, the `.md` in the Obsidian vault, both PDFs on disk, and every `jobs.ndjson` row tied to that slug. Nothing recoverable, no soft-delete, no trash folder. Failed-job cleanup is out of scope (deferred until felt).

## 2. Scope

**In scope**
- New backend endpoint `DELETE /archive/{slug}` on the extractor service.
- New backend module `youtube_extractor/store/delete.py` exposing `delete_by_slug(settings, slug) -> DeleteResult`.
- Atomic rewrite of `catalog.ndjson` and `jobs.ndjson` (write to temp, `os.replace`).
- Mission Control proxy route `DELETE /api/youtube/archive/[slug]`.
- UI: per-row inline two-click delete control on `ArchiveList`. First click arms ("✗ Confirm" red button, 3s auto-revert). Second click deletes.
- A small reusable `useArmedAction(timeoutMs)` hook in `src/app/youtube/_components/useArmedAction.ts`.
- Tests on the backend delete module. Manual smoke for the full UI path.

**Out of scope**
- Failed-job cleanup UI / a separate "Failed jobs" panel.
- A "purge older than N days" sweeper.
- Bulk delete / multi-select.
- Soft delete or trash recovery.
- Job-id-keyed delete (`DELETE /jobs/{id}`).

## 3. Backend — `DELETE /archive/{slug}`

### 3.1 Operation order

Best-effort: continue on partial failure, return per-step summary.

1. Read the catalog row matching `slug`. If missing → respond `404`.
2. Delete `.md` file at `row["md_path"]`. Missing file is not an error; record `false`.
3. Delete `row["pdf_full_path"]`. Missing file is not an error.
4. Delete `row["pdf_lazy_path"]`. Missing file is not an error.
5. Rewrite `catalog.ndjson` excluding the deleted slug. Atomic via `tempfile + os.replace`.
6. Rewrite `jobs.ndjson` excluding every row where `row["slug"] == target_slug`. Atomic. Count rows removed.

If steps 5 or 6 raise (disk full, permission), the endpoint returns `500` with the partial result so the caller knows what already happened.

### 3.2 Module: `store/delete.py`

```python
from dataclasses import dataclass

@dataclass
class DeleteResult:
    slug: str
    md: bool
    pdf_full: bool
    pdf_lazy: bool
    catalog_row: bool
    jobs_removed: int

class ArchiveEntryNotFound(Exception): ...

def delete_by_slug(settings, slug: str) -> DeleteResult: ...
```

`ArchiveEntryNotFound` is the only exception the API layer translates to `404`. Anything else propagates as `500`.

### 3.3 Atomic rewrite helper

Internal helper:

```python
def _rewrite_ndjson_filtered(path: Path, predicate) -> int:
    """Rewrite an ndjson file keeping only rows where predicate(row) is True.
    Returns count of rows removed. Atomic: temp file in same dir, then os.replace."""
```

Used by both the catalog and jobs rewrites.

### 3.4 API integration

`api/archive.py` gains:

```python
@router.delete("/archive/{slug}")
async def delete_archive(slug: str) -> dict:
    try:
        result = delete_by_slug(settings, slug)
    except ArchiveEntryNotFound:
        raise HTTPException(404, f"slug not found: {slug}")
    return asdict(result)
```

### 3.5 Response shape

```json
{
  "slug": "2017-10-05-abc-...",
  "md": true,
  "pdf_full": true,
  "pdf_lazy": true,
  "catalog_row": true,
  "jobs_removed": 2
}
```

Per-step booleans are intentional — they let the caller (or a human reading logs) see what actually got nuked when files were already missing.

## 4. MC Proxy — `DELETE /api/youtube/archive/[slug]`

Pure pass-through. New file:

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

No new auth. MC middleware already gates `/api/*`.

## 5. UI — `ArchiveList` row delete control

### 5.1 Hook: `useArmedAction`

```typescript
// src/app/youtube/_components/useArmedAction.ts
import { useEffect, useRef, useState } from 'react'

export function useArmedAction(timeoutMs = 3000) {
  const [armed, setArmed] = useState(false)
  const [busy, setBusy] = useState(false)
  const tRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  function arm() {
    setArmed(true)
    if (tRef.current) clearTimeout(tRef.current)
    tRef.current = setTimeout(() => setArmed(false), timeoutMs)
  }
  function disarm() {
    setArmed(false)
    if (tRef.current) clearTimeout(tRef.current)
  }
  useEffect(() => () => { if (tRef.current) clearTimeout(tRef.current) }, [])

  return { armed, busy, setBusy, arm, disarm }
}
```

### 5.2 Row integration

`ArchiveList.tsx` receives a new prop `onDelete: (slug: string) => Promise<void>`. Each `RowItem` instantiates `useArmedAction()` and renders a fourth button after PDF LAZY:

- **Idle** (`!armed && !busy`): `🗑` 12 px, gray, hover red.
- **Armed** (`armed && !busy`): "✗ Confirm" red bg, click → calls onDelete, sets busy.
- **Busy** (`busy`): "..." disabled.

After a successful delete the parent removes the row from local state (optimistic) then calls `refreshArchive(query)` to reconcile.

### 5.3 Page integration

`page.tsx` defines `onDelete`:

```typescript
async function onDelete(slug: string) {
  // Optimistic
  setArchive(prev => prev.filter(r => r.slug !== slug))
  const r = await fetch(`/api/youtube/archive/${encodeURIComponent(slug)}`, { method: 'DELETE' })
  if (!r.ok) {
    setDeleteError(`Delete failed (${r.status}). Refreshing.`)
    await refreshArchive(query)
  } else {
    setDeleteError(null)
    // Reconcile in case the server view drifted
    await refreshArchive(query)
  }
}
```

A small `deleteError` state above the archive renders an inline 8-second message on failure.

### 5.4 No native confirm dialog

Native `confirm()` is jarring against the dark minimalist UI. The two-click pattern keeps the visual language consistent with the rest of the page.

## 6. Error handling

| Condition | Backend status | UI behavior |
|---|---|---|
| Slug not in catalog | 404 | Inline "Already gone, refreshing", `refreshArchive()` |
| Disk error mid-rewrite | 500 with partial result | Inline "Delete failed: {message}", row reappears via refresh |
| Network failure | (no response) | Inline "Network error, try again", row reappears via refresh |
| Concurrent re-submit during delete | last write wins | Acceptable — re-submit either creates fresh files (delete saw old slug), or finds them gone (delete won) |

## 7. Testing

### 7.1 Backend (pytest)

Tests live in `tests/store/test_delete.py`. Each uses a `tmp_path` fixture and a fake `Settings` pointing into it.

| # | Case | Expected |
|---|---|---|
| 1 | Happy path: row exists, all artifacts on disk, 2 jobs match slug | `DeleteResult(md=True, pdf_full=True, pdf_lazy=True, catalog_row=True, jobs_removed=2)`. Files gone. Catalog and jobs rewritten without those rows. Other rows untouched. |
| 2 | Missing slug | Raises `ArchiveEntryNotFound`. No filesystem changes. |
| 3 | Catalog row exists but `.md` already missing | Returns `DeleteResult(md=False, ...)`, catalog row still removed. |
| 4 | Atomic rewrite preserves other rows | Catalog has 3 rows, delete one → file has 2 rows, both intact byte-for-byte except the removed row. |

### 7.2 Backend integration

`tests/api/test_archive_delete.py` — uses FastAPI test client:
- `DELETE /archive/{slug}` for an existing slug → 200 with the per-step response.
- `DELETE /archive/{slug}` for unknown slug → 404.

### 7.3 MC proxy

No automated test. Matches the no-test pattern of the other proxy routes in the same directory.

### 7.4 Manual smoke

After build + deploy:
1. Extract a fresh throwaway video.
2. Confirm `.md`, both PDFs, catalog row, and `jobs.ndjson` row all present.
3. Click 🗑 on the row, then "✗ Confirm".
4. Verify row vanishes from UI.
5. Verify on disk: `.md` gone from vault, both PDFs gone from output dir, catalog row gone, `jobs.ndjson` row gone.

Append entry to `docs/manual-test-log.md`.

## 8. Acceptance criteria

- `DELETE /archive/{slug}` exists, returns the documented shape, idempotently deletes everything tied to a slug.
- The MC proxy passes the call through correctly with `DELETE`.
- The UI exposes a per-row two-click delete control that disarms after 3s.
- Backend test suite remains 100% green; new tests cover the four cases in §7.1 plus the two integration cases in §7.2.
- `npm run build` for mission-control stays clean.
- Manual smoke succeeds end-to-end.

## 9. File-level summary

| Repo | File | Action |
|---|---|---|
| youtube-extractor | `src/youtube_extractor/store/delete.py` | New |
| youtube-extractor | `src/youtube_extractor/api/archive.py` | Modify — add DELETE route |
| youtube-extractor | `tests/store/test_delete.py` | New |
| youtube-extractor | `tests/api/test_archive_delete.py` | New |
| mission-control | `src/app/api/youtube/archive/[slug]/route.ts` | New |
| mission-control | `src/app/youtube/_components/useArmedAction.ts` | New |
| mission-control | `src/app/youtube/_components/ArchiveList.tsx` | Modify — onDelete prop + delete button |
| mission-control | `src/app/youtube/page.tsx` | Modify — onDelete handler + deleteError state |
| youtube-extractor | `docs/manual-test-log.md` | Modify — append smoke entry |
