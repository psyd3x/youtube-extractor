from youtube_extractor.models import (
    Chapter,
    Distillation,
    FullDoc,
    InstructionsAndData,
    LazyDoc,
    Metadata,
    PromptItem,
    ResourceItem,
    Step,
)
from youtube_extractor.pipeline.render_md import render_markdown


def _meta() -> Metadata:
    return Metadata(video_id="abc", title="My Video", channel="Ch", duration_s=600, published="2024-01-15")


def _distill() -> Distillation:
    return Distillation(
        title="My Video",
        tldr="Short take.",
        lazy=LazyDoc(key_points=["a", "b"], summary_paragraph="A para."),
        full=FullDoc(
            chapters=[Chapter(title="Intro", summary="s", key_points=["k"], quotes=["q"])],
            topics=["ai"], people=["X"], references=["http://r"],
        ),
    )


def _instructions() -> InstructionsAndData:
    return InstructionsAndData(
        goal="Build a retrieval-augmented app.",
        kind="tutorial",
        prerequisites=["python 3.11"],
        steps=[Step(n=1, action="Install deps", detail="from pypi", command="pip install chromadb")],
        prompts=[PromptItem(label="system", text="you are helpful")],
        commands=["pip install chromadb"],
        resources=[ResourceItem(label="Docs", url="https://example.com/docs")],
        config=["CHROMA_PATH=/data"],
        notes=["one gap"],
        vault_links=["[[ChromaDB]]"],
    )


def test_render_markdown_writes_file(tmp_path):
    out = render_markdown(
        meta=_meta(),
        distill=_distill(),
        slug="2024-01-15-abc-my-video",
        vault_dir=tmp_path,
        pdf_full_path="/x/full.pdf",
        pdf_lazy_path="/x/lazy.pdf",
        extracted_date="2026-05-03",
    )
    assert out.exists()
    text = out.read_text()
    assert "# My Video" in text
    assert "TL;DR" in text
    assert "ai" in text
    assert "[!summary]" in text
    assert "/x/full.pdf" in text
    # With instructions defaulting to None, the new section must be omitted entirely.
    assert "Instructions and data" not in text


def test_render_markdown_omits_instructions_section_when_none(tmp_path):
    """Default (instructions=None) renders exactly as before — no instructions section."""
    out = render_markdown(
        meta=_meta(),
        distill=_distill(),
        slug="s",
        vault_dir=tmp_path,
        pdf_full_path="/x/full.pdf",
        pdf_lazy_path="/x/lazy.pdf",
        extracted_date="2026-05-03",
        instructions=None,
        pdf_instructions_path=None,
    )
    text = out.read_text()
    assert "Instructions and data" not in text
    assert "[!goal]" not in text


def test_render_markdown_includes_instructions_section_when_provided(tmp_path):
    out = render_markdown(
        meta=_meta(),
        distill=_distill(),
        slug="s",
        vault_dir=tmp_path,
        pdf_full_path="/x/full.pdf",
        pdf_lazy_path="/x/lazy.pdf",
        extracted_date="2026-05-03",
        instructions=_instructions(),
        pdf_instructions_path="/x/instructions.pdf",
    )
    text = out.read_text()
    assert "## Instructions and data" in text
    assert "[!goal] Goal (tutorial)" in text
    assert "Build a retrieval-augmented app." in text
    assert "Install deps" in text
    assert "pip install chromadb" in text
    assert "[[ChromaDB]]" in text
    assert "/x/instructions.pdf" in text
