from youtube_extractor.models import JobRecord, JobStatus
from youtube_extractor.store.catalog import append_entry, find_by_video_id, read_all
from youtube_extractor.store.jobs import JobStore
from youtube_extractor.store.search import search_entries

SAMPLE = {
    "slug": "2024-01-15-abc-foo",
    "video_id": "abc",
    "title": "Foo",
    "channel": "Bar",
    "url": "https://y/watch?v=abc",
    "duration": 600,
    "extracted_at": 1700000000.0,
    "md_path": "/v/foo.md",
    "pdf_full_path": "/o/foo-full.pdf",
    "pdf_lazy_path": "/o/foo-lazy.pdf",
    "tags": ["youtube"],
    "topics": ["ai"],
    "people": [],
}


def test_append_and_read(tmp_path):
    p = tmp_path / "catalog.ndjson"
    append_entry(p, SAMPLE)
    rows = read_all(p)
    assert len(rows) == 1
    assert rows[0]["title"] == "Foo"


def test_find_by_video_id(tmp_path):
    p = tmp_path / "catalog.ndjson"
    append_entry(p, SAMPLE)
    found = find_by_video_id(p, "abc")
    assert found and found["slug"] == SAMPLE["slug"]
    missing = find_by_video_id(p, "zzz")
    assert missing is None


def test_search_substring(tmp_path):
    p = tmp_path / "catalog.ndjson"
    append_entry(p, SAMPLE)
    append_entry(p, {**SAMPLE, "slug": "2024-01-16-def-bar", "video_id": "def", "title": "Other", "topics": ["crypto"]})
    rows = search_entries(p, "ai")
    assert len(rows) == 1
    assert rows[0]["video_id"] == "abc"
    rows = search_entries(p, "")
    assert len(rows) == 2


def test_jobstore_lifecycle(tmp_path):
    store = JobStore(tmp_path / "jobs.ndjson")
    job = JobRecord(id="j1", url="u", status=JobStatus.queued)
    store.put(job)
    fetched = store.get("j1")
    assert fetched and fetched.status == JobStatus.queued
    job.status = JobStatus.done
    store.put(job)
    assert store.get("j1").status == JobStatus.done
    lines = (tmp_path / "jobs.ndjson").read_text().strip().splitlines()
    assert len(lines) == 2
