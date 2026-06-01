from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, field_validator


def _coerce_str_list(v: Any) -> list[str]:
    """Some LLMs return list-of-dict for fields we expect as list-of-str
    (e.g. references = [{title, url}] instead of ["title — url"]).
    Coerce dicts to formatted strings so the templates render cleanly."""
    if not isinstance(v, list):
        return v  # let pydantic raise
    out: list[str] = []
    for item in v:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict):
            title = item.get("title") or item.get("name") or ""
            url = item.get("url") or item.get("link") or item.get("href") or ""
            if title and url:
                out.append(f"{title} ({url})")
            elif title:
                out.append(str(title))
            elif url:
                out.append(str(url))
            else:
                # Generic dict with no title/url (e.g. config as {setting, value} or
                # {key, description}): join its scalar values as "v1: v2" rather than
                # dumping a raw dict repr into the rendered output.
                vals = [
                    str(x).strip()
                    for x in item.values()
                    if isinstance(x, (str, int, float)) and str(x).strip()
                ]
                out.append(": ".join(vals) if vals else str(item))
        else:
            out.append(str(item))
    return out


class Metadata(BaseModel):
    video_id: str
    title: str
    channel: str
    duration_s: int
    published: str | None = None
    thumbnail_url: str | None = None
    description: str | None = None


class TranscriptSegment(BaseModel):
    start: float
    dur: float
    text: str


class Transcript(BaseModel):
    segments: list[TranscriptSegment]
    full_text: str
    language: str | None = None
    source: Literal["official", "whisper"] = "official"


class Chapter(BaseModel):
    title: str
    summary: str
    key_points: list[str] = []
    quotes: list[str] = []


class FullDoc(BaseModel):
    chapters: list[Chapter] = []
    topics: list[str] = []
    people: list[str] = []
    references: list[str] = []

    @field_validator("topics", "people", "references", mode="before")
    @classmethod
    def _coerce_strings(cls, v: Any) -> list[str]:
        return _coerce_str_list(v)


class LazyDoc(BaseModel):
    key_points: list[str] = []
    summary_paragraph: str = ""


class Distillation(BaseModel):
    title: str
    tldr: str
    lazy: LazyDoc
    full: FullDoc


class Step(BaseModel):
    n: int
    action: str
    detail: str = ""
    command: str = ""
    prompt: str = ""

    # Some models (e.g. MiniMax-M2) emit null for an omitted optional string field
    # rather than dropping it; coerce None back to "" so a stepwise null doesn't fail.
    @field_validator("detail", "command", "prompt", mode="before")
    @classmethod
    def _none_to_str(cls, v: Any) -> str:
        return "" if v is None else v


class PromptItem(BaseModel):
    label: str
    text: str


class ResourceItem(BaseModel):
    label: str
    url: str = ""

    @field_validator("url", mode="before")
    @classmethod
    def _none_to_str(cls, v: Any) -> str:
        return "" if v is None else v


class InstructionsAndData(BaseModel):
    goal: str
    kind: Literal["tutorial", "mixed", "discussion"] = "tutorial"
    prerequisites: list[str] = []
    steps: list[Step] = []
    prompts: list[PromptItem] = []
    commands: list[str] = []
    resources: list[ResourceItem] = []
    config: list[str] = []
    notes: list[str] = []
    takeaways: list[str] = []  # usable know-how when there is no explicit workflow (discussion videos)
    vault_links: list[str] = []  # zk-steward Obsidian backlinks like "[[Topic]]"

    # Same defensive coercion as FullDoc: tolerate null (-> []) and list-of-dict
    # (-> formatted strings) for the plain-string lists, since served models vary
    # in how they emit these (MiniMax-M2 returns config as [{setting, value}, ...]).
    @field_validator(
        "prerequisites", "commands", "config", "notes", "takeaways", "vault_links",
        mode="before",
    )
    @classmethod
    def _coerce_strings(cls, v: Any) -> list[str]:
        if v is None:
            return []
        return _coerce_str_list(v)

    @field_validator("steps", "prompts", "resources", mode="before")
    @classmethod
    def _none_to_list(cls, v: Any) -> Any:
        return [] if v is None else v


class JobStatus(StrEnum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"
    partial_success = "partial_success"


class JobStage(StrEnum):
    metadata = "metadata"
    transcript = "transcript"
    distill = "distill"
    instructions = "instructions"
    render_md = "render_md"
    render_pdf = "render_pdf"
    store = "store"


class JobRecord(BaseModel):
    id: str
    url: str
    slug: str | None = None
    status: JobStatus
    stage: JobStage | None = None
    error_code: str | None = None
    error_message: str | None = None
    retryable: bool = True
    created_at: float | None = None
    updated_at: float | None = None
