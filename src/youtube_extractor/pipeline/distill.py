from __future__ import annotations

import json

from youtube_extractor.config import settings
from youtube_extractor.llm.client import LLMClient, LLMError
from youtube_extractor.models import Distillation, Metadata, Transcript

# Words per chunk. Sized against the distill model's token context (kimi-linear-48b:
# 32768): whisper transcripts tokenize at ~1.8 tok/word, so each chunk's prompt must
# stay well under the window AND leave room for the model to generate the JSON output.
# 12000 words ≈ 22k prompt tokens, leaving ~10k for the response. 18000 overflowed (HTTP
# 400). Regression-guarded by tests/test_distill.py::test_chunk_prompt_fits_model_context.
CHUNK_WORDS = 12000

# Max characters of serialized chunk partials to pack into one consolidation call. A long
# video yields many partials; dumping them all into a single prompt overflows the context
# the same way oversized chunks did. ~4 chars/token, so 60k chars ≈ 15k tokens, leaving the
# window open for the merged-JSON response. Partials beyond this are folded over multiple
# rounds. Regression-guarded by test_consolidation_batches_to_fit_context.
MAX_CONSOLIDATE_CHARS = 60_000

# Generated once; passed to the LLM as a structured-output schema so the response
# is guaranteed to match Distillation regardless of which model serves the endpoint.
_DISTILL_SCHEMA = Distillation.model_json_schema()


class DistillError(Exception):
    def __init__(self, message: str, *, code: str = "DISTILL_FAILED") -> None:
        super().__init__(message)
        self.code = code


SYSTEM_PROMPT = """You are an expert at distilling YouTube video transcripts into structured knowledge.
You produce two outputs in one JSON response: a LAZY summary (5-10 bullet key points + a 150-word
paragraph) and a FULL chapter-by-chapter breakdown with key points, direct quotes, topics, people,
and references. Return STRICT JSON matching the requested schema. Do not invent quotes.
"""


def _user_prompt(
    meta: Metadata,
    transcript_chunk: str,
    is_chunk: bool,
    total_chunks: int = 1,
    idx: int = 0,
) -> str:
    chunk_note = (
        f"\nThis is chunk {idx + 1} of {total_chunks} of a long transcript. Focus on this chunk only; "
        "consolidation will happen later."
        if is_chunk
        else ""
    )
    return (
        f"Title: {meta.title}\nChannel: {meta.channel}\nDuration: {meta.duration_s}s\n"
        f"Description: {(meta.description or '')[:500]}\n{chunk_note}\n\nTranscript:\n{transcript_chunk}\n\n"
        "Return JSON: {title, tldr, lazy: {key_points[], summary_paragraph}, "
        "full: {chapters: [{title, summary, key_points[], quotes[]}], topics[], people[], references[]}}"
    )


def _consolidate_prompt(meta: Metadata, partials: list[dict]) -> str:
    return (
        f"Consolidate these {len(partials)} chunk-level distillations of '{meta.title}' "
        f"into one final Distillation. Merge chapters in order, dedupe key points, "
        f"keep best quotes (verbatim). Return the same JSON schema.\n\n"
        f"Chunks:\n{json.dumps(partials)}"
    )


def _chunk_text(text: str, max_words: int) -> list[str]:
    words = text.split()
    if len(words) <= max_words:
        return [text]
    chunks: list[str] = []
    for i in range(0, len(words), max_words):
        chunks.append(" ".join(words[i : i + max_words]))
    return chunks


def _batch_partials(partials: list[dict], max_chars: int) -> list[list[dict]]:
    """Greedily pack partials into batches whose compact-JSON size stays under max_chars.

    If no two adjacent partials fit together, falls back to pairwise batches so a fold
    round always makes progress (two chunk-level partials still fit the window).
    """
    batches: list[list[dict]] = []
    current: list[dict] = []
    current_chars = 0
    for p in partials:
        size = len(json.dumps(p))
        if current and current_chars + size > max_chars:
            batches.append(current)
            current, current_chars = [], 0
        current.append(p)
        current_chars += size
    if current:
        batches.append(current)
    if len(batches) == len(partials) and len(partials) > 1:
        batches = [partials[i : i + 2] for i in range(0, len(partials), 2)]
    return batches


async def distill(meta: Metadata, transcript: Transcript) -> Distillation:
    client = LLMClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        timeout_s=settings.llm_timeout_s,
    )

    chunks = _chunk_text(transcript.full_text, CHUNK_WORDS)

    if len(chunks) == 1:
        try:
            raw = await client.chat_json(
                system=SYSTEM_PROMPT,
                user=_user_prompt(meta, chunks[0], is_chunk=False),
                response_schema_name="Distillation",
                schema=_DISTILL_SCHEMA,
            )
        except LLMError as e:
            raise DistillError(str(e), code=e.code) from e
        return Distillation.model_validate(raw)

    partials: list[dict] = []
    for i, chunk in enumerate(chunks):
        try:
            partials.append(
                await client.chat_json(
                    system=SYSTEM_PROMPT,
                    user=_user_prompt(
                        meta, chunk, is_chunk=True, total_chunks=len(chunks), idx=i
                    ),
                    response_schema_name="Distillation",
                    schema=_DISTILL_SCHEMA,
                )
            )
        except LLMError as e:
            raise DistillError(f"chunk {i + 1}/{len(chunks)} failed: {e}", code=e.code) from e

    # Fold partials into one Distillation, batching so no single consolidation prompt
    # overflows the context window (a long video can produce many partials).
    while len(partials) > 1:
        next_partials: list[dict] = []
        for batch in _batch_partials(partials, MAX_CONSOLIDATE_CHARS):
            if len(batch) == 1:
                next_partials.append(batch[0])
                continue
            try:
                next_partials.append(
                    await client.chat_json(
                        system=SYSTEM_PROMPT,
                        user=_consolidate_prompt(meta, batch),
                        response_schema_name="Distillation",
                        schema=_DISTILL_SCHEMA,
                    )
                )
            except LLMError as e:
                raise DistillError(f"consolidation failed: {e}", code=e.code) from e
        partials = next_partials

    return Distillation.model_validate(partials[0])
