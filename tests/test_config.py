from youtube_extractor.config import Settings


def test_settings_loads_defaults(monkeypatch):
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("OUTPUT_DIR", raising=False)
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
    # _env_file=None isolates from the deployment .env (gitignored) so this asserts
    # the shipped code defaults, not whatever endpoint the local box is pointed at.
    s = Settings(_env_file=None)
    assert s.llm_base_url == "http://localhost:8642"
    assert s.host == "127.0.0.1"
    assert s.port == 18765
    assert s.max_concurrent_jobs == 2


def test_settings_env_override(monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://x:1/v1")
    monkeypatch.setenv("PORT", "9999")
    s = Settings()
    assert s.llm_base_url == "http://x:1/v1"
    assert s.port == 9999


def test_paths_expanded(monkeypatch, tmp_path):
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "out"))
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path / "vault"))
    s = Settings()
    assert s.output_dir.is_absolute()
    assert s.obsidian_vault_path.is_absolute()
