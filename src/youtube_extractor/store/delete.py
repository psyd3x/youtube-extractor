from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from youtube_extractor.config import Settings
from youtube_extractor.store.atomic import rewrite_ndjson_filtered
from youtube_extractor.store.catalog import read_all
from youtube_extractor.store.jobs import JobStore


class ArchiveEntryNotFound(Exception):
    """Raised when delete_by_slug is called with a slug not in the catalog."""


@dataclass
class DeleteResult:
    slug: str
    md: bool
    pdf_full: bool
    pdf_lazy: bool
    catalog_row: bool
    jobs_removed: int


def _find_by_slug(catalog: Path, slug: str) -> dict | None:
    for row in read_all(catalog):
        if row.get("slug") == slug:
            return row
    return None


def _unlink_if_present(p: Path) -> bool:
    """Return True if the file existed and was removed, False if it was already gone."""
    try:
        p.unlink()
        return True
    except FileNotFoundError:
        return False


def delete_by_slug(settings: Settings, slug: str, jobs: JobStore) -> DeleteResult:
    """Hard-delete every artifact tied to ``slug``: the .md in the Obsidian vault,
    both PDFs in the output dir, the catalog row, and every jobs.ndjson entry whose
    latest state has the same slug. Returns a per-step report.

    Raises ``ArchiveEntryNotFound`` if the slug is not in the catalog. Anything else
    (disk full, permission denied during rewrite) propagates.

    On partial failure (e.g. catalog rewrite raises after unlinks succeed), files
    are gone but the catalog row remains; a re-run with the same slug recovers
    (md/pdf bools come back False, catalog_row True, jobs_removed 0 as appropriate).

    Caller must serialize concurrent calls — the catalog rewrite is single-writer
    per atomic.py's contract. The FastAPI route layer is the right place to add an
    asyncio.Lock if request concurrency ever matters in practice.
    """
    catalog = settings.output_dir / "catalog.ndjson"

    row = _find_by_slug(catalog, slug)
    if row is None:
        raise ArchiveEntryNotFound(slug)

    md_removed = _unlink_if_present(Path(row["md_path"]))
    pdf_full_removed = _unlink_if_present(Path(row["pdf_full_path"]))
    pdf_lazy_removed = _unlink_if_present(Path(row["pdf_lazy_path"]))

    catalog_removed = rewrite_ndjson_filtered(catalog, predicate=lambda r: r.get("slug") != slug)
    jobs_removed_ids = jobs.remove_by_slug(slug)

    return DeleteResult(
        slug=slug,
        md=md_removed,
        pdf_full=pdf_full_removed,
        pdf_lazy=pdf_lazy_removed,
        catalog_row=catalog_removed > 0,
        jobs_removed=len(jobs_removed_ids),
    )
