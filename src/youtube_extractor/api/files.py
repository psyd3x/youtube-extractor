from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse

from youtube_extractor.config import settings

router = APIRouter()


@router.get("/pdfs/{slug}/{kind}")
async def get_pdf(slug: str, kind: str) -> FileResponse:
    if kind not in ("full", "lazy", "instructions"):
        raise HTTPException(status_code=400, detail="kind must be full, lazy, or instructions")
    p = settings.output_dir / f"{slug}-{kind}.pdf"
    if not p.exists():
        raise HTTPException(status_code=404, detail="pdf not found")
    return FileResponse(p, media_type="application/pdf", filename=p.name)


@router.get("/files/{slug}/md", response_class=PlainTextResponse)
async def get_md(slug: str) -> str:
    p = settings.obsidian_vault_path / f"{slug}.md"
    if not p.exists():
        raise HTTPException(status_code=404, detail="md not found")
    return p.read_text(encoding="utf-8")
