import types

import pytest

from youtube_extractor.pipeline import whisper_fallback as wf


def test_whisper_error_is_exception():
    assert issubclass(wf.WhisperError, Exception)


def test_whisper_transcript_raises_when_unavailable(monkeypatch):
    monkeypatch.setattr(wf, "_MLX_AVAILABLE", False)
    with pytest.raises(wf.WhisperError):
        wf.whisper_transcript("abc123")


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
    assert released["n"] == 1


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
    assert released["n"] == 1
