from __future__ import annotations

import gc
import tempfile
import threading
from pathlib import Path

import yt_dlp

from youtube_extractor.config import settings
from youtube_extractor.models import Transcript, TranscriptSegment

try:
    import mlx.core as mx
    import mlx_whisper
    from mlx_whisper.transcribe import ModelHolder
    _MLX_AVAILABLE = True
except ImportError:  # pragma: no cover - platform/extra dependent
    mx = None
    mlx_whisper = None
    ModelHolder = None
    _MLX_AVAILABLE = False


class WhisperError(Exception):
    pass


# Serialize whisper so at most one model is resident at a time (max_concurrent_jobs=2).
_whisper_lock = threading.Lock()


def _download_audio(video_id: str, dest_dir: Path) -> Path:
    url = f"https://www.youtube.com/watch?v={video_id}"
    opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "format": "bestaudio/best",
        "outtmpl": str(dest_dir / "%(id)s.%(ext)s"),
    }
    if settings.yt_dlp_cookies_browser:
        opts["cookiesfrombrowser"] = (settings.yt_dlp_cookies_browser,)
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            return Path(ydl.prepare_filename(info))
    except Exception as e:
        raise WhisperError(f"audio download failed for {video_id}: {e}") from e


def _transcribe(audio_path: Path) -> tuple[list[TranscriptSegment], str, str | None]:
    result = mlx_whisper.transcribe(str(audio_path), path_or_hf_repo=settings.whisper_model)
    full_text = (result.get("text") or "").strip()
    if not full_text:
        raise WhisperError("whisper produced an empty transcript")
    segments = [
        TranscriptSegment(
            start=float(s["start"]),
            dur=float(s["end"]) - float(s["start"]),
            text=s["text"],
        )
        for s in result.get("segments", [])
    ]
    return segments, full_text, result.get("language")


def _release_model() -> None:
    """Drop the in-memory model so idle RAM returns to ~0 between fallbacks."""
    if ModelHolder is not None:
        ModelHolder.model = None
        ModelHolder.model_path = None
    gc.collect()
    if mx is not None:
        mx.clear_cache()


def whisper_transcript(video_id: str) -> Transcript:
    """Download a video's audio and transcribe it locally with mlx-whisper.

    Fallback for when no official transcript exists. The model is loaded on demand
    and released afterwards (idle RAM ~0); a module lock keeps at most one
    transcription in flight at a time.
    """
    if not _MLX_AVAILABLE:
        raise WhisperError(
            "mlx-whisper not available (install the '.[whisper]' extra on Apple Silicon)"
        )

    with _whisper_lock, tempfile.TemporaryDirectory(prefix="yte-whisper-") as td:
        audio_path = _download_audio(video_id, Path(td))
        try:
            segments, full_text, language = _transcribe(audio_path)
        finally:
            _release_model()

    return Transcript(
        segments=segments, full_text=full_text, language=language, source="whisper"
    )
