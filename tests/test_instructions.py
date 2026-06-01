import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from youtube_extractor.llm.client import LLMError
from youtube_extractor.models import InstructionsAndData, Metadata, Transcript, TranscriptSegment
from youtube_extractor.pipeline.instructions import InstructionsError, extract_instructions
from youtube_extractor.pipeline.instructions import personas as p
from youtube_extractor.pipeline.instructions import team as team_mod

CHAT_JSON = "youtube_extractor.pipeline.instructions.team.LLMClient.chat_json"


def _meta() -> Metadata:
    return Metadata(video_id="abc", title="Build a RAG app", channel="c", duration_s=600)


# A real URL/command the transcript actually contains, plus a fabricated one to be dropped.
REAL_URL = "https://example.com/docs"
REAL_CMD = "pip install chromadb"
FAKE_URL = "https://evil.invented.example/never-said"
FAKE_CMD = "rm -rf /tmp/hallucinated"

TRANSCRIPT_TEXT = (
    "Welcome. First go to https://example.com/docs and read it. "
    "Then run pip install chromadb to set up the vector store. "
    "That is the whole workflow."
)


def _transcript(text: str = TRANSCRIPT_TEXT) -> Transcript:
    return Transcript(
        segments=[TranscriptSegment(start=0, dur=2, text=text)],
        full_text=text,
        language="en",
        source="official",
    )


def _long_transcript(n_chunks: int) -> Transcript:
    # Each chunk is INSTRUCTIONS_CHUNK_WORDS words; embed the real url/cmd so the guard keeps them.
    body = ("word " * (team_mod.INSTRUCTIONS_CHUNK_WORDS * n_chunks)).strip()
    text = f"{REAL_URL} {REAL_CMD} {body}"
    return Transcript(
        segments=[TranscriptSegment(start=0, dur=1, text="x")],
        full_text=text,
        language="en",
        source="official",
    )


# Canned per-persona JSON keyed by which system prompt the call carries. The team issues
# Architect/Synthesizer per chunk, then Orchestrator merge, Writer, Reality Checker, ZK.
def _draft_with_fabrications() -> dict:
    return {
        "goal": "Build a retrieval-augmented app.",
        "kind": "tutorial",
        "prerequisites": ["python 3.11"],
        "steps": [
            {"n": 1, "action": "Open the docs", "detail": "d", "command": "", "prompt": ""},
            {"n": 2, "action": "Install deps", "detail": "d", "command": REAL_CMD, "prompt": ""},
            {"n": 3, "action": "Wipe tmp", "detail": "d", "command": FAKE_CMD, "prompt": ""},
        ],
        "prompts": [{"label": "system", "text": "you are helpful"}],
        "commands": [REAL_CMD, FAKE_CMD],
        "resources": [
            {"label": "Docs", "url": REAL_URL},
            {"label": "Sketchy", "url": FAKE_URL},
        ],
        "config": ["CHROMA_PATH=/data"],
        "notes": ["a note"],
        "takeaways": [],
        "vault_links": [],
    }


def _canned_by_persona(*, system: str, user: str, **_kwargs) -> dict:
    if system == p.ARCHITECT_SYS:
        return {
            "prerequisites": ["python 3.11"],
            "steps": [{"n": 1, "action": "Open the docs", "command": ""}],
            "commands": [REAL_CMD],
            "prompts": [{"label": "system", "text": "you are helpful"}],
            "resources": [{"label": "Docs", "url": REAL_URL}],
            "config": ["CHROMA_PATH=/data"],
        }
    if system == p.SYNTHESIZER_SYS:
        return {"takeaways": ["RAG needs a vector store"], "notes": ["a note"]}
    if system == p.ZK_STEWARD_SYS:
        return {"vault_links": ["[[Retrieval-Augmented Generation]]", "[[ChromaDB]]"]}
    # Orchestrator merge, Writer refine, Reality Checker -> return a full-shape draft that
    # carries the fabricated url/command so the deterministic guard has something to strip.
    return _draft_with_fabrications()


