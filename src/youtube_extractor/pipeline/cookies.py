from __future__ import annotations

import contextlib
import logging
import os
import shutil
import tempfile
from collections.abc import Iterator
from pathlib import Path

from youtube_extractor.config import settings

log = logging.getLogger(__name__)


@contextlib.contextmanager
def cookie_opts() -> Iterator[dict]:
    """yt-dlp cookie options for one call.

    yt_dlp_cookies_file (if set and present) is copied to a private temp file for the
    call, because yt-dlp rewrites its cookiefile on close and concurrent jobs would
    race on a shared file. Otherwise falls back to yt_dlp_cookies_browser.
    """
    src = Path(settings.yt_dlp_cookies_file).expanduser() if settings.yt_dlp_cookies_file else None
    if src is not None and not src.is_file():
        log.warning("yt-dlp cookies file %s not found; falling back", src)
        src = None
    if src is None:
        if settings.yt_dlp_cookies_browser:
            yield {"cookiesfrombrowser": (settings.yt_dlp_cookies_browser,)}
        else:
            yield {}
        return
    fd, tmp = tempfile.mkstemp(prefix="ytdlp-cookies-", suffix=".txt")
    os.close(fd)
    try:
        shutil.copyfile(src, tmp)
        yield {"cookiefile": tmp}
    finally:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
