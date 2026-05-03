import re
from urllib.parse import parse_qs, urlparse


class InvalidYouTubeUrl(ValueError):
    pass


_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_YT_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}


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
    elif parsed.path.startswith("/embed/") or parsed.path.startswith("/shorts/"):
        candidate = parsed.path.split("/", 2)[2].split("/", 1)[0]
    else:
        raise InvalidYouTubeUrl(f"unrecognised youtube path: {parsed.path!r}")

    if not _ID_RE.match(candidate):
        raise InvalidYouTubeUrl(f"video id failed shape check: {candidate!r}")
    return candidate
