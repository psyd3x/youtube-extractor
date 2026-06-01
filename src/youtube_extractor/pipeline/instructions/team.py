"""Multi-persona extraction engine: transcript -> InstructionsAndData.

Mirrors distill.py's conventions (LLMClient from settings, client.chat_json with a
response schema, chunk-then-consolidate, explicit context-budget comments) but adds a
parallel multi-agent pass: per chunk an Architect (procedure skeleton) and a Synthesizer
(know-how) run concurrently, an Orchestrator folds all partials into one draft, a Writer
refines it, a Reality Checker validates it, and a ZK Steward adds Obsidian backlinks.

Pure: extract_instructions(meta, transcript) -> InstructionsAndData. No global state.
"""

from __future__ import annotations

import asyncio
import json

from youtube_extractor.config import settings
from youtube_extractor.llm.client import LLMClient, LLMError
from youtube_extractor.models import InstructionsAndData, Metadata, Transcript
from youtube_extractor.pipeline.instructions.personas import (
    ARCHITECT_SYS,
    ORCHESTRATOR_SYS,
    REALITY_CHECKER_SYS,
    SYNTHESIZER_SYS,
    WRITER_SYS,
    ZK_STEWARD_SYS,
)

# Words per chunk. Smaller than distill's 12000 to leave headroom: each instructions
# call carries a persona system prompt (~1200 tokens) on top of the transcript chunk and
# must still leave room for the JSON output in qwen3-30b's 32k window. 10000 words ≈ 18k
# prompt tokens + ~1.5k persona, leaving ~12k for the response.
INSTRUCTIONS_CHUNK_WORDS = 10000

# Max characters of serialized partials packed into one orchestrator merge call. Same
# overflow concern as distill: a long video yields many partials and dumping them all into
# one prompt blows the window. ~4 chars/token, so 60k chars ≈ 15k tokens, leaving the
# window open for the merged-JSON response. Partials beyond this are folded over rounds.
MAX_MERGE_CHARS = 60_000

# Generated once; passed as a structured-output schema so the final-shape calls are
# guaranteed to match InstructionsAndData regardless of which model serves the endpoint.
_INSTRUCTIONS_SCHEMA = InstructionsAndData.model_json_schema()


class InstructionsError(Exception):
    def __init__(self, message: str, *, code: str = "INSTRUCTIONS_FAILED") -> None:
        super().__init__(message)
        self.code = code


# Small intermediate schemas keep the per-chunk persona calls cheap and focused; only the
# final-shape calls (orchestrator merge onward) use the full InstructionsAndData schema.
_ARCHITECT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "prerequisites": {"type": "array", "items": {"type": "string"}},
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "n": {"type": "integer"},
                    "action": {"type": "string"},
                    "detail": {"type": "string"},
                    "command": {"type": "string"},
                    "prompt": {"type": "string"},
                },
                "required": ["n", "action"],
            },
        },
        "commands": {"type": "array", "items": {"type": "string"}},
        "prompts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"label": {"type": "string"}, "text": {"type": "string"}},
                "required": ["label", "text"],
            },
        },
        "resources": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"label": {"type": "string"}, "url": {"type": "string"}},
                "required": ["label"],
            },
        },
        "config": {"type": "array", "items": {"type": "string"}},
    },
}

_SYNTHESIZER_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "takeaways": {"type": "array", "items": {"type": "string"}},
        "notes": {"type": "array", "items": {"type": "string"}},
    },
}

_ZK_SCHEMA: dict = {
    "type": "object",
    "properties": {"vault_links": {"type": "array", "items": {"type": "string"}}},
}


def _chunk_text(text: str, max_words: int) -> list[str]:
    words = text.split()
    if len(words) <= max_words:
        return [text]
    return [" ".join(words[i : i + max_words]) for i in range(0, len(words), max_words)]


