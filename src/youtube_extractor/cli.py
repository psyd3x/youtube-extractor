from __future__ import annotations

import asyncio

import click

from youtube_extractor.config import settings
from youtube_extractor.pipeline.orchestrator import run_pipeline


@click.group()
def cli() -> None:
    """YouTube Extractor — turn a video link into Markdown + 2 PDFs."""


@cli.command("extract")
@click.argument("url")
def extract(url: str) -> None:
    """Run the full pipeline for one URL and print where the outputs landed."""
    result = asyncio.run(
        run_pipeline(
            url=url,
            vault_dir=settings.obsidian_vault_path,
            output_dir=settings.output_dir,
        )
    )
    click.echo(f"slug: {result.slug}")
    click.echo(f"md:   {result.md_path}")
    click.echo(f"full: {result.pdf_full_path}")
    click.echo(f"lazy: {result.pdf_lazy_path}")


@cli.command("serve")
@click.option("--host", default=None, help="Override HOST env (e.g. 127.0.0.1)")
@click.option("--port", default=None, type=int, help="Override PORT env (default 18765)")
def serve(host: str | None, port: int | None) -> None:
    """Run the FastAPI service on 127.0.0.1:18765 by default."""
    if host:
        settings.host = host
    if port:
        settings.port = port
    from youtube_extractor.main import serve as _serve
    _serve()


if __name__ == "__main__":
    cli()
