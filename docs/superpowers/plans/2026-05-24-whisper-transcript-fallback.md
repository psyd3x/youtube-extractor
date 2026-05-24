# Whisper Transcript Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a YouTube video has no official captions, transcribe its audio locally with mlx-whisper so the pipeline still produces the `.md` + PDFs.

**Architecture:** A new `whisper_fallback` module downloads audio (yt-dlp, cookie-aware), transcribes it with mlx-whisper (`large-v3-turbo`, M2 GPU), and returns a `Transcript(source="whisper")`. The orchestrator calls it only when the official-caption path raises `NoTranscriptError`. The model is loaded on demand and released after each use (reset `ModelHolder` + `gc.collect()` + `mx.clear_cache()`), with a module lock serializing transcriptions. The orchestrator is the single integration point; no API/UI changes.

**Tech Stack:** Python 3.11, FastAPI, yt-dlp, mlx-whisper (Apple Silicon, optional extra), pytest + respx, ruff.

> **Env note (RTK):** this machine's shell wraps `pytest`/`ruff` and may print a misleading "No tests collected" summary. If output looks summarized, re-run via `rtk proxy python -m pytest ...` / `rtk proxy ruff ...` for real output.

Spec: [[2026-05-24-whisper-transcript-fallback-design]]

---

## File Structure

- Create: `src/youtube_extractor/pipeline/whisper_fallback.py` — audio download + mlx transcription + model lifecycle. Exposes `whisper_transcript(video_id) -> Transcript` and `WhisperError`.
- Modify: `src/youtube_extractor/config.py` — add `whisper_enabled`, `whisper_model`.
- Modify: `src/youtube_extractor/pipeline/orchestrator.py` — wrap the official-transcript call with the fallback.
- Modify: `pyproject.toml` — add `whisper` optional-dependency extra.
- Modify: `.env.example` — document the two new settings.
- Create: `tests/test_whisper_fallback.py` — unit tests (mocked yt-dlp + mlx).
- Modify: `tests/test_orchestrator.py` — fallback wiring tests.
- Modify: `tests/test_config.py` — assert new defaults.

---

### Task 1: Config — whisper settings

**Files:**
- Modify: `src/youtube_extractor/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_config.py`:

```python
def test_settings_whisper_defaults():
    s = Settings(_env_file=None)
    assert s.whisper_enabled is True
    assert s.whisper_model == "mlx-community/whisper-large-v3-turbo"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py -k whisper -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'whisper_enabled'`

- [ ] **Step 3: Add the fields**

In `src/youtube_extractor/config.py`, after the `yt_dlp_cookies_browser` field:

```python
    # Whisper fallback (Apple Silicon / mlx). Used only when a video has no
    # official captions. Model loaded on demand and released after each use.
    whisper_enabled: bool = True
    whisper_model: str = "mlx-community/whisper-large-v3-turbo"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_config.py -k whisper -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/youtube_extractor/config.py tests/test_config.py
git commit -m "feat(config): add whisper_enabled + whisper_model settings"
```

---

### Task 2: whisper_fallback module skeleton (WhisperError + guarded import)

**Files:**
- Create: `src/youtube_extractor/pipeline/whisper_fallback.py`
- Test: `tests/test_whisper_fallback.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_whisper_fallback.py`:

```python
import pytest

from youtube_extractor.pipeline import whisper_fallback as wf


def test_whisper_error_is_exception():
    assert issubclass(wf.WhisperError, Exception)


def test_whisper_transcript_raises_when_unavailable(monkeypatch):
    monkeypatch.setattr(wf, "_MLX_AVAILABLE", False)
    with pytest.raises(wf.WhisperError):
        wf.whisper_transcript("abc123")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_whisper_fallback.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'youtube_extractor.pipeline.whisper_fallback'`

- [ ] **Step 3: Create the module skeleton**

Create `src/youtube_extractor/pipeline/whisper_fallback.py`:

```python
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


def whisper_transcript(video_id: str) -> Transcript:
    if not _MLX_AVAILABLE:
        raise WhisperError(
            "mlx-whisper not available (install the '.[whisper]' extra on Apple Silicon)"
        )
    raise WhisperError("not implemented")  # filled in Task 5
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_whisper_fallback.py -v`
Expected: PASS (both tests)

- [ ] **Step 5: Commit**

```bash
git add src/youtube_extractor/pipeline/whisper_fallback.py tests/test_whisper_fallback.py
git commit -m "feat(whisper): module skeleton with guarded mlx import + WhisperError"
```

---

### Task 3: `_download_audio` — yt-dlp audio-only, cookie-aware

**Files:**
- Modify: `src/youtube_extractor/pipeline/whisper_fallback.py`
- Test: `tests/test_whisper_fallback.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_whisper_fallback.py`:

```python
def test_download_audio_builds_opts_and_returns_path(monkeypatch, tmp_path):
    captured = {}

    class FakeYDL:
        def __init__(self, opts):
            captured["opts"] = opts
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def extract_info(self, url, download):
            captured["url"] = url
            captured["download"] = download
            return {"id": "vid123", "ext": "m4a"}
        def prepare_filename(self, info):
            return str(tmp_path / f"{info['id']}.{info['ext']}")

    monkeypatch.setattr(wf.yt_dlp, "YoutubeDL", FakeYDL)
    monkeypatch.setattr(wf.settings, "yt_dlp_cookies_browser", "chrome")

    out = wf._download_audio("vid123", tmp_path)

    assert out == tmp_path / "vid123.m4a"
    assert captured["opts"]["format"] == "bestaudio/best"
    assert captured["opts"]["cookiesfrombrowser"] == ("chrome",)
    assert captured["download"] is True
    assert "vid123" in captured["url"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_whisper_fallback.py -k download_audio -v`
Expected: FAIL — `AttributeError: module ... has no attribute '_download_audio'`

- [ ] **Step 3: Implement `_download_audio`**

In `whisper_fallback.py`, add above `whisper_transcript`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_whisper_fallback.py -k download_audio -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/youtube_extractor/pipeline/whisper_fallback.py tests/test_whisper_fallback.py
git commit -m "feat(whisper): cookie-aware audio-only download via yt-dlp"
```

---

### Task 4: `_transcribe` + `_release_model`

**Files:**
- Modify: `src/youtube_extractor/pipeline/whisper_fallback.py`
- Test: `tests/test_whisper_fallback.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_whisper_fallback.py`:

```python
import types


def test_transcribe_maps_result(monkeypatch, tmp_path):
    fake = types.SimpleNamespace(
        transcribe=lambda audio, path_or_hf_repo: {
            "text": "  hello world  ",
            "segments": [{"start": 0.0, "end": 1.5, "text": "hello world"}],
            "language": "en",
        }
    )
    monkeypatch.setattr(wf, "mlx_whisper", fake)

    segments, full_text, language = wf._transcribe(tmp_path / "a.m4a")

    assert full_text == "hello world"
    assert language == "en"
    assert len(segments) == 1
    assert segments[0].start == 0.0
    assert segments[0].dur == 1.5
    assert segments[0].text == "hello world"


def test_transcribe_empty_raises(monkeypatch, tmp_path):
    fake = types.SimpleNamespace(
        transcribe=lambda audio, path_or_hf_repo: {"text": "   ", "segments": [], "language": "en"}
    )
    monkeypatch.setattr(wf, "mlx_whisper", fake)
    with pytest.raises(wf.WhisperError):
        wf._transcribe(tmp_path / "a.m4a")


def test_release_model_resets_holder(monkeypatch):
    class FakeHolder:
        model = "loaded"
        model_path = "repo"
    fake_mx = types.SimpleNamespace(clear_cache=lambda: None)
    monkeypatch.setattr(wf, "ModelHolder", FakeHolder)
    monkeypatch.setattr(wf, "mx", fake_mx)

    wf._release_model()

    assert FakeHolder.model is None
    assert FakeHolder.model_path is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_whisper_fallback.py -k "transcribe or release" -v`
Expected: FAIL — `AttributeError: ... '_transcribe'`

- [ ] **Step 3: Implement `_transcribe` and `_release_model`**

In `whisper_fallback.py`, add above `whisper_transcript`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_whisper_fallback.py -k "transcribe or release" -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/youtube_extractor/pipeline/whisper_fallback.py tests/test_whisper_fallback.py
git commit -m "feat(whisper): transcribe mapping + model release helper"
```

---

### Task 5: `whisper_transcript` orchestration (download → transcribe → cleanup → release)

**Files:**
- Modify: `src/youtube_extractor/pipeline/whisper_fallback.py`
- Test: `tests/test_whisper_fallback.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_whisper_fallback.py`:

```python
def test_whisper_transcript_happy(monkeypatch, tmp_path):
    monkeypatch.setattr(wf, "_MLX_AVAILABLE", True)
    monkeypatch.setattr(wf, "_download_audio", lambda vid, d: tmp_path / "a.m4a")
    monkeypatch.setattr(
        wf, "_transcribe",
        lambda p: ([wf.TranscriptSegment(start=0.0, dur=1.0, text="hi")], "hi there", "en"),
    )
    released = {"n": 0}
    monkeypatch.setattr(wf, "_release_model", lambda: released.__setitem__("n", released["n"] + 1))

    t = wf.whisper_transcript("vid123")

    assert t.source == "whisper"
    assert t.full_text == "hi there"
    assert t.language == "en"
    assert released["n"] == 1  # released even on the happy path


def test_whisper_transcript_releases_on_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(wf, "_MLX_AVAILABLE", True)
    monkeypatch.setattr(wf, "_download_audio", lambda vid, d: tmp_path / "a.m4a")
    def boom(p):
        raise wf.WhisperError("inference failed")
    monkeypatch.setattr(wf, "_transcribe", boom)
    released = {"n": 0}
    monkeypatch.setattr(wf, "_release_model", lambda: released.__setitem__("n", released["n"] + 1))

    with pytest.raises(wf.WhisperError):
        wf.whisper_transcript("vid123")
    assert released["n"] == 1  # finally-block release ran
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_whisper_fallback.py -k whisper_transcript -v`
Expected: FAIL — current `whisper_transcript` raises `WhisperError("not implemented")`

- [ ] **Step 3: Implement `whisper_transcript`**

In `whisper_fallback.py`, replace the placeholder body of `whisper_transcript`:

```python
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

    with _whisper_lock:
        with tempfile.TemporaryDirectory(prefix="yte-whisper-") as td:
            audio_path = _download_audio(video_id, Path(td))
            try:
                segments, full_text, language = _transcribe(audio_path)
            finally:
                _release_model()

    return Transcript(
        segments=segments, full_text=full_text, language=language, source="whisper"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_whisper_fallback.py -v`
Expected: PASS (all tests in file)

- [ ] **Step 5: Commit**

```bash
git add src/youtube_extractor/pipeline/whisper_fallback.py tests/test_whisper_fallback.py
git commit -m "feat(whisper): whisper_transcript with temp cleanup + guaranteed release"
```

---

### Task 6: Orchestrator integration (fallback on NoTranscriptError)

**Files:**
- Modify: `src/youtube_extractor/pipeline/orchestrator.py`
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_orchestrator.py` (helpers `_meta`, `_di`, `VIDEO_ID` already exist in this file):

```python
from youtube_extractor.models import Transcript, TranscriptSegment
from youtube_extractor.pipeline.transcript import NoTranscriptError
from youtube_extractor.pipeline.whisper_fallback import WhisperError


def _whisper_tx():
    return Transcript(
        segments=[TranscriptSegment(start=0, dur=1, text="spoken")],
        full_text="spoken words", language="en", source="whisper",
    )


async def test_pipeline_uses_whisper_when_no_official_transcript(tmp_path, monkeypatch):
    monkeypatch.setattr("youtube_extractor.pipeline.orchestrator.settings.whisper_enabled", True)
    with patch("youtube_extractor.pipeline.orchestrator.fetch_metadata", return_value=_meta()), \
         patch("youtube_extractor.pipeline.orchestrator.fetch_transcript",
               side_effect=NoTranscriptError("none")), \
         patch("youtube_extractor.pipeline.orchestrator.whisper_transcript",
               return_value=_whisper_tx()), \
         patch("youtube_extractor.pipeline.orchestrator.distill", new=AsyncMock(return_value=_di())):
        result = await run_pipeline(
            url=f"https://youtu.be/{VIDEO_ID}", vault_dir=tmp_path / "v", output_dir=tmp_path / "o"
        )
    assert result.md_path.exists()


async def test_pipeline_no_whisper_when_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr("youtube_extractor.pipeline.orchestrator.settings.whisper_enabled", False)
    with patch("youtube_extractor.pipeline.orchestrator.fetch_metadata", return_value=_meta()), \
         patch("youtube_extractor.pipeline.orchestrator.fetch_transcript",
               side_effect=NoTranscriptError("none")), \
         patch("youtube_extractor.pipeline.orchestrator.whisper_transcript") as wt:
        with pytest.raises(NoTranscriptError):
            await run_pipeline(
                url=f"https://youtu.be/{VIDEO_ID}", vault_dir=tmp_path / "v", output_dir=tmp_path / "o"
            )
        wt.assert_not_called()


async def test_pipeline_whisper_failure_becomes_no_transcript(tmp_path, monkeypatch):
    monkeypatch.setattr("youtube_extractor.pipeline.orchestrator.settings.whisper_enabled", True)
    with patch("youtube_extractor.pipeline.orchestrator.fetch_metadata", return_value=_meta()), \
         patch("youtube_extractor.pipeline.orchestrator.fetch_transcript",
               side_effect=NoTranscriptError("none")), \
         patch("youtube_extractor.pipeline.orchestrator.whisper_transcript",
               side_effect=WhisperError("download failed")):
        with pytest.raises(NoTranscriptError):
            await run_pipeline(
                url=f"https://youtu.be/{VIDEO_ID}", vault_dir=tmp_path / "v", output_dir=tmp_path / "o"
            )