def _batch_partials(partials: list[dict], max_chars: int) -> list[list[dict]]:
    """Greedily pack partials into batches whose compact-JSON size stays under max_chars.

    If no two adjacent partials fit together, falls back to pairwise batches so a merge
    round always makes progress. Mirrors distill._batch_partials.
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


def _meta_header(meta: Metadata) -> str:
    return (
        f"Title: {meta.title}\nChannel: {meta.channel}\nDuration: {meta.duration_s}s\n"
        f"Description: {(meta.description or '')[:500]}\n"
    )


def _architect_prompt(meta: Metadata, chunk: str, idx: int, total: int) -> str:
    note = (
        f"\nThis is chunk {idx + 1} of {total} of a long transcript. Cover only the steps in "
        "this chunk; merging happens later."
        if total > 1
        else ""
    )
    return (
        f"{_meta_header(meta)}{note}\n\nTranscript:\n{chunk}\n\n"
        "Recover the ordered procedure from this transcript. Return JSON: "
        "{prerequisites[], steps:[{n, action, detail, command, prompt}], commands[], "
        "prompts:[{label, text}], resources:[{label, url}], config[]}. "
        "Commands and prompts MUST be verbatim from the transcript. Invent nothing."
    )


def _synthesizer_prompt(meta: Metadata, chunk: str, idx: int, total: int) -> str:
    note = (
        f"\nThis is chunk {idx + 1} of {total} of a long transcript. Cover only this chunk."
        if total > 1
        else ""
    )
    return (
        f"{_meta_header(meta)}{note}\n\nTranscript:\n{chunk}\n\n"
        "Extract usable know-how. Return JSON: {takeaways[], notes[]}. "
        "Each item a crisp standalone statement drawn strictly from this chunk. Invent nothing."
    )


def _merge_prompt(meta: Metadata, arch: list[dict], synth: list[dict]) -> str:
    return (
        f"Fold these per-chunk partials of '{meta.title}' into ONE InstructionsAndData.\n"
        f"Architect partials (procedure skeletons, in order):\n{json.dumps(arch)}\n\n"
        f"Synthesizer partials (know-how):\n{json.dumps(synth)}\n\n"
        "Concatenate steps in order and renumber n consecutively from 1; dedupe prerequisites, "
        "commands, prompts, resources, config; merge takeaways and notes. Decide kind: "
        "'tutorial' (clear end-to-end procedure), 'discussion' (commentary/know-how, no real "
        "workflow), or 'mixed'. Write one clear goal sentence. Return the full InstructionsAndData "
        "JSON. Evidence only — invent nothing."
    )


def _merge_drafts_prompt(meta: Metadata, drafts: list[dict]) -> str:
    return (
        f"Merge these {len(drafts)} partial InstructionsAndData drafts of '{meta.title}' into one. "
        "Concatenate steps in order and renumber n from 1; dedupe all list fields; reconcile goal "
        "and kind. Return the full InstructionsAndData JSON. Evidence only — invent nothing.\n\n"
        f"Drafts:\n{json.dumps(drafts)}"
    )


def _writer_prompt(meta: Metadata, draft: dict) -> str:
    return (
        f"Refine this InstructionsAndData for '{meta.title}'.\n{json.dumps(draft)}\n\n"
        "Rewrite each step action as a short second-person imperative; keep detail concise. "
        "Command and prompt fields MUST stay verbatim — do not alter literal command or prompt "
        "text. Ensure steps are ordered and n is consecutive from 1. Fill resources and config "
        "only with items present in the draft. Return the full InstructionsAndData JSON."
    )


def _reality_prompt(meta: Metadata, draft: dict, transcript_text: str) -> str:
    # Bound the transcript slice so the validation prompt stays inside the window.
    excerpt = transcript_text[:48_000]
    return (
        f"Validate this InstructionsAndData for '{meta.title}' against the transcript.\n"
        f"Draft:\n{json.dumps(draft)}\n\nTranscript (may be truncated):\n{excerpt}\n\n"
        "Confirm every step/command/prompt/resource/config is supported by the transcript. Do NOT "
        "add new steps, commands, or resources. If the procedure is incomplete or something is "
        "referenced but never explained, append a concrete gap statement to notes. Return the same "
        "InstructionsAndData JSON, unchanged except for any appended notes."
    )


def _zk_prompt(meta: Metadata, draft: dict) -> str:
    return (
        f"From this InstructionsAndData for '{meta.title}', produce Obsidian backlinks for the key "
        f"concepts, tools, technologies, people, and sources.\n{json.dumps(draft)}\n\n"
        'Return JSON: {vault_links: ["[[Topic]]", ...]}. One concept per link, Title Case, '
        "5-15 high-signal links. Invent nothing not present in the material."
    )


def _verbatim_guard(draft: dict, transcript_text: str) -> dict:
    """Deterministic reality guard: drop fabricated resources/commands.

    - Drop any ResourceItem whose url is non-empty but does not appear verbatim in the
      transcript.
    - Drop top-level commands and clear per-step command fields not found verbatim.
    Never invents — only removes ungrounded content.
    """
    haystack = transcript_text

    resources = draft.get("resources")
    if isinstance(resources, list):
        kept = []
        for r in resources:
            url = (r or {}).get("url", "") if isinstance(r, dict) else ""
            if url and url not in haystack:
                # Ungrounded URL: keep the label as a resource but strip the fabricated url.
                r = {**r, "url": ""}
            kept.append(r)
        draft["resources"] = kept

    commands = draft.get("commands")
    if isinstance(commands, list):
        draft["commands"] = [c for c in commands if isinstance(c, str) and c in haystack]

    steps = draft.get("steps")
    if isinstance(steps, list):
        for s in steps:
            if isinstance(s, dict):
                cmd = s.get("command", "")
                if cmd and cmd not in haystack:
                    s["command"] = ""
    return draft


async def _gather_chunk_partials(
    client: LLMClient, meta: Metadata, chunks: list[str]
) -> tuple[list[dict], list[dict]]:
    """Per chunk, run Architect and Synthesizer concurrently; collect both partial lists."""
    arch_partials: list[dict] = []
    synth_partials: list[dict] = []
    total = len(chunks)
    for i, chunk in enumerate(chunks):
        arch, synth = await asyncio.gather(
            client.chat_json(
                system=ARCHITECT_SYS,
                user=_architect_prompt(meta, chunk, i, total),
                response_schema_name="ArchitectPartial",
                schema=_ARCHITECT_SCHEMA,
            ),
            client.chat_json(
                system=SYNTHESIZER_SYS,
                user=_synthesizer_prompt(meta, chunk, i, total),
                response_schema_name="SynthesizerPartial",
                schema=_SYNTHESIZER_SCHEMA,
            ),
        )
        arch_partials.append(arch)
        synth_partials.append(synth)
    return arch_partials, synth_partials


async def _merge(
    client: LLMClient, meta: Metadata, arch: list[dict], synth: list[dict]
) -> dict:
    """Orchestrator merge: fold all chunk partials into one draft InstructionsAndData.

    Batches architect partials under the context budget; if many, merges the resulting
    drafts over multiple rounds (mirrors distill's fold loop).
    """
    arch_batches = _batch_partials(arch, MAX_MERGE_CHARS)
    if len(arch_batches) == 1:
        return await client.chat_json(
            system=ORCHESTRATOR_SYS,
            user=_merge_prompt(meta, arch, synth),
            response_schema_name="InstructionsAndData",
            schema=_INSTRUCTIONS_SCHEMA,
        )

    # Many partials: synthesizer know-how folds into the first batch only so it is not
    # duplicated across drafts; remaining batches contribute steps/structure.
    drafts: list[dict] = []
    for bi, batch in enumerate(arch_batches):
        drafts.append(
            await client.chat_json(
                system=ORCHESTRATOR_SYS,
                user=_merge_prompt(meta, batch, synth if bi == 0 else []),
                response_schema_name="InstructionsAndData",
                schema=_INSTRUCTIONS_SCHEMA,
            )
        )

    while len(drafts) > 1:
        next_drafts: list[dict] = []
        for batch in _batch_partials(drafts, MAX_MERGE_CHARS):
            if len(batch) == 1:
                next_drafts.append(batch[0])
                continue
            next_drafts.append(
                await client.chat_json(
                    system=ORCHESTRATOR_SYS,
                    user=_merge_drafts_prompt(meta, batch),
                    response_schema_name="InstructionsAndData",
                    schema=_INSTRUCTIONS_SCHEMA,
                )
            )
        drafts = next_drafts
    return drafts[0]


async def extract_instructions(
    meta: Metadata, transcript: Transcript
) -> InstructionsAndData:
    """Extract a build-ready InstructionsAndData from a transcript via a multi-persona team.

    Flow: chunk -> per-chunk (Architect || Synthesizer) -> Orchestrator merge -> Writer
    refine -> Reality check (deterministic guard + Reality Checker) -> ZK Steward links.
    Raises InstructionsError on any LLMError.
    """
    client = LLMClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        timeout_s=settings.llm_timeout_s,
    )

    chunks = _chunk_text(transcript.full_text, INSTRUCTIONS_CHUNK_WORDS)

    try:
        # 1-2. Per chunk: Architect (procedure) + Synthesizer (know-how) concurrently.
        arch_partials, synth_partials = await _gather_chunk_partials(client, meta, chunks)

        # 3. Orchestrator merge -> single draft, also decides kind.
        draft = await _merge(client, meta, arch_partials, synth_partials)

        # 4. Writer pass: imperative voice, verbatim commands/prompts, fill resources/config.
        draft = await client.chat_json(
            system=WRITER_SYS,
            user=_writer_prompt(meta, draft),
            response_schema_name="InstructionsAndData",
            schema=_INSTRUCTIONS_SCHEMA,
        )

        # 5a. Deterministic reality guard: drop ungrounded urls/commands (no LLM, never invents).
        draft = _verbatim_guard(draft, transcript.full_text)

        # 5b. Reality Checker: validate completeness, append gaps to notes.
        draft = await client.chat_json(
            system=REALITY_CHECKER_SYS,
            user=_reality_prompt(meta, draft, transcript.full_text),
            response_schema_name="InstructionsAndData",
            schema=_INSTRUCTIONS_SCHEMA,
        )
        # Re-apply the deterministic guard in case the checker reintroduced content.
        draft = _verbatim_guard(draft, transcript.full_text)

        # 6. ZK Steward: Obsidian wikilinks for key concepts/tools/people/sources.
        zk = await client.chat_json(
            system=ZK_STEWARD_SYS,
            user=_zk_prompt(meta, draft),
            response_schema_name="ZkLinks",
            schema=_ZK_SCHEMA,
        )
    except LLMError as e:
        raise InstructionsError(str(e), code=e.code) from e

    links = zk.get("vault_links")
    if isinstance(links, list):
        draft["vault_links"] = links

    return InstructionsAndData.model_validate(draft)
