---
title: Whisper Transcript Fallback — Design Spec
project: youtube-extractor
type: design-spec
status: approved
date: 2026-05-24
tags: [youtube-extractor, transcript, whisper, mlx, fallback, design-spec]
description: When a video has no official YouTube captions, transcribe its audio locally with mlx-whisper (large-v3-turbo, on the Apple Silicon GPU) so the pipeline can still produce the .md + PDFs. Fallback only — official captions still take priority. Model is lazy-loaded on demand and released after use, so idle RAM cost is ~0.
---

# Whisper Transcript Fallback — Design Spec

Successor to [[2026-05-03-youtube-extractor-design]] (base extractor spec). Implementation plan tracked in [[2026-05-24-whisper-transcript-fallback]] (written next).

**Date:** 2026-05-24
**Status:** Approved
**Project:** youtube-extractor

## 1. Purpose

Videos without official/available YouTube captions currently fail the pipeline at the transcript stage with `NoTranscriptError` → job `failed (stage=transcript, NO_TRANSCRIPT)`. This blocks any captionless video from being distilled.

Add a fallback: when official captions are missing, download the audio and transcribe it locally with Whisper, then feed that transcript into the existing distill → render → catalog stages unchanged. The `Transcript` model already anticipates this with `source: Literal["official", "whisper"]`.

## 2. Scope

**In scope**
- New module `youtube_extractor/pipeline/whisper_fallback.py` exposing `whisper_transcript(video_id: str) -> Transcript`.
- Audio-only download via yt-dlp (reuses the existing `yt_dlp_cookies_browser` setting), to a temp file, always cleaned up.
- Local transcription via `mlx-whisper` (Apple Silicon GPU) using `large-v3-turbo`.
- Lazy model load on first use; release after each transcription (≈0 idle RAM). A module-level lock serializes whisper so at most one transcription runs at a time.
- Orchestrator integration: wrap the existing official-transcript call so `NoTranscriptError` triggers the whisper fallback when enabled.
- Config: `whisper_enabled` (default `True`), `whisper_model` (default `mlx-community/whisper-large-v3-turbo`).
- `mlx-whisper` added as an optional dependency extra (`.[whisper]`); guarded import so the base package still installs and runs (official-only) on non-Apple hosts.
- Unit tests with mocked yt-dlp + mocked mlx (no real model load, no network).

**Out of scope**
- faster-whisper / CPU runtime / any second runtime or runtime-selection logic (single Mac, single GPU runtime). Revisit only if the extractor ever runs off Apple Silicon.
- A hosted/API Whisper option.
- Speaker diarization, word-level timestamps, translation.
- Re-running already-failed `NO_TRANSCRIPT` jobs automatically (user re-submits as normal).
- Mission Control UI changes (none needed; the job just succeeds where it used to fail).

## 3. Data flow

Only the transcript stage of `pipeline/orchestrator.py` changes. Current:

```
transcript = await asyncio.to_thread(fetch_transcript, video_id)
```

New:

```
try:
    transcript = await asyncio.to_thread(fetch_transcript, video_id)   # official, unchanged, still first
except NoTranscriptError:
    if not settings.whisper_enabled:
        raise
    try:
        transcript = await asyncio.to_thread(whisper_transcript, video_id)  # fallback
    except WhisperError as e:
        raise NoTranscriptError(f"no official transcript; whisper fallback failed: {e}") from e
```

Re-raising `WhisperError` as `NoTranscriptError` means the existing `stage=transcript` job handling applies with **no change to `api/jobs.py`** — the orchestrator is the single integration point.

`whisper_transcript(video_id)` (synchronous, run via `to_thread` to keep the event loop free — consistent with the existing pipeline offloading):

1. Download audio-only with yt-dlp to a temp file (e.g. `m4a`/`webm`/`bestaudio`), applying `cookiesfrombrowser` from settings.
2. Acquire the module lock.
3. Lazy-load the mlx-whisper model if not already loaded for this call; transcribe the audio.
4. Build `Transcript(source="whisper", segments=[...], full_text=..., language=<whisper-detected language>)`.
5. Release the model reference; release the lock.
6. `finally`: delete the temp audio file (and any yt-dlp leftovers).