async def test_extract_short_video_single_chunk():
    fake = AsyncMock(side_effect=_canned_by_persona)
    with patch(CHAT_JSON, fake):
        result = await extract_instructions(_meta(), _transcript())
    assert isinstance(result, InstructionsAndData)
    assert result.goal
    assert result.kind == "tutorial"
    # ZK steward links flowed through.
    assert "[[ChromaDB]]" in result.vault_links


async def test_drop_guard_removes_fabricated_url_and_command():
    """The deterministic guard strips a url/command NOT in the transcript but keeps real ones."""
    fake = AsyncMock(side_effect=_canned_by_persona)
    with patch(CHAT_JSON, fake):
        result = await extract_instructions(_meta(), _transcript())

    # Real url survives on its resource; fabricated url is blanked (label kept, url dropped).
    urls = {r.label: r.url for r in result.resources}
    assert urls["Docs"] == REAL_URL
    assert urls["Sketchy"] == ""

    # Real command survives in top-level commands; fabricated one is gone.
    assert REAL_CMD in result.commands
    assert FAKE_CMD not in result.commands

    # Per-step command guard: the fabricated step command is cleared, the real one kept.
    by_action = {s.action: s.command for s in result.steps}
    assert by_action["Install deps"] == REAL_CMD
    assert by_action["Wipe tmp"] == ""


async def test_per_chunk_architect_and_synthesizer_run_for_each_chunk():
    """Long transcript chunks; each chunk drives one Architect + one Synthesizer call."""
    tx = _long_transcript(3)
    # Derive the real chunk count from the module so the assertion can't drift if the
    # prepended url/cmd nudges the word total over a chunk boundary.
    n_chunks = len(team_mod._chunk_text(tx.full_text, team_mod.INSTRUCTIONS_CHUNK_WORDS))
    assert n_chunks >= 2, "fixture must span multiple chunks to exercise the per-chunk loop"
    calls: list[str] = []

    async def _record(*, system: str, user: str, **_kwargs) -> dict:
        calls.append(system)
        return _canned_by_persona(system=system, user=user)

    fake = AsyncMock(side_effect=_record)
    with patch(CHAT_JSON, fake):
        result = await extract_instructions(_meta(), tx)

    assert calls.count(p.ARCHITECT_SYS) == n_chunks
    assert calls.count(p.SYNTHESIZER_SYS) == n_chunks
    # Downstream personas each run at least once: orchestrator merge, writer, reality, zk.
    assert calls.count(p.ZK_STEWARD_SYS) == 1
    assert isinstance(result, InstructionsAndData)


async def test_architect_and_synthesizer_invoked_in_parallel():
    """Per chunk the Architect and Synthesizer must be awaited concurrently (asyncio.gather),
    not serialized — both should be in-flight at the same time."""

    inflight = 0
    max_inflight = 0

    async def _slow(*, system: str, user: str, **_kwargs) -> dict:
        nonlocal inflight, max_inflight
        if system in (p.ARCHITECT_SYS, p.SYNTHESIZER_SYS):
            inflight += 1
            max_inflight = max(max_inflight, inflight)
            await asyncio.sleep(0.02)
            inflight -= 1
        return _canned_by_persona(system=system, user=user)

    fake = AsyncMock(side_effect=_slow)
    with patch(CHAT_JSON, fake):
        await extract_instructions(_meta(), _transcript())

    assert max_inflight >= 2, "Architect and Synthesizer should run concurrently per chunk"


async def test_merge_folds_multi_chunk_partials_into_one_document():
    """Many chunks -> the orchestrator merge consolidates into a single InstructionsAndData."""
    fake = AsyncMock(side_effect=_canned_by_persona)
    with patch(CHAT_JSON, fake):
        result = await extract_instructions(_meta(), _long_transcript(4))
    # Steps renumbering/merge is the LLM's job (mocked); we assert the merge produced a
    # single coherent doc with the canned merged shape.
    assert isinstance(result, InstructionsAndData)
    assert result.goal
    assert len(result.steps) >= 1


async def test_llm_error_raises_instructions_error():
    fake = AsyncMock(side_effect=LLMError("backend down", code="LLM_TIMEOUT"))
    with patch(CHAT_JSON, fake), pytest.raises(InstructionsError) as ei:
        await extract_instructions(_meta(), _transcript())
    assert ei.value.code == "LLM_TIMEOUT"
