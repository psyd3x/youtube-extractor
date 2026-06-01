from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from youtube_extractor.models import Distillation, InstructionsAndData, Metadata

_TEMPLATES_DIR = Path(__file__).parent.parent.parent.parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(disabled_extensions=("md",), default=False),
    keep_trailing_newline=True,
)


def render_markdown(
    *,
    meta: Metadata,
    distill: Distillation,
    slug: str,
    vault_dir: Path,
    pdf_full_path: str,
    pdf_lazy_path: str,
    extracted_date: str,
    instructions: InstructionsAndData | None = None,
    pdf_instructions_path: str | None = None,
) -> Path:
    """Render the Obsidian-flavoured markdown file and write it into vault_dir."""
    vault_dir.mkdir(parents=True, exist_ok=True)
    template = _env.get_template("obsidian.md.jinja")
    content = template.render(
        meta=meta,
        distill=distill,
        pdf_full_path=pdf_full_path,
        pdf_lazy_path=pdf_lazy_path,
        extracted_date=extracted_date,
        instructions=instructions,
        pdf_instructions_path=pdf_instructions_path,
    )
    out = vault_dir / f"{slug}.md"
    out.write_text(content, encoding="utf-8")
    return out
