from youtube_extractor.models import (
    Chapter,
    Distillation,
    FullDoc,
    JobRecord,
    JobStatus,
    LazyDoc,
    Metadata,
    Transcript,
    TranscriptSegment,
)


def test_metadata_construct():
    m = Metadata(
        video_id="abc123",
        title="Sample",
        channel="Ch",
        duration_s=600,
        published="2024-01-15",
        thumbnail_url="https://x/y.jpg",
        description="d",
    )
    assert m.video_id == "abc123"
    assert m.duration_s == 600


def test_transcript_segments():
    t = Transcript(
        segments=[TranscriptSegment(start=0.0, dur=2.5, text="hi")],
        full_text="hi",
        language="en",
        source="official",
    )
    assert t.segments[0].text == "hi"
    assert t.source == "official"


def test_distillation_round_trip():
    d = Distillation(
        title="t",
        tldr="s",
        lazy=LazyDoc(key_points=["a"], summary_paragraph="x"),
        full=FullDoc(
            chapters=[Chapter(title="c", summary="s", key_points=["k"], quotes=["q"])],
            topics=["x"],
            people=["y"],
            references=["z"],
        ),
    )
    j = d.model_dump_json()
    parsed = Distillation.model_validate_json(j)
    assert parsed.full.chapters[0].title == "c"


def test_job_status_values():
    assert JobStatus.queued.value == "queued"
    assert JobStatus.failed.value == "failed"


def test_job_record_minimal():
    j = JobRecord(id="j1", url="u", status=JobStatus.queued)
    assert j.error_code is None
    assert j.retryable is True
