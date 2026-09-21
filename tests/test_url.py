import pytest

from youtube_extractor.pipeline.url import InvalidYouTubeUrl, extract_video_id

VALID_CASES = [
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://youtube.com/watch?v=dQw4w9WgXcQ&t=42s", "dQw4w9WgXcQ"),
    ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://youtu.be/dQw4w9WgXcQ?si=abc", "dQw4w9WgXcQ"),
    ("https://www.youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    # /live/ is what the share button gives you for a livestream or premiere,
    # and every one of them was rejected before this (live failure 2026-09-21).
    ("https://www.youtube.com/live/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://www.youtube.com/live/dQw4w9WgXcQ?si=abc", "dQw4w9WgXcQ"),
    ("https://m.youtube.com/live/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://www.youtube.com/v/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://m.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("dQw4w9WgXcQ", "dQw4w9WgXcQ"),
]

INVALID_CASES = [
    "https://example.com/watch?v=dQw4w9WgXcQ",
    "https://www.youtube.com/",
    "not a url",
    "",
    # A prefix path still has to carry a real id — the shape check is what
    # stops "/live/" widening into "accept anything after a slash".
    "https://www.youtube.com/live/",
    "https://www.youtube.com/live/tooshort",
]


@pytest.mark.parametrize("url,expected", VALID_CASES)
def test_extract_valid(url, expected):
    assert extract_video_id(url) == expected


@pytest.mark.parametrize("url", INVALID_CASES)
def test_extract_invalid(url):
    with pytest.raises(InvalidYouTubeUrl):
        extract_video_id(url)
