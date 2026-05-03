from unittest.mock import patch

import pytest

from youtube_extractor.pipeline.transcript import NoTranscriptError, fetch_transcript

SAMPLE_FETCH = [
    {"text": "Never gonna give you up", "start": 0.0, "duration": 2.5},
    {"text": "Never gonna let you down", "start": 2.5, "duration": 2.5},
]


def test_fetch_transcript_happy():
    with patch(
        "youtube_extractor.pipeline.transcript.YouTubeTranscriptApi.get_transcript",
        return_value=SAMPLE_FETCH,
    ):
        t = fetch_transcript("dQw4w9WgXcQ")
    assert len(t.segments) == 2
    assert t.segments[0].text == "Never gonna give you up"
    assert "let you down" in t.full_text
    assert t.source == "official"


def test_fetch_transcript_unavailable():
    from youtube_transcript_api._errors import TranscriptsDisabled

    with (
        patch(
            "youtube_extractor.pipeline.transcript.YouTubeTranscriptApi.get_transcript",
            side_effect=TranscriptsDisabled("dQw4w9WgXcQ"),
        ),
        pytest.raises(NoTranscriptError),
    ):
        fetch_transcript("dQw4w9WgXcQ")