Everything downstream (`distill` → `render_pdfs`/`render_markdown` → catalog) is untouched; it receives a `Transcript` whose `source` is `"whisper"`.

## 4. Components

### 4.1 `pipeline/whisper_fallback.py`
Single responsibility: produce a `Transcript` from a video's audio. Internal helpers:
- `_download_audio(video_id, dest_dir) -> Path` — yt-dlp audio-only, cookie-aware.
- `_transcribe(audio_path) -> tuple[list[TranscriptSegment], str, str]` — mlx-whisper call; returns segments, full_text, detected language.
- `whisper_transcript(video_id) -> Transcript` — orchestrates download → transcribe → cleanup.

Errors raised as `WhisperError` (new) for download/transcription failures. Empty transcription text is treated as a failure.

Model lifecycle: a module-level `threading.Lock` (`_whisper_lock`) guards load+inference so only one transcription runs at a time (bounds GPU/RAM under `max_concurrent_jobs=2`). Loaded per-use and dropped after, so idle RAM ≈ 0. (A keep-warm idle-unload timer is a possible future optimization, explicitly deferred.)

Guarded import: `import mlx_whisper` wrapped so an ImportError (non-Apple host or extra not installed) is detected; `whisper_transcript` then raises `WhisperError("mlx-whisper not available")`, and `whisper_enabled` can be treated as effectively off.

### 4.2 `pipeline/orchestrator.py`
~4-line change wrapping the official-transcript call with the fallback (see §3). Imports `whisper_transcript` and `NoTranscriptError`.

### 4.3 `config.py`
Add:
- `whisper_enabled: bool = True`
- `whisper_model: str = "mlx-community/whisper-large-v3-turbo"`

(`.env` gets matching commented entries; defaults are sane so no env change is required.)

## 5. Error handling

- Audio download failure, whisper inference failure, or empty output → `whisper_fallback` raises `WhisperError`; the orchestrator converts it to `NoTranscriptError` (see §3), so the job fails at the existing `stage=transcript` mapping (`NO_TRANSCRIPT`, retryable per current behavior). No `api/jobs.py` change.
- Temp audio always removed in a `finally`, even on failure (honors the repo's clean-up discipline).
- `mlx-whisper` not installed / non-Apple host → fallback unavailable; official-only behavior unchanged; job fails with a clear `NO_TRANSCRIPT`/whisper-unavailable message rather than crashing.

## 6. Testing

All tests offline and deterministic — never load a real model or hit the network.

- Orchestrator: mock `fetch_transcript` to raise `NoTranscriptError`, mock `whisper_transcript` to return a `Transcript(source="whisper", ...)`; assert the pipeline proceeds and the distillation runs on the whisper transcript.
- Orchestrator: `whisper_enabled=False` → `NoTranscriptError` propagates (job fails, no whisper call).
- `whisper_fallback`: mock `_download_audio` (return a fake path) and the mlx transcribe call (return canned segments); assert `whisper_transcript` returns `source="whisper"`, correct `full_text`, and that the temp file cleanup is invoked even when transcription raises.
- Guarded import: simulate `mlx_whisper` import failure → `WhisperError`.

## 7. Dependencies

- Add `mlx-whisper` as an optional extra in `pyproject.toml`: `[project.optional-dependencies] whisper = ["mlx-whisper>=0.4"]`. Install on the Mac with `pip install -e '.[whisper]'`.
- `ffmpeg` — already installed (used by yt-dlp / whisper for audio decoding).
- No change to the base dependency list, so the package still installs on any platform (official-only).

## 8. Success criteria

- A captionless video (e.g. one that previously failed `NO_TRANSCRIPT`) submitted via the API runs end-to-end: audio downloaded, transcribed locally on the M2 GPU, distilled via Kimi, `.md` + 2 PDFs produced, catalog row written with the transcript sourced from whisper.
- Idle RAM attributable to whisper is ~0 between jobs (model released after use).
- Videos with official captions are unaffected (official path still taken first).
- Full test suite green; ruff clean.
