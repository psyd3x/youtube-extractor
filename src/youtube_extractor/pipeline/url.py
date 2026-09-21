import re
from urllib.parse import parse_qs, urlparse


class InvalidYouTubeUrl(ValueError):
    pass


_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_YT_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}

# Paths shaped "/<prefix>/<video id>". "/live/" is what YouTube serves for a
# livestream or premiere, and is the canonical link you get from the share
# button while a stream is on — it was missing here, so every stream URL was
# rejected outright ("unrecognised youtube path", live failure 2026-09-21).
# "/v/" is the legacy embed path and fails identically; same one-line branch.
_ID_PATH_PREFIXES = ("/embed/", "/shorts/", "/live/", "/v/")


def extract_video_id(url: str) -> str:
    if not url or not isinstance(url, str):
        raise InvalidYouTubeUrl("empty or non-string url")

    raw = url.strip()
    if _ID_RE.match(raw):
        return raw

    try:
        parsed = urlparse(raw)
    except Exception as e:
        raise InvalidYouTubeUrl(f"unparseable url: {e}") from e

    host = parsed.hostname or ""
    if host not in _YT_HOSTS:
        raise InvalidYouTubeUrl(f"not a youtube host: {host!r}")

    if host == "youtu.be":
        candidate = parsed.path.lstrip("/").split("/", 1)[0]
    elif parsed.path == "/watch":
        candidate = (parse_qs(parsed.query).get("v") or [""])[0]
    elif parsed.path.startswith(_ID_PATH_PREFIXES):
        candidate = parsed.path.split("/", 2)[2].split("/", 1)[0]
    else:
        raise InvalidYouTubeUrl(f"unrecognised youtube path: {parsed.path!r}")

    if not _ID_RE.match(candidate):
        raise InvalidYouTubeUrl(f"video id failed shape check: {candidate!r}")
    return candidate
