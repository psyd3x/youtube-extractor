import pytest

from youtube_extractor.pipeline.url import InvalidYouTubeUrl, extract_video_id

VALID_CASES = [
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://youtube.com/watch?v=dQw4w9WgXcQ&t=42s", "dQw4w9WgXcQ"),
    ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://youtu.be/dQw4w9WgXcQ?si=abc", "dQw4w9WgXcQ"),
    ("https://www.youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://m.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("dQw4w9WgXcQ", "dQw4w9WgXcQ"),
]

INVALID_CASES = [
    "https://example.com/watch?v=dQw4w9WgXcQ",
    "https://www.youtube.com/",
    "not a url",
    "",
]


@pytest.mark.parametrize("url,expected", VALID_CASES)
def test_extract_valid(url, expected):
    assert extract_video_id(url) == expected


@pytest.mark.parametrize("url", INVALID_CASES)
def test_extract_invalid(url):
    with pytest.raises(InvalidYouTubeUrl):
        extract_video_id(url)
