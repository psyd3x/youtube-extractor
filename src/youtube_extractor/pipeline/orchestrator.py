from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from slugify import slugify

from youtube_extractor.config import settings
from youtube_extractor.models import JobStage, Metadata
from youtube_extractor.pipeline.distill import distill
from youtube_extractor.pipeline.instructions import extract_instructions
from youtube_extractor.pipeline.metadata import fetch_metadata
from youtube_extractor.pipeline.render_md import render_markdown
from youtube_extractor.pipeline.render_pdf import render_instructions_pdf, render_pdfs
from youtube_extractor.pipeline.transcript import NoTranscriptError, fetch_transcript
from youtube_extractor.pipeline.url import extract_video_id
from youtube_extractor.pipeline.whisper_fallback import WhisperError, whisper_transcript
from youtube_extractor.store.catalog import append_entry, find_by_video_id


@dataclass
class PipelineResult:
    slug: str
    md_path: Path
    pdf_full_path: Path
    pdf_lazy_path: Path
    # Defaulted so existing call sites that construct the 4-field result stay valid;
    # None when instructions extraction was skipped or failed (best-effort).
    pdf_instructions_path: Path | None = None


def _make_slug(meta: Metadata) -> str:
    date_part = meta.published or time.strftime("%Y-%m-%d")
    title_part = slugify(meta.title or meta.video_id, max_length=40)
    return f"{date_part}-{meta.video_id}-{title_part}"[:80]


async def run_pipeline(
    *,
    url: str,
    vault_dir: Path,
    output_dir: Path,
    on_stage: Callable[[JobStage], None] | None = None,
) -> PipelineResult:
    """Run all 6 stages: url -> metadata -> transcript -> distill -> render -> catalog.

    Idempotent on video_id: a second call for an already-extracted video short-circuits
    to the catalog entry without re-running any stage.

    on_stage (optional) is called as each stage begins. The service layer uses it to
    advance the job record so a long job (e.g. a multi-hour whisper transcription) keeps
    reporting progress instead of looking hung. Kept as a callback so this module stays
    pure — it never touches the job store directly.
    """

    def _emit(stage: JobStage) -> None:
        if on_stage is not None:
            on_stage(stage)

    video_id = extract_video_id(url)
    catalog_path = output_dir / "catalog.ndjson"

    # Every stage below is synchronous and blocking (yt-dlp network calls, transcript
    # retries with time.sleep, CPU-heavy PDF rendering, file I/O). run_pipeline runs
    # inside the FastAPI event loop via a background task, so each blocking call is
    # offloaded with asyncio.to_thread — otherwise the loop stalls and concurrent
    # POST /jobs requests time out at the proxy. distill is already async.
    existing = await asyncio.to_thread(find_by_video_id, catalog_path, video_id)
    if existing:
        return PipelineResult(
            slug=existing["slug"],
            md_path=Path(existing["md_path"]),
            pdf_full_path=Path(existing["pdf_full_path"]),
            pdf_lazy_path=Path(existing["pdf_lazy_path"]),
            pdf_instructions_path=(
                Path(existing["pdf_instructions_path"])
                if existing.get("pdf_instructions_path")
                else None
            ),
        )

    _emit(JobStage.metadata)
    meta = await asyncio.to_thread(fetch_metadata, video_id)

    _emit(JobStage.transcript)
    try:
        transcript = await asyncio.to_thread(fetch_transcript, video_id)
    except NoTranscriptError:
        if not settings.whisper_enabled:
            raise
        try:
            transcript = await asyncio.to_thread(whisper_transcript, video_id)
        except WhisperError as e:
            raise NoTranscriptError(
                f"no official transcript; whisper fallback failed: {e}"
            ) from e
    _emit(JobStage.distill)
    distillation = await distill(meta, transcript)

    # Instructions extraction is BEST-EFFORT: the core FULL/LAZY pipeline must still
    # succeed even if this fails, so any error is logged and downgraded to None.
    instructions = None
    try:
        _emit(JobStage.instructions)
        instructions = await extract_instructions(meta, transcript)
    except Exception as e:  # best-effort: includes InstructionsError and any LLM/IO fault
        logging.getLogger(__name__).warning("instructions extraction failed: %s", e)
        instructions = None

    slug = _make_slug(meta)
    extracted_date = time.strftime("%Y-%m-%d")
    _emit(JobStage.render_pdf)
    pdf_full_path, pdf_lazy_path = await asyncio.to_thread(
        render_pdfs,
        meta=meta,
        distill=distillation,
        slug=slug,
        output_dir=output_dir,
        extracted_date=extracted_date,
    )
    pdf_instructions_path = (
        await asyncio.to_thread(
            render_instructions_pdf,
            meta=meta,
            instructions=instructions,
            slug=slug,
            output_dir=output_dir,
            extracted_date=extracted_date,
        )
        if instructions is not None
        else None
    )
    _emit(JobStage.render_md)
    md_path = await asyncio.to_thread(
        render_markdown,
        meta=meta,
        distill=distillation,
        slug=slug,
        vault_dir=vault_dir,
        pdf_full_path=str(pdf_full_path),
        pdf_lazy_path=str(pdf_lazy_path),
        extracted_date=extracted_date,
        instructions=instructions,
        pdf_instructions_path=(
            str(pdf_instructions_path) if pdf_instructions_path else None
        ),
    )

    _emit(JobStage.store)
    await asyncio.to_thread(
        append_entry,
        catalog_path,
        {
            "slug": slug,
            "video_id": meta.video_id,
            "title": meta.title,
            "channel": meta.channel,
            "url": f"https://youtube.com/watch?v={meta.video_id}",
            "duration": meta.duration_s,
            "extracted_at": time.time(),
            "md_path": str(md_path),
            "pdf_full_path": str(pdf_full_path),
            "pdf_lazy_path": str(pdf_lazy_path),
            "pdf_instructions_path": (
                str(pdf_instructions_path) if pdf_instructions_path else None
            ),
            "tags": ["youtube", *distillation.full.topics[:5]],
            "topics": distillation.full.topics,
            "people": distillation.full.people,
        },
    )

    return PipelineResult(
        slug=slug,
        md_path=md_path,
        pdf_full_path=pdf_full_path,
        pdf_lazy_path=pdf_lazy_path,
        pdf_instructions_path=pdf_instructions_path,
    )