```

Add `import pytest` at the top of `tests/test_orchestrator.py` if not already present.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_orchestrator.py -k "whisper or no_official" -v`
Expected: FAIL — `ImportError: cannot import name 'whisper_transcript'` in orchestrator, or `AttributeError` on `settings`.

- [ ] **Step 3: Implement the orchestrator change**

In `src/youtube_extractor/pipeline/orchestrator.py`:

Add imports near the other pipeline imports:

```python
from youtube_extractor.config import settings
from youtube_extractor.pipeline.transcript import NoTranscriptError, fetch_transcript
from youtube_extractor.pipeline.whisper_fallback import WhisperError, whisper_transcript
```

(Replace the existing `from youtube_extractor.pipeline.transcript import fetch_transcript` line with the combined import above.)

Replace the transcript line:

```python
    transcript = await asyncio.to_thread(fetch_transcript, video_id)
```

with:

```python
    try:
        transcript = await asyncio.to_thread(fetch_transcript, video_id)
    except NoTranscriptError:
        if not settings.whisper_enabled:
            raise
        try:
            transcript = await asyncio.to_thread(whisper_transcript, video_id)
        except WhisperError as e:
            raise NoTranscriptError(
                f"no official transcript; whisper fallback failed: {e}"
            ) from e
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_orchestrator.py -v`
Expected: PASS (existing tests + 3 new). The existing `test_run_pipeline_happy` still passes because `fetch_transcript` returns normally (no fallback).

- [ ] **Step 5: Commit**

```bash
git add src/youtube_extractor/pipeline/orchestrator.py tests/test_orchestrator.py
git commit -m "feat(pipeline): fall back to whisper when no official transcript"
```

---

### Task 7: Packaging — optional extra + .env.example

**Files:**
- Modify: `pyproject.toml`
- Modify: `.env.example`

- [ ] **Step 1: Add the optional extra**

In `pyproject.toml`, under the existing `[project.optional-dependencies]` table (the one that already holds `dev = [...]`), add:

```toml
whisper = ["mlx-whisper>=0.4"]
```

- [ ] **Step 2: Document the settings**

Append to `.env.example`:

```
# Whisper fallback for captionless videos (Apple Silicon).
# Install the extra:  pip install -e '.[whisper]'
WHISPER_ENABLED=true
WHISPER_MODEL=mlx-community/whisper-large-v3-turbo
```

- [ ] **Step 3: Verify the project still resolves**

Run: `python -m pytest -q`
Expected: full suite PASS (no new tests here; this confirms nothing broke).

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml .env.example
git commit -m "build(whisper): add optional mlx-whisper extra + document env vars"
```

---

### Task 8: Manual integration verification (not automated)

**Files:** none (runtime check on the Mac).

- [ ] **Step 1: Install the extra**

```bash
cd ~/Youtube-extractor && source .venv/bin/activate && pip install -e '.[whisper]'
```

- [ ] **Step 2: Restart the service**

```bash
launchctl stop com.deedee.youtube-extractor && sleep 2 && launchctl start com.deedee.youtube-extractor && sleep 3 && curl -s http://127.0.0.1:18765/health
```

- [ ] **Step 3: Submit a known captionless video and poll to done**

Use one of the videos that previously failed `NO_TRANSCRIPT` (e.g. `V0-yBVdbi6w`). First whisper run downloads the model (~1–2 GB) — expect a longer first run.

```bash
JOB=$(curl -s -X POST -H "Content-Type: application/json" -d '{"url":"https://www.youtube.com/watch?v=V0-yBVdbi6w"}' http://127.0.0.1:18765/jobs | python3 -c "import sys,json;print(json.load(sys.stdin)['job_id'])")
echo "$JOB"; for i in $(seq 1 40); do sleep 6; rtk proxy curl -s http://127.0.0.1:18765/jobs/$JOB | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['status'],d.get('error_code') or '')"; done
```

Expected: reaches `done`; catalog entry exists with the transcript sourced from whisper; idle RAM returns to baseline after completion.

- [ ] **Step 4: Append a manual smoke note**

Append the result (video id, duration, time taken, done/failed) to `docs/manual-test-log.md`, then commit that file.

---

## Notes for the implementer

- mlx-whisper is **not** installed in the venv during unit tests; that's why every test patches module globals (`wf.mlx_whisper`, `wf.ModelHolder`, `wf._MLX_AVAILABLE`) rather than relying on a real import. Never load a real model in tests.
- `large-v3-turbo` is the default for speed/quality balance. To get max accuracy (closest to a hosted engine), set `WHISPER_MODEL=mlx-community/whisper-large-v3-mlx`. No code change — it's just the config value.
- Keep blocking work off the event loop: the orchestrator already calls `whisper_transcript` via `asyncio.to_thread`.
