from __future__ import annotations

import asyncio
from dataclasses import asdict

from fastapi import APIRouter, HTTPException

from youtube_extractor.config import settings
from youtube_extractor.store.delete import ArchiveEntryNotFound, delete_by_slug
from youtube_extractor.store.search import search_entries

router = APIRouter()

# Serializes concurrent deletes within this process — the catalog rewrite is
# single-writer per atomic.py's contract. Sufficient for the single-user local
# service; not a cross-process lock.
_delete_lock = asyncio.Lock()


@router.get("/archive")
async def archive(q: str = "") -> list[dict]:
    catalog = settings.output_dir / "catalog.ndjson"
    return search_entries(catalog, q)


@router.delete("/archive/{slug}")
async def delete_archive(slug: str) -> dict:
    # Late import so monkeypatching api.jobs._jobs in tests works.
    from youtube_extractor.api import jobs as jobs_module

    async with _delete_lock:
        try:
            result = delete_by_slug(settings, slug, jobs_module._jobs)
        except ArchiveEntryNotFound:
            raise HTTPException(status_code=404, detail=f"slug not found: {slug}") from None
    return asdict(result)
