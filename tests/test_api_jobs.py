import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from youtube_extractor.api import jobs as jobs_mod
from youtube_extractor.main import create_app
from youtube_extractor.pipeline.distill import DistillError
from youtube_extractor.pipeline.orchestrator import PipelineResult
from youtube_extractor.store.jobs import JobStore


def _ok_result(tmp_path: Path) -> PipelineResult:
    md = tmp_path / "x.md"
    md.write_text("# x")
    full = tmp_path / "x-full.pdf"
    full.write_bytes(b"%PDF-")
    lazy = tmp_path / "x-lazy.pdf"
    lazy.write_bytes(b"%PDF-")
    return PipelineResult(
        slug="2024-01-15-abc-x",
        md_path=md,
        pdf_full_path=full,
        pdf_lazy_path=lazy,
    )


def test_post_job_creates_and_completes(tmp_path, monkeypatch):
    # Redirect the module-level JobStore to a tmp file so this test is hermetic.
    fresh_store = JobStore(tmp_path / "jobs.ndjson")
    monkeypatch.setattr(jobs_mod, "_jobs", fresh_store)

    with patch.object(
        jobs_mod, "run_pipeline", new=AsyncMock(return_value=_ok_result(tmp_path))
    ):
        app = create_app()
        client = TestClient(app)
        r = client.post("/jobs", json={"url": "https://youtu.be/dQw4w9WgXcQ"})
        assert r.status_code == 200
        body = r.json()
        assert "job_id" in body

        job_id = body["job_id"]
        # TestClient runs background tasks synchronously after response — no polling needed,
        # but we still poll defensively in case the implementation changes.
        for _ in range(20):
            g = client.get(f"/jobs/{job_id}")
            if g.status_code == 200 and g.json().get("status") in ("done", "failed"):
                break
            time.sleep(0.05)

        final = client.get(f"/jobs/{job_id}").json()
        assert final["status"] == "done"
        assert final["slug"] == "2024-01-15-abc-x"


def test_post_job_invalid_url():
    app = create_app()
    client = TestClient(app)
    r = client.post("/jobs", json={"url": "not a url"})
    assert r.status_code == 400
    body = r.json()
    # FastAPI wraps HTTPException(detail={...}) under "detail"
    detail = body.get("detail")
    assert isinstance(detail, dict)
    assert detail.get("error_code") == "INVALID_URL"


def test_get_unknown_job_404():
    app = create_app()
    client = TestClient(app)
    r = client.get("/jobs/job_does_not_exist")
    assert r.status_code == 404


def _run_failing_job(tmp_path, monkeypatch, exc) -> dict:
    fresh_store = JobStore(tmp_path / "jobs.ndjson")
    monkeypatch.setattr(jobs_mod, "_jobs", fresh_store)
    with patch.object(jobs_mod, "run_pipeline", new=AsyncMock(side_effect=exc)):
        app = create_app()
        client = TestClient(app)
        r = client.post("/jobs", json={"url": "https://youtu.be/dQw4w9WgXcQ"})
        job_id = r.json()["job_id"]
        return client.get(f"/jobs/{job_id}").json()


def test_distill_request_rejected_is_not_retryable(tmp_path, monkeypatch):
    """A 400 (context overflow) must surface its real code and NOT be marked retryable —
    retrying an oversized prompt fails identically. Regression for the HERMES_OFFLINE mislabel."""
    err = DistillError("chunk 1/2 failed: upstream 400: maximum context length", code="LLM_REQUEST_REJECTED")
    final = _run_failing_job(tmp_path, monkeypatch, err)
    assert final["status"] == "failed"
    assert final["stage"] == "distill"
    assert final["error_code"] == "LLM_REQUEST_REJECTED"
    assert final["retryable"] is False


def test_distill_unreachable_is_retryable(tmp_path, monkeypatch):
    err = DistillError("transport error to http://dgx:8000", code="LLM_UNREACHABLE")
    final = _run_failing_job(tmp_path, monkeypatch, err)
    assert final["status"] == "failed"
    assert final["error_code"] == "LLM_UNREACHABLE"
    assert final["retryable"] is True
