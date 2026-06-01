import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest

from youtube_extractor.models import (
    Chapter,
    Distillation,
    FullDoc,
    InstructionsAndData,
    JobStage,
    LazyDoc,
    Metadata,
    Step,
    Transcript,
    TranscriptSegment,
)
from youtube_extractor.pipeline.instructions import InstructionsError
from youtube_extractor.pipeline.orchestrator import PipelineResult, run_pipeline
from youtube_extractor.pipeline.transcript import NoTranscriptError
from youtube_extractor.pipeline.whisper_fallback import WhisperError

VIDEO_ID = "dQw4w9WgXcQ"


def _meta():
    return Metadata(
        video_id=VIDEO_ID,
        title="Hello World",
        channel="C",
        duration_s=120,
        published="2024-01-15",
    )


def _tx():
    return Transcript(
        segments=[TranscriptSegment(start=0, dur=1, text="hi")],
        full_text="hi",
        language="en",
        source="official",
    )


def _di():
    return Distillation(
        title="Hello World",
        tldr="t",
        lazy=LazyDoc(key_points=["a"], summary_paragraph="p"),
        full=FullDoc(
            chapters=[Chapter(title="c", summary="s", key_points=["k"], quotes=["q"])],
            topics=["x"],
        ),
    )


def _instructions():
    return InstructionsAndData(
        goal="Build a retrieval-augmented app.",
        kind="tutorial",
        steps=[Step(n=1, action="Install deps", command="pip install chromadb")],
        commands=["pip install chromadb"],
        vault_links=["[[ChromaDB]]"],
    )


def _whisper_tx():
    return Transcript(
        segments=[TranscriptSegment(start=0, dur=1, text="spoken")],
        full_text="spoken words", language="en", source="whisper",
    )


async def test_run_pipeline_happy(tmp_path):
    vault = tmp_path / "vault"
    output = tmp_path / "output"
    with patch("youtube_extractor.pipeline.orchestrator.fetch_metadata", return_value=_meta()), \
         patch("youtube_extractor.pipeline.orchestrator.fetch_transcript", return_value=_tx()), \
         patch("youtube_extractor.pipeline.orchestrator.distill", new=AsyncMock(return_value=_di())), \
         patch("youtube_extractor.pipeline.orchestrator.extract_instructions",
               new=AsyncMock(return_value=_instructions())):
        result = await run_pipeline(
            url=f"https://youtu.be/{VIDEO_ID}",
            vault_dir=vault,
            output_dir=output,
        )
    assert isinstance(result, PipelineResult)
    assert result.md_path.exists()
    assert result.pdf_full_path.exists()
    assert result.pdf_lazy_path.exists()
    assert result.pdf_instructions_path is not None
    assert result.pdf_instructions_path.exists()
    assert result.pdf_instructions_path.name == f"{result.slug}-instructions.pdf"
    assert result.slug.startswith(f"2024-01-15-{VIDEO_ID}-")
    cat = output / "catalog.ndjson"
    assert cat.exists() and cat.read_text().strip()
    import json as _json
    row = _json.loads(cat.read_text().strip().splitlines()[-1])
    assert row["pdf_instructions_path"] == str(result.pdf_instructions_path)


async def test_run_pipeline_instructions_best_effort(tmp_path):
    """Instructions extraction is BEST-EFFORT: when extract_instructions raises, the job
    still completes, no instructions pdf is written, and pdf_instructions_path is None."""
    vault = tmp_path / "vault"
    output = tmp_path / "output"
    with patch("youtube_extractor.pipeline.orchestrator.fetch_metadata", return_value=_meta()), \
         patch("youtube_extractor.pipeline.orchestrator.fetch_transcript", return_value=_tx()), \
         patch("youtube_extractor.pipeline.orchestrator.distill", new=AsyncMock(return_value=_di())), \
         patch("youtube_extractor.pipeline.orchestrator.extract_instructions",
               new=AsyncMock(side_effect=InstructionsError("backend down"))), \
         patch("youtube_extractor.pipeline.orchestrator.render_instructions_pdf") as rip:
        result = await run_pipeline(
            url=f"https://youtu.be/{VIDEO_ID}", vault_dir=vault, output_dir=output
        )
    # Core artifacts still produced.
    assert result.md_path.exists()
    assert result.pdf_full_path.exists()
    assert result.pdf_lazy_path.exists()
    # Instructions skipped entirely.
    assert result.pdf_instructions_path is None
    rip.assert_not_called()
    # Catalog row carries a null instructions path (key present, value None).
    import json as _json
    row = _json.loads((output / "catalog.ndjson").read_text().strip().splitlines()[-1])
    assert row.get("pdf_instructions_path") is None


