from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import CSS, HTML

from youtube_extractor.models import Distillation, InstructionsAndData, Metadata

_TEMPLATES_DIR = Path(__file__).parent.parent.parent.parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
    keep_trailing_newline=True,
)
_CSS_PATH = _TEMPLATES_DIR / "style.css"


def _write_pdf(html: str, out_path: Path) -> None:
    HTML(string=html, base_url=str(_TEMPLATES_DIR)).write_pdf(
        out_path,
        stylesheets=[CSS(filename=str(_CSS_PATH))],
    )


def _render_one(template_name: str, meta: Metadata, distill: Distillation, extracted_date: str, out_path: Path) -> None:
    html = _env.get_template(template_name).render(
        meta=meta, distill=distill, extracted_date=extracted_date,
    )
    _write_pdf(html, out_path)


def render_pdfs(
    *,
    meta: Metadata,
    distill: Distillation,
    slug: str,
    output_dir: Path,
    extracted_date: str,
) -> tuple[Path, Path]:
    """Render FULL and LAZY PDFs into output_dir. Returns (full_path, lazy_path)."""
    output_dir.mkdir(parents=True, exist_ok=True)
    full_path = output_dir / f"{slug}-full.pdf"
    lazy_path = output_dir / f"{slug}-lazy.pdf"
    _render_one("full.html.jinja", meta, distill, extracted_date, full_path)
    _render_one("lazy.html.jinja", meta, distill, extracted_date, lazy_path)
    return full_path, lazy_path


def render_instructions_pdf(
    *,
    meta: Metadata,
    instructions: InstructionsAndData,
    slug: str,
    output_dir: Path,
    extracted_date: str,
) -> Path:
    """Render the INSTRUCTIONS PDF into output_dir. Returns its path."""
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{slug}-instructions.pdf"
    html = _env.get_template("instructions.html.jinja").render(
        meta=meta, instructions=instructions, extracted_date=extracted_date,
    )
    _write_pdf(html, out_path)
    return out_path
