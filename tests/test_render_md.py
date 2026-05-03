from youtube_extractor.models import Metadata, Distillation, LazyDoc, FullDoc, Chapter
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
