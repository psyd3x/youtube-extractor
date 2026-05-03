from __future__ import annotations

from pathlib import Path
from threading import Lock

from youtube_extractor.models import JobRecord
from youtube_extractor.store.atomic import rewrite_ndjson_filtered


class JobStore:
    """In-memory job dict mirrored to an append-only NDJSON for crash recovery."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._mem: dict[str, JobRecord] = {}
        self._lock = Lock()
        self._reload()

    def _reload(self) -> None:
        if not self.path.exists():
            return
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = JobRecord.model_validate_json(line)
                self._mem[rec.id] = rec
            except Exception:
                continue

    def put(self, job: JobRecord) -> None:
        with self._lock:
            self._mem[job.id] = job
            with self.path.open("a", encoding="utf-8") as f:
                f.write(job.model_dump_json() + "\n")

    def get(self, job_id: str) -> JobRecord | None:
        return self._mem.get(job_id)

    def remove_by_slug(self, slug: str) -> list[str]:
        """Remove every job whose latest state has the given slug.

        Drops the job from in-memory state AND rewrites the file to remove every
        row for those job ids (regardless of slug — covers earlier rows where slug
        may have been null). Returns the list of removed job ids.
        """
        with self._lock:
            ids_to_remove = [jid for jid, rec in self._mem.items() if rec.slug == slug]
            if not ids_to_remove:
                return []
            ids_set = set(ids_to_remove)
            rewrite_ndjson_filtered(self.path, predicate=lambda row: row.get("id") not in ids_set)
            for jid in ids_to_remove:
                self._mem.pop(jid, None)
            return ids_to_remove
