import pytest

from youtube_extractor.config import settings
from youtube_extractor.models import JobRecord, JobStatus
from youtube_extractor.store.catalog import append_entry
from youtube_extractor.store.delete import (
    ArchiveEntryNotFound,
    DeleteResult,
    delete_by_slug,
)
from youtube_extractor.store.jobs import JobStore


def _setup(tmp_path, monkeypatch):
    """Point settings into tmp_path and return (vault, output_dir, jobs_store)."""
    vault = tmp_path / "vault"
    output = tmp_path / "output"
    vault.mkdir()
    output.mkdir()
    monkeypatch.setattr(settings, "obsidian_vault_path", vault)
    monkeypatch.setattr(settings, "output_dir", output)
    jobs_store = JobStore(output / "jobs.ndjson")
    return vault, output, jobs_store


def _seed_archive_row(catalog, vault, output, *, slug="2024-aaa-foo"):
    md = vault / f"{slug}.md"
    md.write_text("# md", encoding="utf-8")
    pdf_full = output / f"{slug}-full.pdf"
    pdf_full.write_bytes(b"%PDF-1.7 full")
    pdf_lazy = output / f"{slug}-lazy.pdf"
    pdf_lazy.write_bytes(b"%PDF-1.7 lazy")
    append_entry(
        catalog,
        {
            "slug": slug,
            "video_id": "aaa",
            "title": "Foo",
            "channel": "C",
            "url": "https://y/watch?v=aaa",
            "duration": 100,
            "extracted_at": 1.0,
            "md_path": str(md),
            "pdf_full_path": str(pdf_full),
            "pdf_lazy_path": str(pdf_lazy),
            "tags": [],
            "topics": [],
            "people": [],
        },
    )
    return md, pdf_full, pdf_lazy


def test_delete_happy_path(tmp_path, monkeypatch):
    vault, output, jobs = _setup(tmp_path, monkeypatch)
    catalog = output / "catalog.ndjson"
    md, pdf_full, pdf_lazy = _seed_archive_row(catalog, vault, output, slug="slug-A")

    # Two jobs tied to slug-A, one to slug-B
    j1 = JobRecord(id="j1", url="u", status=JobStatus.done, slug="slug-A")
    j2 = JobRecord(id="j2", url="u2", status=JobStatus.done, slug="slug-A")
    j3 = JobRecord(id="j3", url="u3", status=JobStatus.done, slug="slug-B")
    jobs.put(j1)
    jobs.put(j2)
    jobs.put(j3)

    result = delete_by_slug(settings, "slug-A", jobs)

    assert isinstance(result, DeleteResult)
    assert result.slug == "slug-A"
    assert result.md is True
    assert result.pdf_full is True
    assert result.pdf_lazy is True
    assert result.catalog_row is True
    assert result.jobs_removed == 2

    # Files gone
    assert not md.exists()
    assert not pdf_full.exists()
    assert not pdf_lazy.exists()

    # Catalog rewritten with no slug-A row
    rows = catalog.read_text(encoding="utf-8").splitlines()
    assert all('"slug-A"' not in line for line in rows)

    # Other job survives
    assert jobs.get("j3") is not None
    assert jobs.get("j1") is None
    assert jobs.get("j2") is None


def test_delete_missing_slug_raises(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    with pytest.raises(ArchiveEntryNotFound):
        delete_by_slug(settings, "does-not-exist", JobStore(tmp_path / "no.ndjson"))


def test_delete_artifact_files_already_missing(tmp_path, monkeypatch):
    vault, output, jobs = _setup(tmp_path, monkeypatch)
    catalog = output / "catalog.ndjson"
    md, pdf_full, pdf_lazy = _seed_archive_row(catalog, vault, output, slug="slug-A")
    md.unlink()  # md gone but catalog row references it

    result = delete_by_slug(settings, "slug-A", jobs)

    assert result.md is False
    assert result.pdf_full is True
    assert result.pdf_lazy is True
    assert result.catalog_row is True
    assert result.jobs_removed == 0
    # PDFs still got removed
    assert not pdf_full.exists()
    assert not pdf_lazy.exists()


def test_delete_atomic_rewrite_preserves_other_rows(tmp_path, monkeypatch):
    vault, output, jobs = _setup(tmp_path, monkeypatch)
    catalog = output / "catalog.ndjson"
    _seed_archive_row(catalog, vault, output, slug="slug-A")
    _seed_archive_row(catalog, vault, output, slug="slug-B")
    _seed_archive_row(catalog, vault, output, slug="slug-C")

    delete_by_slug(settings, "slug-B", jobs)

    text = catalog.read_text(encoding="utf-8")
    assert '"slug-A"' in text
    assert '"slug-B"' not in text
    assert '"slug-C"' in text
