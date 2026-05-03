from __future__ import annotations

import time

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
)

from youtube_extractor.config import settings
from youtube_extractor.models import Transcript, TranscriptSegment


class NoTranscriptError(Exception):
    pass


# youtube-transcript-api >= 1.0 dropped the legacy classmethod
# ``YouTubeTranscriptApi.get_transcript``. We restore a thin compatibility shim
# so that callers (and tests that patch this attribute) keep a stable surface.
if not hasattr(YouTubeTranscriptApi, "get_transcript"):

    def _compat_get_transcript(video_id, languages=("en",)):  # pragma: no cover - thin shim
        fetched = YouTubeTranscriptApi().fetch(video_id, languages=languages)
        return [
            {"text": s.text, "start": s.start, "duration": s.duration}
            for s in fetched.snippets
        ]

    YouTubeTranscriptApi.get_transcript = staticmethod(_compat_get_transcript)


def fetch_transcript(video_id: str) -> Transcript:
    """Fetch the official transcript for a video, with bounded retries on transient errors."""
    last_exc: Exception | None = None
    delay = 1.0
    entries = None
    for attempt in range(settings.transcript_retries):
        try:
            entries = YouTubeTranscriptApi.get_transcript(video_id)
            break
        except (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable) as e:
            raise NoTranscriptError(f"no official transcript for {video_id}: {e}") from e
        except Exception as e:
            last_exc = e
            if attempt < settings.transcript_retries - 1:
                time.sleep(delay)
                delay *= 2

    if entries is None:
        raise NoTranscriptError(
            f"transcript fetch failed after retries: {last_exc}"
        ) from last_exc

    segments = [
        TranscriptSegment(start=float(e["start"]), dur=float(e["duration"]), text=e["text"])
        for e in entries
    ]
    full_text = " ".join(s.text for s in segments)
    return Transcript(segments=segments, full_text=full_text, language="en", source="official")
