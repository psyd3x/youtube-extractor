from __future__ import annotations

from fastapi import APIRouter

from youtube_extractor.config import settings
from youtube_extractor.store.search import search_entries

router = APIRouter()


@router.get("/archive")
async def archive(q: str = "") -> list[dict]:
    catalog = settings.output_dir / "catalog.ndjson"
    return search_entries(catalog, q)
