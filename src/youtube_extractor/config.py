from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    llm_base_url: str = "http://localhost:8642"
    llm_api_key: str | None = None
    llm_model: str | None = None

    obsidian_vault_path: Path = Path("~/.claude/obsidian-mind/youtube")
    output_dir: Path = Path("./output")

    host: str = "127.0.0.1"
    port: int = 18765
    log_level: str = "INFO"

    max_concurrent_jobs: int = 2
    llm_timeout_s: int = 300
    transcript_retries: int = 3

    # Browser to pull cookies from for yt-dlp (avoids bot detection).
    # Supported: chrome, safari, firefox, brave, edge. Set to empty string to disable.
    yt_dlp_cookies_browser: str = "chrome"
    # Netscape cookies.txt; when set and present it wins over yt_dlp_cookies_browser.
    # Each yt-dlp call gets a private temp copy (yt-dlp rewrites its cookiefile on close).
    yt_dlp_cookies_file: str = ""

    # Whisper fallback (Apple Silicon / mlx). Used only when a video has no
    # official captions. Model loaded on demand and released after each use.
    whisper_enabled: bool = True
    whisper_model: str = "mlx-community/whisper-large-v3-turbo"
    # Remote whisper (OpenAI-compatible /v1/audio/transcriptions, e.g. the Mac's mlx-whisper
    # service). Empty = transcribe in-process with mlx-whisper (default, Apple Silicon).
    whisper_api_url: str = ""
    whisper_api_key: str | None = None
    whisper_api_timeout_s: int = 1800

    @field_validator("obsidian_vault_path", "output_dir", mode="after")
    @classmethod
    def _expand(cls, v: Path) -> Path:
        return v.expanduser().resolve()


settings = Settings()
