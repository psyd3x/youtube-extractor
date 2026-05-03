from __future__ import annotations

from pathlib import Path
from threading import Lock

from youtube_extractor.models import JobRecord


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
