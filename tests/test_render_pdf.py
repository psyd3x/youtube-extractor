from youtube_extractor.models import Chapter, Distillation, FullDoc, LazyDoc, Metadata
from youtube_extractor.pipeline.render_pdf import render_pdfs

PDF_MAGIC = b"%PDF-"


def _meta(): return Metadata(video_id="abc", title="V", channel="C", duration_s=600)
def _distill():
    return Distillation(
        title="V", tldr="T",
        lazy=LazyDoc(key_points=["a"], summary_paragraph="p"),
        full=FullDoc(chapters=[Chapter(title="c", summary="s", key_points=["k"], quotes=["q"])]),
    )


def test_render_pdfs_writes_two_files(tmp_path):
    full_path, lazy_path = render_pdfs(
        meta=_meta(),
        distill=_distill(),
        slug="2024-01-15-abc-v",
        output_dir=tmp_path,
        extracted_date="2026-05-03",
    )
    assert full_path.exists() and lazy_path.exists()
    assert full_path.read_bytes()[:5] == PDF_MAGIC
    assert lazy_path.read_bytes()[:5] == PDF_MAGIC
    assert full_path.stat().st_size >= lazy_path.stat().st_size
