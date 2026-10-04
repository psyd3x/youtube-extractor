from __future__ import annotations

import asyncio
import time
import uuid

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel

from youtube_extractor.config import settings
from youtube_extractor.models import JobRecord, JobStage, JobStatus
from youtube_extractor.pipeline.distill import DistillError
from youtube_extractor.pipeline.metadata import MetadataError
from youtube_extractor.pipeline.orchestrator import run_pipeline
from youtube_extractor.pipeline.transcript import NoTranscriptError
from youtube_extractor.pipeline.url import InvalidYouTubeUrl, extract_video_id
from youtube_extractor.store.jobs import JobStore

router = APIRouter()
_jobs = JobStore(settings.output_dir / "jobs.ndjson")
_semaphore = asyncio.Semaphore(settings.max_concurrent_jobs)

# A distill failure is retryable unless its cause is deterministic — a 4xx the LLM server
# will reject identically on replay (e.g. a prompt over the context window). Keyed by the
# code carried on DistillError; unknown codes default to retryable.
_DISTILL_RETRYABLE = {
    "LLM_UNREACHABLE": True,  # server may come back
    "LLM_UPSTREAM_ERROR": True,  # 5xx — transient
    "LLM_REQUEST_REJECTED": False,  # 4xx — deterministic
    "LLM_BAD_JSON": True,  # model nondeterminism — a replay may parse
}


class JobCreateBody(BaseModel):
    url: str


@router.post("/jobs")
async def create_job(body: JobCreateBody, bg: BackgroundTasks) -> dict:
    try:
        extract_video_id(body.url)
    except InvalidYouTubeUrl as e:
        raise HTTPException(
            status_code=400,
            detail={"error": "invalid url", "error_code": "INVALID_URL", "error_message": str(e)},
        ) from e

    # A second submit of a video that is still queued/running would run the whole
    # pipeline twice (the catalog short-circuit only sees finished entries). Hand back
    # the in-flight job instead.
    for rec in _jobs.all():
        if rec.status in (JobStatus.queued, JobStatus.running) and _same_video(rec.url, body.url):
            return {"job_id": rec.id, "status": rec.status.value, "deduplicated": True}

    job_id = "job_" + uuid.uuid4().hex[:12]
    rec = JobRecord(
        id=job_id, url=body.url, status=JobStatus.queued,
        created_at=time.time(), updated_at=time.time(),
    )
    _jobs.put(rec)
    bg.add_task(_run, job_id, body.url)
    return {"job_id": job_id, "status": rec.status.value}


@router.get("/jobs")
async def list_jobs(since_s: int = 86_400) -> list[dict]:
    """Jobs a UI should show after a reload: everything queued/running, plus jobs that
    finished in the last `since_s` seconds (failures and done-with-warnings included).
    Newest first."""
    cutoff = time.time() - since_s
    out = [
        _view(r)
        for r in _jobs.all()
        if r.status in (JobStatus.queued, JobStatus.running) or (r.updated_at or 0) >= cutoff
    ]
    return sorted(out, key=lambda r: r.get("created_at") or 0, reverse=True)


def _same_video(a: str, b: str) -> bool:
    try:
        return extract_video_id(a) == extract_video_id(b)
    except InvalidYouTubeUrl:
        return False


def _view(rec: JobRecord) -> dict:
    out = rec.model_dump(mode="json")
    if rec.status == JobStatus.failed and rec.retryable:
        out["retry_url"] = f"/jobs/{rec.id}/retry"
    return out


@router.get("/jobs/{job_id}")
async def get_job(job_id: str) -> dict:
    rec = _jobs.get(job_id)
    if not rec:
        raise HTTPException(status_code=404, detail="job not found")
    return _view(rec)


@router.post("/jobs/{job_id}/retry")
async def retry_job(job_id: str, bg: BackgroundTasks) -> dict:
    rec = _jobs.get(job_id)
    if not rec or not rec.retryable:
        raise HTTPException(status_code=400, detail="not retryable")
    rec.status = JobStatus.queued
    rec.error_code = None
    rec.error_message = None
    rec.warnings = []
    rec.updated_at = time.time()
    _jobs.put(rec)
    bg.add_task(_run, job_id, rec.url)
    return {"job_id": job_id, "status": rec.status.value}


async def _run(job_id: str, url: str) -> None:
    async with _semaphore:
        rec = _jobs.get(job_id)
        if not rec:
            return
        rec.status = JobStatus.running
        rec.updated_at = time.time()
        _jobs.put(rec)

        def _on_stage(stage: JobStage) -> None:
            # Heartbeat: advance the record as each pipeline stage begins so a long job
            # (e.g. a multi-hour whisper transcription) keeps moving updated_at instead
            # of looking hung.
            rec.stage = stage
            rec.updated_at = time.time()
            _jobs.put(rec)

        try:
            result = await run_pipeline(
                url=url,
                vault_dir=settings.obsidian_vault_path,
                output_dir=settings.output_dir,
                on_stage=_on_stage,
            )
            rec.status = JobStatus.done
            rec.slug = result.slug
            rec.warnings = list(result.warnings)
            rec.updated_at = time.time()
            _jobs.put(rec)
        except InvalidYouTubeUrl as e:
            _fail(rec, JobStage.metadata, "INVALID_URL", str(e), retryable=False)
        except MetadataError as e:
            _fail(rec, JobStage.metadata, "VIDEO_UNAVAILABLE", str(e), retryable=True)
        except NoTranscriptError as e:
            _fail(rec, JobStage.transcript, "NO_TRANSCRIPT", str(e), retryable=False)
        except DistillError as e:
            _fail(
                rec,
                JobStage.distill,
                e.code,
                str(e),
                retryable=_DISTILL_RETRYABLE.get(e.code, True),
            )
        except Exception as e:
            _fail(rec, None, "UNKNOWN", str(e), retryable=True)


def _fail(rec: JobRecord, stage: JobStage | None, code: str, msg: str, retryable: bool) -> None:
    rec.status = JobStatus.failed
    rec.stage = stage
    rec.error_code = code
    rec.error_message = msg
    rec.retryable = retryable
    rec.updated_at = time.time()
    _jobs.put(rec)
