import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

from youtube_extractor.models import Metadata, Transcript, TranscriptSegment
from youtube_extractor.pipeline import distill as distill_mod
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


def test_chunk_prompt_fits_model_context():
    """A worst-case full-size chunk must leave the model room to READ the prompt
    AND GENERATE the distillation within its context window.

    Regression for the V0-yBVdbi6w incident: CHUNK_WORDS=18000 produced a
    ~33k-token prompt that overflowed Kimi's 32768 context (HTTP 400), surfaced
    only once the whisper fallback started feeding full-length transcripts.
    """
    MODEL_CONTEXT = 32768  # kimi-linear-48b
    OUTPUT_RESERVE = 6000  # tokens the model needs to emit the chunk-level JSON
    TOKENS_PER_WORD = 1.85  # observed ~1.8 for whisper text (token-dense); round up

    transcript = ("word " * (distill_mod.CHUNK_WORDS * 3)).strip()
    chunks = distill_mod._chunk_text(transcript, distill_mod.CHUNK_WORDS)
    biggest_words = max(len(c.split()) for c in chunks)
    # Fixed per-request overhead: system prompt + user scaffold (title/desc/schema hint).
    scaffold_words = len(distill_mod.SYSTEM_PROMPT.split()) + 200
    est_prompt_tokens = (biggest_words + scaffold_words) * TOKENS_PER_WORD

    assert est_prompt_tokens + OUTPUT_RESERVE <= MODEL_CONTEXT, (
        f"chunk prompt ~{est_prompt_tokens:.0f} tok + {OUTPUT_RESERVE} output reserve "
        f"exceeds {MODEL_CONTEXT}-token context (CHUNK_WORDS={distill_mod.CHUNK_WORDS})"
    )


def _fat_partial() -> dict:
    """A valid Distillation-shaped dict big enough that several can't share one prompt."""
    return {
        "title": "T",
        "tldr": "x" * 200,
        "lazy": {"key_points": ["k" * 100] * 5, "summary_paragraph": "lorem ipsum " * 1200},
        "full": {
            "chapters": [{"title": "c", "summary": "s" * 500, "key_points": [], "quotes": []}],
            "topics": [],
            "people": [],
            "references": [],
        },
    }


async def test_consolidation_batches_to_fit_context():
    """Many fat chunk partials must be folded in budget-sized batches, never dumped into one
    over-context consolidation call. Latent-overflow guard for very long (many-chunk) videos."""
    long_transcript = Transcript(
        segments=[TranscriptSegment(start=0, dur=1, text="x")],
        full_text=("word " * (distill_mod.CHUNK_WORDS * 6)),  # 6 chunks -> 6 partials
        language="en",
        source="official",
    )
    captured: list[str] = []

    async def _record(*args, **kwargs):
        captured.append(kwargs["user"])
        return _fat_partial()

    fake = AsyncMock(side_effect=_record)
    with patch("youtube_extractor.pipeline.distill.LLMClient.chat_json", fake):
        d = await distill(_meta(), long_transcript)

    consolidation_prompts = [p for p in captured if p.startswith("Consolidate")]
    assert len(consolidation_prompts) >= 2, "expected batched (multi-call) consolidation"
    assert max(len(p) for p in consolidation_prompts) <= distill_mod.MAX_CONSOLIDATE_CHARS + 2000
    assert d.title
