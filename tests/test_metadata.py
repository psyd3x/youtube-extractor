from unittest.mock import MagicMock, patch

import pytest

from youtube_extractor.pipeline.metadata import MetadataError, fetch_metadata

SAMPLE = {
    "id": "dQw4w9WgXcQ",
    "title": "Rick Astley - Never Gonna Give You Up",
    "uploader": "Rick Astley",
    "duration": 213,
    "upload_date": "20091025",
    "thumbnail": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
    "description": "Music video.",
}


def test_fetch_metadata_happy():
    fake = MagicMock()
    fake.__enter__.return_value.extract_info.return_value = SAMPLE
    fake.__exit__.return_value = False
    with patch("youtube_extractor.pipeline.metadata.yt_dlp.YoutubeDL", return_value=fake):
        m = fetch_metadata("dQw4w9WgXcQ")
    assert m.title.startswith("Rick Astley")
    assert m.duration_s == 213
    assert m.published == "2009-10-25"


def test_fetch_metadata_failure():
    import yt_dlp
    fake = MagicMock()
    fake.__enter__.return_value.extract_info.side_effect = yt_dlp.utils.DownloadError("private video")
    fake.__exit__.return_value = False
    with (
        patch("youtube_extractor.pipeline.metadata.yt_dlp.YoutubeDL", return_value=fake),
        pytest.raises(MetadataError),
    ):
        fetch_metadata("dQw4w9WgXcQ")
