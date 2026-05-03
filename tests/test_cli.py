from unittest.mock import AsyncMock, patch

from click.testing import CliRunner

from youtube_extractor.cli import cli
from youtube_extractor.pipeline.orchestrator import PipelineResult


def test_cli_extract(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "out"))
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path / "vault"))
    fake = AsyncMock(return_value=PipelineResult(
        slug="s",
        md_path=tmp_path / "s.md",
        pdf_full_path=tmp_path / "s-full.pdf",
        pdf_lazy_path=tmp_path / "s-lazy.pdf",
    ))
    with patch("youtube_extractor.cli.run_pipeline", new=fake):
        runner = CliRunner()
        result = runner.invoke(cli, ["extract", "https://youtu.be/dQw4w9WgXcQ"])
    assert result.exit_code == 0, result.output
    assert "slug: s" in result.output
    assert "md:" in result.output
    assert "full:" in result.output
    assert "lazy:" in result.output


def test_cli_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "extract" in result.output.lower()
    assert "serve" in result.output.lower()


def test_cli_serve_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["serve", "--help"])
    assert result.exit_code == 0
    out = result.output.lower()
    assert "host" in out
    assert "port" in out


def test_cli_extract_invalid_url():
    """Invalid URL should exit non-zero and not crash."""
    runner = CliRunner()
    result = runner.invoke(cli, ["extract", "not a url"])
    # Click + InvalidYouTubeUrl bubbling up: exit code != 0
    assert result.exit_code != 0
