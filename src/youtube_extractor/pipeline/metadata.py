from __future__ import annotations

import yt_dlp

from youtube_extractor.models import Metadata


class MetadataError(Exception):
    pass


def _format_date(yyyymmdd: str | None) -> str | None:
    if not yyyymmdd or len(yyyymmdd) != 8:
        return None
    return f"{yyyymmdd[0:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"


def fetch_metadata(video_id: str) -> Metadata:
    """Fetch video metadata via yt-dlp without downloading the video itself."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    opts = {"quiet": True, "skip_download": True, "no_warnings": True}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as e:
        raise MetadataError(f"yt-dlp could not fetch metadata for {video_id}: {e}") from e
    except Exception as e:
        raise MetadataError(f"unexpected metadata error: {e}") from e

    if not info:
        raise MetadataError("yt-dlp returned empty info")

    return Metadata(
        video_id=info.get("id", video_id),
        title=info.get("title", ""),
        channel=info.get("uploader") or info.get("channel") or "",
        duration_s=int(info.get("duration") or 0),
        published=_format_date(info.get("upload_date")),
        thumbnail_url=info.get("thumbnail"),
        description=info.get("description"),
    )