async def test_run_pipeline_emits_stage_heartbeats(tmp_path):
    """Each stage reports progress via on_stage so a long job's record advances
    (a slow 3h transcription stays distinguishable from a hang)."""
    seen: list[JobStage] = []
    with patch("youtube_extractor.pipeline.orchestrator.fetch_metadata", return_value=_meta()), \
         patch("youtube_extractor.pipeline.orchestrator.fetch_transcript", return_value=_tx()), \
         patch("youtube_extractor.pipeline.orchestrator.distill", new=AsyncMock(return_value=_di())), \
         patch("youtube_extractor.pipeline.orchestrator.extract_instructions",
               new=AsyncMock(return_value=_instructions())):
        await run_pipeline(
            url=f"https://youtu.be/{VIDEO_ID}",
            vault_dir=tmp_path / "vault",
            output_dir=tmp_path / "output",
            on_stage=seen.append,
        )
    assert seen == [
        JobStage.metadata,
        JobStage.transcript,
        JobStage.distill,
        JobStage.instructions,
        JobStage.render_pdf,
        JobStage.render_md,
        JobStage.store,
    ]


async def test_run_pipeline_idempotent(tmp_path):
    """Re-running on same video returns cached entry without re-calling pipeline stages."""
    vault = tmp_path / "vault"
    output = tmp_path / "output"
    with patch("youtube_extractor.pipeline.orchestrator.fetch_metadata", return_value=_meta()), \
         patch("youtube_extractor.pipeline.orchestrator.fetch_transcript", return_value=_tx()), \
         patch("youtube_extractor.pipeline.orchestrator.distill", new=AsyncMock(return_value=_di())), \
         patch("youtube_extractor.pipeline.orchestrator.extract_instructions",
               new=AsyncMock(return_value=None)):
        first = await run_pipeline(url=f"https://youtu.be/{VIDEO_ID}", vault_dir=vault, output_dir=output)

    # Second call — patches are gone; if orchestrator re-fetches, it'll hit real network and fail
    # OR raise NameError. We expect it to short-circuit on catalog hit instead.
    second = await run_pipeline(url=f"https://youtu.be/{VIDEO_ID}", vault_dir=vault, output_dir=output)
    assert second.slug == first.slug
    assert second.md_path == first.md_path


