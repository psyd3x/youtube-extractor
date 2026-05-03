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
