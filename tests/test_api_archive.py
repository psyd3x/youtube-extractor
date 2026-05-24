from fastapi.testclient import TestClient

from youtube_extractor.config import settings
from youtube_extractor.main import create_app
from youtube_extractor.store.catalog import append_entry


def test_archive_list_and_search(tmp_path, monkeypatch):
    # Redirect catalog by pointing settings at a tmp output_dir.
    monkeypatch.setattr(settings, "output_dir", tmp_path)
    cat = tmp_path / "catalog.ndjson"
    append_entry(
        cat,
        {
            "slug": "s1",
            "video_id": "v1",
            "title": "AI Talk",
            "channel": "C",
            "url": "https://y/watch?v=v1",
            "duration": 100,
            "extracted_at": 1.0,
            "md_path": "/x.md",
            "pdf_full_path": "/f.pdf",
            "pdf_lazy_path": "/l.pdf",
            "tags": ["youtube", "ai"],
            "topics": ["ai"],
            "people": [],
        },
    )
    app = create_app()
    client = TestClient(app)

    r = client.get("/archive")
    assert r.status_code == 200
    assert len(r.json()) == 1

    r = client.get("/archive?q=AI")
    assert r.status_code == 200
    assert len(r.json()) == 1

    r = client.get("/archive?q=nope")
    assert r.json() == []


def test_archive_orders_newest_first(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "output_dir", tmp_path)
    cat = tmp_path / "catalog.ndjson"
    for slug, ts in [("old", 1.0), ("newest", 3.0), ("mid", 2.0)]:
        append_entry(
            cat,
            {
                "slug": slug, "video_id": slug, "title": "T", "channel": "C",
                "url": "u", "duration": 1, "extracted_at": ts,
                "md_path": "/x.md", "pdf_full_path": "/f.pdf", "pdf_lazy_path": "/l.pdf",
                "tags": [], "topics": [], "people": [],
            },
        )
    app = create_app()
    client = TestClient(app)
    slugs = [r["slug"] for r in client.get("/archive").json()]
    assert slugs == ["newest", "mid", "old"]


def test_files_pdf_serve(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "output_dir", tmp_path)
    pdf = tmp_path / "s1-full.pdf"
    pdf.write_bytes(b"%PDF-1.4 minimal")
    app = create_app()
    client = TestClient(app)
    r = client.get("/pdfs/s1/full")
    assert r.status_code == 200
    assert r.content.startswith(b"%PDF-")


def test_files_md_serve(tmp_path, monkeypatch):
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setattr(settings, "obsidian_vault_path", vault)
    (vault / "s1.md").write_text("# Hi", encoding="utf-8")
    app = create_app()
    client = TestClient(app)
    r = client.get("/files/s1/md")
    assert r.status_code == 200
    assert "# Hi" in r.text


def test_files_404(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "output_dir", tmp_path)
    monkeypatch.setattr(settings, "obsidian_vault_path", tmp_path / "vault")
    app = create_app()
    client = TestClient(app)
    assert client.get("/pdfs/missing/full").status_code == 404
    assert client.get("/files/missing/md").status_code == 404


def test_files_pdf_invalid_kind(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "output_dir", tmp_path)
    app = create_app()
    client = TestClient(app)
    r = client.get("/pdfs/anything/banana")
    assert r.status_code == 400


def test_archive_delete_happy_path(tmp_path, monkeypatch):
    from youtube_extractor.api import jobs as jobs_module
    from youtube_extractor.models import JobRecord, JobStatus

    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setattr(settings, "output_dir", tmp_path)
    monkeypatch.setattr(settings, "obsidian_vault_path", vault)

    # Swap the API's jobs singleton to point at tmp.
    from youtube_extractor.store.jobs import JobStore
    fresh_jobs = JobStore(tmp_path / "jobs.ndjson")
    monkeypatch.setattr(jobs_module, "_jobs", fresh_jobs)

    # Seed catalog + artifacts + a matching job.
    md = vault / "slug-A.md"
    md.write_text("# md", encoding="utf-8")
    pdf_full = tmp_path / "slug-A-full.pdf"
    pdf_full.write_bytes(b"%PDF-1.7")
    pdf_lazy = tmp_path / "slug-A-lazy.pdf"
    pdf_lazy.write_bytes(b"%PDF-1.7")
    append_entry(
        tmp_path / "catalog.ndjson",
        {
            "slug": "slug-A", "video_id": "v", "title": "T", "channel": "C",
            "url": "https://y/watch?v=v", "duration": 1, "extracted_at": 1.0,
            "md_path": str(md), "pdf_full_path": str(pdf_full), "pdf_lazy_path": str(pdf_lazy),
            "tags": [], "topics": [], "people": [],
        },
    )
    fresh_jobs.put(JobRecord(id="j1", url="u", status=JobStatus.done, slug="slug-A"))

    app = create_app()
    client = TestClient(app)
    r = client.delete("/archive/slug-A")

    assert r.status_code == 200
    body = r.json()
    assert body["slug"] == "slug-A"
    assert body["md"] is True
    assert body["pdf_full"] is True
    assert body["pdf_lazy"] is True
    assert body["catalog_row"] is True
    assert body["jobs_removed"] == 1

    assert not md.exists()
    assert not pdf_full.exists()
    assert not pdf_lazy.exists()
    # Archive list reflects the deletion
    assert client.get("/archive").json() == []


def test_archive_delete_unknown_slug_returns_404(tmp_path, monkeypatch):
    from youtube_extractor.api import jobs as jobs_module
    from youtube_extractor.store.jobs import JobStore

    monkeypatch.setattr(settings, "output_dir", tmp_path)
    monkeypatch.setattr(settings, "obsidian_vault_path", tmp_path / "vault")
    monkeypatch.setattr(jobs_module, "_jobs", JobStore(tmp_path / "jobs.ndjson"))

    app = create_app()
    client = TestClient(app)
    r = client.delete("/archive/nope")
    assert r.status_code == 404
    assert "nope" in r.json()["detail"]