async def test_run_pipeline_keeps_event_loop_responsive(tmp_path):
    """Blocking pipeline stages must run off the event loop.

    Regression: run_pipeline called sync fetch_metadata/fetch_transcript/render_*
    directly, blocking the single FastAPI event loop for the duration of each job.
    A concurrent POST /jobs then stalled past the MC proxy's 6s timeout -> 504 ->
    the UI silently swallowed it ("click button, nothing happens").
    """
    vault = tmp_path / "vault"
    output = tmp_path / "output"
    block_s = 0.4

    def blocking_metadata(_video_id):
        time.sleep(block_s)  # stand-in for the synchronous yt-dlp network call
        return _meta()

    loop_gaps: list[float] = []

    async def heartbeat():
        while True:
            t0 = time.monotonic()
            await asyncio.sleep(0.02)
            loop_gaps.append(time.monotonic() - t0)

    pf, pl, md = output / "f.pdf", output / "l.pdf", vault / "x.md"
    with patch("youtube_extractor.pipeline.orchestrator.find_by_video_id", return_value=None), \
         patch("youtube_extractor.pipeline.orchestrator.fetch_metadata", side_effect=blocking_metadata), \
         patch("youtube_extractor.pipeline.orchestrator.fetch_transcript", return_value=_tx()), \
         patch("youtube_extractor.pipeline.orchestrator.distill", new=AsyncMock(return_value=_di())), \
         patch("youtube_extractor.pipeline.orchestrator.extract_instructions",
               new=AsyncMock(return_value=None)), \
         patch("youtube_extractor.pipeline.orchestrator.render_pdfs", return_value=(pf, pl)), \
         patch("youtube_extractor.pipeline.orchestrator.render_markdown", return_value=md), \
         patch("youtube_extractor.pipeline.orchestrator.append_entry"):
        hb = asyncio.create_task(heartbeat())
        await asyncio.sleep(0.01)  # let the heartbeat park in its sleep before we block
        try:
            await run_pipeline(url=f"https://youtu.be/{VIDEO_ID}", vault_dir=vault, output_dir=output)
        finally:
            hb.cancel()

    assert loop_gaps, "event loop fully blocked during pipeline — heartbeat never got to run"
    max_gap = max(loop_gaps)
    assert max_gap < block_s / 2, (
        f"event loop blocked for {max_gap:.3f}s during pipeline; blocking stages "
        f"must run via asyncio.to_thread"
    )


async def test_pipeline_uses_whisper_when_no_official_transcript(tmp_path, monkeypatch):
    monkeypatch.setattr("youtube_extractor.pipeline.orchestrator.settings.whisper_enabled", True)
    with patch("youtube_extractor.pipeline.orchestrator.fetch_metadata", return_value=_meta()), \
         patch("youtube_extractor.pipeline.orchestrator.fetch_transcript",
               side_effect=NoTranscriptError("none")), \
         patch("youtube_extractor.pipeline.orchestrator.whisper_transcript",
               return_value=_whisper_tx()), \
         patch("youtube_extractor.pipeline.orchestrator.distill", new=AsyncMock(return_value=_di())), \
         patch("youtube_extractor.pipeline.orchestrator.extract_instructions",
               new=AsyncMock(return_value=None)):
        result = await run_pipeline(
            url=f"https://youtu.be/{VIDEO_ID}", vault_dir=tmp_path / "v", output_dir=tmp_path / "o"
        )
    assert result.md_path.exists()


async def test_pipeline_no_whisper_when_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr("youtube_extractor.pipeline.orchestrator.settings.whisper_enabled", False)
    with patch("youtube_extractor.pipeline.orchestrator.fetch_metadata", return_value=_meta()), \
         patch("youtube_extractor.pipeline.orchestrator.fetch_transcript",
               side_effect=NoTranscriptError("none")), \
         patch("youtube_extractor.pipeline.orchestrator.whisper_transcript") as wt:
        with pytest.raises(NoTranscriptError):
            await run_pipeline(
                url=f"https://youtu.be/{VIDEO_ID}", vault_dir=tmp_path / "v", output_dir=tmp_path / "o"
            )
        wt.assert_not_called()


async def test_pipeline_whisper_failure_becomes_no_transcript(tmp_path, monkeypatch):
    monkeypatch.setattr("youtube_extractor.pipeline.orchestrator.settings.whisper_enabled", True)
    with patch("youtube_extractor.pipeline.orchestrator.fetch_metadata", return_value=_meta()), \
         patch("youtube_extractor.pipeline.orchestrator.fetch_transcript",
               side_effect=NoTranscriptError("none")), \
         patch("youtube_extractor.pipeline.orchestrator.whisper_transcript",
               side_effect=WhisperError("download failed")), \
         pytest.raises(NoTranscriptError):
        await run_pipeline(
            url=f"https://youtu.be/{VIDEO_ID}", vault_dir=tmp_path / "v", output_dir=tmp_path / "o"
        )
