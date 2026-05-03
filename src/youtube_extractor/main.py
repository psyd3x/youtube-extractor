from __future__ import annotations

import logging

import httpx
from fastapi import FastAPI

from youtube_extractor import __version__
from youtube_extractor.api.archive import router as archive_router
from youtube_extractor.api.files import router as files_router
from youtube_extractor.api.jobs import router as jobs_router
from youtube_extractor.config import settings


def create_app() -> FastAPI:
    logging.basicConfig(level=settings.log_level)
    app = FastAPI(title="YouTube Extractor", version=__version__)
    app.include_router(jobs_router)
    app.include_router(archive_router)
    app.include_router(files_router)

    @app.get("/health")
    async def health() -> dict:
        # Best-effort LLM probe — don't block if it's slow.
        hermes_ok = False
        try:
            async with httpx.AsyncClient(timeout=2) as c:
                r = await c.get(f"{settings.llm_base_url.rstrip('/')}/v1/models")
                hermes_ok = r.status_code == 200
        except Exception:
            pass
        return {"status": "ok", "version": __version__, "hermes_reachable": hermes_ok}

    return app


def serve() -> None:
    """Entrypoint used by `youtube-extractor serve` and the launchd unit."""
    import uvicorn

    uvicorn.run(
        "youtube_extractor.main:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )
