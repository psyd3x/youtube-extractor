import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

from youtube_extractor.models import Metadata, Transcript, TranscriptSegment
from youtube_extractor.pipeline.distill import distill

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "sample_distillation.json").read_text())


def _meta() -> Metadata:
    return Metadata(video_id="abc", title="t", channel="c", duration_s=600)


def _short_transcript() -> Transcript:
    return Transcript(
        segments=[TranscriptSegment(start=0, dur=2, text="hello world " * 50)],
        full_text="hello world " * 500,
        language="en",
        source="official",
    )


async def test_distill_short_video():
    fake = AsyncMock(return_value=FIXTURE)
    with patch("youtube_extractor.pipeline.distill.LLMClient.chat_json", fake):
        d = await distill(_meta(), _short_transcript())
    assert d.title == "Test Video"
    assert d.lazy.key_points == ["Point one", "Point two"]
    assert d.full.chapters[0].title == "Intro"


async def test_distill_chunked_long_video():
    """Long transcripts get chunked; consolidation merges into one Distillation."""
    long_transcript = Transcript(
        segments=[TranscriptSegment(start=0, dur=1, text="x")],
        full_text=("word " * 30000),
        language="en",
        source="official",
    )
    fake = AsyncMock(return_value=FIXTURE)
    with patch("youtube_extractor.pipeline.distill.LLMClient.chat_json", fake):
        d = await distill(_meta(), long_transcript)
    assert fake.call_count >= 3
    assert d.title
