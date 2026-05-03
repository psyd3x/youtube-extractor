from __future__ import annotations

import json

from youtube_extractor.config import settings
from youtube_extractor.llm.client import LLMClient, LLMError
from youtube_extractor.models import Distillation, Metadata, Transcript

CHUNK_WORDS = 18000


class DistillError(Exception):
    pass


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
        f"Chunks:\n{json.dumps(partials, indent=2)}"
    )


def _chunk_text(text: str, max_words: int) -> list[str]:
    words = text.split()
    if len(words) <= max_words:
        return [text]
    chunks: list[str] = []
    for i in range(0, len(words), max_words):
        chunks.append(" ".join(words[i : i + max_words]))
    return chunks


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
            )
        except LLMError as e:
            raise DistillError(str(e)) from e
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
                )
            )
        except LLMError as e:
            raise DistillError(f"chunk {i + 1}/{len(chunks)} failed: {e}") from e

    try:
        consolidated = await client.chat_json(
            system=SYSTEM_PROMPT,
            user=_consolidate_prompt(meta, partials),
            response_schema_name="Distillation",
        )
    except LLMError as e:
        raise DistillError(f"consolidation failed: {e}") from e

    return Distillation.model_validate(consolidated)
