from unittest.mock import AsyncMock, patch

from youtube_extractor.models import (
    Chapter,
    Distillation,
    FullDoc,
    LazyDoc,
    Metadata,
    Transcript,
    TranscriptSegment,
)
from youtube_extractor.pipeline.orchestrator import PipelineResult, run_pipeline

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


async def test_run_pipeline_happy(tmp_path):
    vault = tmp_path / "vault"
    output = tmp_path / "output"
    with patch("youtube_extractor.pipeline.orchestrator.fetch_metadata", return_value=_meta()), \
         patch("youtube_extractor.pipeline.orchestrator.fetch_transcript", return_value=_tx()), \
         patch("youtube_extractor.pipeline.orchestrator.distill", new=AsyncMock(return_value=_di())):
        result = await run_pipeline(
            url=f"https://youtu.be/{VIDEO_ID}",
            vault_dir=vault,
            output_dir=output,
        )
    assert isinstance(result, PipelineResult)
    assert result.md_path.exists()
    assert result.pdf_full_path.exists()
    assert result.pdf_lazy_path.exists()
    assert result.slug.startswith(f"2024-01-15-{VIDEO_ID}-")
    cat = output / "catalog.ndjson"
    assert cat.exists() and cat.read_text().strip()


async def test_run_pipeline_idempotent(tmp_path):
    """Re-running on same video returns cached entry without re-calling pipeline stages."""
    vault = tmp_path / "vault"
    output = tmp_path / "output"
    with patch("youtube_extractor.pipeline.orchestrator.fetch_metadata", return_value=_meta()), \
         patch("youtube_extractor.pipeline.orchestrator.fetch_transcript", return_value=_tx()), \
         patch("youtube_extractor.pipeline.orchestrator.distill", new=AsyncMock(return_value=_di())):
        first = await run_pipeline(url=f"https://youtu.be/{VIDEO_ID}", vault_dir=vault, output_dir=output)

    # Second call — patches are gone; if orchestrator re-fetches, it'll hit real network and fail
    # OR raise NameError. We expect it to short-circuit on catalog hit instead.
    second = await run_pipeline(url=f"https://youtu.be/{VIDEO_ID}", vault_dir=vault, output_dir=output)
    assert second.slug == first.slug
    assert second.md_path == first.md_path
