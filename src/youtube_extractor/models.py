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
                out.append(str(item))
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
