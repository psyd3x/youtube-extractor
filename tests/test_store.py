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


def test_jobstore_remove_by_slug(tmp_path):
    from youtube_extractor.store.jobs import JobStore

    store = JobStore(tmp_path / "jobs.ndjson")
    j1 = JobRecord(id="j1", url="u1", status=JobStatus.queued)
    store.put(j1)
    j1.status = JobStatus.running
    j1.slug = "slug-A"
    store.put(j1)
    j1.status = JobStatus.done
    store.put(j1)

    j2 = JobRecord(id="j2", url="u2", status=JobStatus.done, slug="slug-B")
    store.put(j2)

    j3 = JobRecord(id="j3", url="u3", status=JobStatus.failed)  # no slug
    store.put(j3)

    removed = store.remove_by_slug("slug-A")
    assert removed == ["j1"]

    # In-memory state expunged
    assert store.get("j1") is None
    assert store.get("j2") is not None
    assert store.get("j3") is not None

    # File rewritten — no rows for j1 remain even though one of its rows had slug=null
    lines = (tmp_path / "jobs.ndjson").read_text().strip().splitlines()
    assert all('"j1"' not in line for line in lines)
    assert any('"j2"' in line for line in lines)
    assert any('"j3"' in line for line in lines)


def test_jobstore_remove_by_slug_no_match(tmp_path):
    from youtube_extractor.store.jobs import JobStore

    store = JobStore(tmp_path / "jobs.ndjson")
    store.put(JobRecord(id="j1", url="u1", status=JobStatus.done, slug="slug-X"))

    removed = store.remove_by_slug("slug-Z")
    assert removed == []
    assert store.get("j1") is not None
