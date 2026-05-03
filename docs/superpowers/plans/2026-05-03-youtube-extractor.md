---
title: YouTube Extractor — Implementation Plan
description: Task-by-task plan to build the YouTube Extractor public Python service, ship the CLI + launchd unit, and wire the Mission Control tab. Designed for parallel agent dispatch where independent tasks allow.
date: 2026-05-03
type: plan
project: youtube-extractor
tags: [youtube-extractor, plan, implementation]
related:
  - "[[2026-05-03-youtube-extractor-design]]"
  - "[[Mission Control]]"
  - "[[Hermes]]"
---

# YouTube Extractor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a public Python service (`github.com/psyd3x/youtube-extractor`) that turns a YouTube URL into a distilled `.md` file in the user's Obsidian vault plus FULL and LAZY PDFs, with a Mission Control tab as one consumer.

**Architecture:** Standalone FastAPI service on `127.0.0.1:18765` with a 6-stage pipeline (url → metadata → transcript → distill → render → store). Calls the Hermes LLM router (`:8642`) by default; configurable to any OpenAI-compatible endpoint. Mission Control owns the UI tab and proxies through `/api/youtube/*`. Files land in `~/.claude/obsidian-mind/youtube/` (`.md`) and `~/Youtube-extractor/output/` (PDFs + meta JSON + catalog NDJSON).

**Tech Stack:** Python 3.11, FastAPI, uvicorn, yt-dlp, youtube-transcript-api, httpx (Hermes calls), Jinja2, WeasyPrint, Click (CLI), pytest + ruff, GitHub Actions CI. Mission Control side: existing Next.js 14 / TS / React 18 stack.

**Spec:** `~/Youtube-extractor/docs/specs/2026-05-03-youtube-extractor-design.md`

---

## File map

### `youtube-extractor` repo (public)

```
~/Youtube-extractor/
├── README.md
├── LICENSE                              # MIT
├── CLAUDE.md                            # repo conventions
├── pyproject.toml                       # deps, ruff, pytest config
├── .env.example
├── .gitignore                           # output/, .env, .venv, __pycache__, *.pdf
├── docs/
│   ├── specs/2026-05-03-youtube-extractor-design.md   (exists)
│   └── superpowers/plans/2026-05-03-youtube-extractor.md (this file)
├── src/youtube_extractor/
│   ├── __init__.py
│   ├── config.py                        # env loading
│   ├── models.py                        # Pydantic types
│   ├── main.py                          # FastAPI app + uvicorn entrypoint
│   ├── cli.py                           # Click standalone CLI
│   ├── api/
│   │   ├── __init__.py
│   │   ├── jobs.py                      # POST /jobs, GET /jobs/{id}, POST /jobs/{id}/retry
│   │   ├── archive.py                   # GET /archive
│   │   └── files.py                     # GET /pdfs/.., /files/.../md
│   ├── pipeline/
│   │   ├── __init__.py
│   │   ├── url.py                       # video_id extractor
│   │   ├── metadata.py                  # yt-dlp metadata
│   │   ├── transcript.py                # youtube-transcript-api
│   │   ├── distill.py                   # Hermes call, JSON contract
│   │   ├── render_md.py                 # Obsidian markdown writer
│   │   └── render_pdf.py                # WeasyPrint HTML→PDF
│   ├── store/
│   │   ├── __init__.py
│   │   ├── catalog.py                   # append-only NDJSON
│   │   ├── search.py                    # substring search
│   │   └── jobs.py                      # in-memory + NDJSON job state
│   └── llm/
│       ├── __init__.py
│       └── client.py                    # OpenAI-compatible HTTP client
├── templates/
│   ├── full.html.jinja                  # PDF FULL template
│   ├── lazy.html.jinja                  # PDF LAZY template
│   ├── obsidian.md.jinja                # Markdown for vault
│   └── style.css                        # PDF print stylesheet
├── tests/
│   ├── __init__.py
│   ├── conftest.py
│   ├── fixtures/
│   │   ├── sample_metadata.json
│   │   ├── sample_transcript.json
│   │   └── sample_distillation.json
│   ├── test_url.py
│   ├── test_metadata.py
│   ├── test_transcript.py
│   ├── test_distill.py
│   ├── test_render_md.py
│   ├── test_render_pdf.py
│   ├── test_catalog.py
│   ├── test_search.py
│   └── test_api.py
├── deploy/
│   └── com.deedee.youtube-extractor.plist   # launchd unit
└── .github/
    └── workflows/
        └── ci.yml                        # pytest + ruff on push
```

### `OpenDeeDee/mission-control` repo (private, existing)

```
src/
├── app/
│   ├── youtube/
│   │   ├── page.tsx                     # /youtube tab
│   │   └── _components/
│   │       ├── PasteForm.tsx
│   │       ├── ActiveJobs.tsx
│   │       ├── ArchiveList.tsx
│   │       ├── SearchBox.tsx
│   │       └── MarkdownViewer.tsx       # for non-Mac
│   └── api/youtube/
│       ├── jobs/route.ts                # POST /jobs, GET /jobs/[id]
│       ├── jobs/[id]/retry/route.ts
│       ├── archive/route.ts
│       └── files/[slug]/[kind]/route.ts # serves PDF + .md bytes
├── lib/
│   └── youtube-extractor.ts             # typed HTTP client to extractor service
└── components/
    └── Sidebar.tsx                      # +1 nav entry
```

---

## Execution waves (parallelism map)

```
Wave 0 (sequential)      Wave 1 (5-way parallel)            Wave 2 (sequential)        Wave 3 (parallel)            Wave 4
═══════════════════════  ═══════════════════════════════    ═════════════════════════  ═══════════════════════════  ════════════════
Tasks 1-5                Tasks 6-15                          Tasks 16-20                Tasks 21-22 / 23-30          Tasks 31-32
Repo scaffold            Pipeline modules                    API + service wiring       CLI + launchd / MC tab       E2E + docs
                         (url, metadata, transcript,                                                                  smoke
                          llm, distill, render, store,
                          catalog, search, jobs-store)
```

Wave 1 tasks share no files — safe to dispatch as 5 parallel agents.

---

## Wave 0 — Repo scaffold (sequential)

### Task 1: Initialize repo + gitignore

**Repo:** youtube-extractor
**Depends on:** none
**Files:**
- Create: `~/Youtube-extractor/.gitignore`

- [ ] **Step 1: Init git repo**

```bash
cd ~/Youtube-extractor
git init -b main
```

- [ ] **Step 2: Write `.gitignore`**

```
# Python
__pycache__/
*.py[cod]
*.egg-info/
.venv/
venv/
.pytest_cache/
.ruff_cache/

# Project artefacts
output/
*.pdf
catalog.ndjson
jobs.ndjson

# Secrets
.env
.env.local

# OS
.DS_Store
Thumbs.db

# IDE
.vscode/
.idea/
```

- [ ] **Step 3: Commit**

```bash
git add .gitignore
git commit -m "chore: init repo with gitignore"
```

---

### Task 2: pyproject.toml + dev deps

**Repo:** youtube-extractor
**Depends on:** Task 1
**Files:**
- Create: `~/Youtube-extractor/pyproject.toml`

- [ ] **Step 1: Write pyproject.toml**

```toml
[project]
name = "youtube-extractor"
version = "0.1.0"
description = "Turn a YouTube link into a distilled Obsidian .md plus FULL and LAZY PDFs."
readme = "README.md"
license = {text = "MIT"}
requires-python = ">=3.11"
authors = [{name = "psyd3x"}]
dependencies = [
  "fastapi>=0.115",
  "uvicorn[standard]>=0.32",
  "httpx>=0.27",
  "pydantic>=2.9",
  "pydantic-settings>=2.5",
  "yt-dlp>=2024.10.0",
  "youtube-transcript-api>=0.6.2",
  "jinja2>=3.1",
  "weasyprint>=63.0",
  "click>=8.1",
  "python-slugify>=8.0",
]

[project.optional-dependencies]
dev = [
  "pytest>=8.3",
  "pytest-asyncio>=0.24",
  "pytest-mock>=3.14",
  "respx>=0.21",
  "ruff>=0.7",
]

[project.scripts]
youtube-extractor = "youtube_extractor.cli:cli"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/youtube_extractor"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "SIM"]
ignore = ["E501"]

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"
```

- [ ] **Step 2: Create venv + install dev deps**

```bash
cd ~/Youtube-extractor
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Expected: installs successfully, `youtube-extractor --help` works (will fail until cli.py exists, that's fine for now).

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml
git commit -m "chore: add pyproject.toml with deps and dev tooling"
```

---

### Task 3: README + LICENSE + .env.example + CLAUDE.md

**Repo:** youtube-extractor
**Depends on:** Task 1
**Files:**
- Create: `~/Youtube-extractor/README.md`
- Create: `~/Youtube-extractor/LICENSE`
- Create: `~/Youtube-extractor/.env.example`
- Create: `~/Youtube-extractor/CLAUDE.md`

- [ ] **Step 1: Write LICENSE (MIT)**

```
MIT License

Copyright (c) 2026 Eliasz Bykowski (psyd3x)

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

- [ ] **Step 2: Write .env.example**

```bash
# LLM endpoint — any OpenAI-compatible API
LLM_BASE_URL=http://localhost:8642
LLM_API_KEY=
LLM_MODEL=

# Storage
OBSIDIAN_VAULT_PATH=~/.claude/obsidian-mind/youtube
OUTPUT_DIR=./output

# Service
HOST=127.0.0.1
PORT=18765
LOG_LEVEL=INFO

# Behaviour
MAX_CONCURRENT_JOBS=2
LLM_TIMEOUT_S=300
TRANSCRIPT_RETRIES=3
```

- [ ] **Step 3: Write README.md**

```markdown
# YouTube Extractor

Turn a YouTube link into a distilled Markdown note in your Obsidian vault plus two PDFs (FULL + LAZY) — calling any OpenAI-compatible LLM endpoint to do the distillation.

## Why

Watching long videos is slow. Reading distilled notes is fast. This service takes a YouTube URL and produces a comprehensive `.md` in your knowledge base plus print-ready PDFs, never storing the raw transcript — only the substance.

## Quickstart

```bash
git clone https://github.com/psyd3x/youtube-extractor.git
cd youtube-extractor
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
# edit .env — at minimum set LLM_BASE_URL to your OpenAI-compatible endpoint
youtube-extractor extract https://youtube.com/watch?v=dQw4w9WgXcQ
```

Outputs land in:
- `$OBSIDIAN_VAULT_PATH/{slug}.md`
- `$OUTPUT_DIR/{slug}-full.pdf`
- `$OUTPUT_DIR/{slug}-lazy.pdf`

## Run as a service

```bash
youtube-extractor serve
# binds 127.0.0.1:18765 by default
```

REST API surface: see `docs/specs/2026-05-03-youtube-extractor-design.md`.

## Configuration

All paths and endpoints are env-overridable. See `.env.example`.

LLM backend works with any OpenAI-compatible API:
- [Hermes](https://github.com/psyd3x/hermes) (default)
- vLLM, Ollama, LM Studio (local)
- OpenAI, OpenRouter, Anthropic via proxy (cloud)

## How I use it

I run this on a Mac Studio with a tab in [Mission Control](https://github.com/psyd3x/OpenDeeDee) (private) that proxies to it. The LLM lives on a DGX Spark on my LAN, routed through Hermes. End-to-end takes ~90 seconds for a 1-hour video.

## Architecture

See `docs/specs/2026-05-03-youtube-extractor-design.md` for the full design including pipeline, storage layout, and error handling.

## Roadmap

- [ ] v2: Whisper fallback for videos without official captions
- [ ] v2: Batch / playlist input
- [ ] v3: Browser extension

## License

MIT
```

- [ ] **Step 4: Write CLAUDE.md**

```markdown
# YouTube Extractor — Repo Conventions

## Stack
- Python 3.11, FastAPI, pytest, ruff
- See `pyproject.toml` for full dep list

## Commands
```bash
source .venv/bin/activate     # activate venv
pytest -q                     # run tests
ruff check src tests          # lint
ruff format src tests         # format
youtube-extractor serve       # run service
youtube-extractor extract URL # one-shot CLI
```

## Conventions
- Type hints everywhere; Pydantic models for I/O
- One responsibility per module
- TDD where it fits; pure config files don't need failing-test ceremony
- Keep `pipeline/` modules pure: input → output, no global state
- Service layer (`api/`, `main.py`) owns concurrency + side effects

## What NOT to commit
- `.env` (real config — use `.env.example` for the template)
- `output/` (generated PDFs and catalog)
- Real video URLs in fixtures (use stable placeholder IDs)
```

- [ ] **Step 5: Commit**

```bash
git add README.md LICENSE .env.example CLAUDE.md
git commit -m "docs: add README, LICENSE, .env.example, CLAUDE.md"
```

---

### Task 4: GitHub Actions CI

**Repo:** youtube-extractor
**Depends on:** Task 2
**Files:**
- Create: `~/Youtube-extractor/.github/workflows/ci.yml`

- [ ] **Step 1: Write CI workflow**

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
          cache: "pip"
      - name: Install system deps for WeasyPrint
        run: sudo apt-get update && sudo apt-get install -y libpango-1.0-0 libpangoft2-1.0-0
      - name: Install
        run: pip install -e ".[dev]"
      - name: Lint
        run: ruff check src tests
      - name: Test
        run: pytest -q
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add pytest + ruff GitHub Actions workflow"
```

---

### Task 5: Create public GitHub repo + push

**Repo:** youtube-extractor (push)
**Depends on:** Tasks 1-4
**Files:** none new — pushing existing commits

- [ ] **Step 1: Pre-push secret scan**

```bash
cd ~/Youtube-extractor
git diff --cached --name-only
git log --all --pretty=format: --name-only --diff-filter=A | sort -u | grep -iE "\.env$|secret|credential|id_rsa|api.key"
```

Expected: no matches. If any, halt and review per the global GitHub-pre-push-security rule.

- [ ] **Step 2: Create the public GitHub repo via gh CLI**

```bash
gh repo create psyd3x/youtube-extractor --public \
  --description "Turn a YouTube link into a distilled Obsidian .md plus FULL and LAZY PDFs." \
  --homepage "" \
  --source . --remote origin --push
```

Expected: repo created at `https://github.com/psyd3x/youtube-extractor`, main branch pushed.

- [ ] **Step 3: Verify CI runs green**

```bash
gh run watch
```

Expected: lint + test pass on first run (no source files yet, but no failures either — pytest reports "no tests ran", which is a 5 exit, so adjust the workflow if needed; see Step 4).

- [ ] **Step 4: Add a placeholder smoke test so first CI run is green**

Create `tests/test_placeholder.py`:

```python
def test_placeholder():
    assert True
```

```bash
git add tests/test_placeholder.py tests/__init__.py
echo "" > tests/__init__.py
git add tests/__init__.py
git commit -m "test: add placeholder smoke test for green CI"
git push
```

Expected: green CI run.


---

### Task 6: Package skeleton — config, models, shared types

**Repo:** youtube-extractor
**Depends on:** Task 2
**Files:**
- Create: `~/Youtube-extractor/src/youtube_extractor/__init__.py`
- Create: `~/Youtube-extractor/src/youtube_extractor/config.py`
- Create: `~/Youtube-extractor/src/youtube_extractor/models.py`
- Create: `~/Youtube-extractor/tests/__init__.py` (already created in Task 5 if you stamped it; idempotent)
- Test: `~/Youtube-extractor/tests/test_config.py`, `~/Youtube-extractor/tests/test_models.py`

- [ ] **Step 1: Empty package init**

```python
# src/youtube_extractor/__init__.py
__version__ = "0.1.0"
```

- [ ] **Step 2: Write the failing config test**

```python
# tests/test_config.py
import os
from youtube_extractor.config import Settings


def test_settings_loads_defaults(monkeypatch):
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    monkeypatch.delenv("OUTPUT_DIR", raising=False)
    monkeypatch.delenv("OBSIDIAN_VAULT_PATH", raising=False)
    s = Settings()
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
```

- [ ] **Step 3: Run test, verify it fails**

```bash
pytest tests/test_config.py -v
```

Expected: ImportError — `Settings` not defined.

- [ ] **Step 4: Implement config.py**

```python
# src/youtube_extractor/config.py
from pathlib import Path
from pydantic import Field, field_validator
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

    @field_validator("obsidian_vault_path", "output_dir", mode="after")
    @classmethod
    def _expand(cls, v: Path) -> Path:
        return v.expanduser().resolve()


settings = Settings()
```

- [ ] **Step 5: Verify config tests pass**

```bash
pytest tests/test_config.py -v
```

Expected: 3/3 PASS.

- [ ] **Step 6: Write the failing models test**

```python
# tests/test_models.py
from youtube_extractor.models import (
    Metadata, Transcript, TranscriptSegment, FullDoc, LazyDoc,
    Distillation, Chapter, JobStatus, JobRecord,
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
        title="t", tldr="s",
        lazy=LazyDoc(key_points=["a"], summary_paragraph="x"),
        full=FullDoc(
            chapters=[Chapter(title="c", summary="s", key_points=["k"], quotes=["q"])],
            topics=["x"], people=["y"], references=["z"],
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
```

- [ ] **Step 7: Run, verify fail**

```bash
pytest tests/test_models.py -v
```

Expected: ImportError.

- [ ] **Step 8: Implement models.py**

```python
# src/youtube_extractor/models.py
from __future__ import annotations
from enum import Enum
from typing import Literal
from pydantic import BaseModel


class Metadata(BaseModel):
    video_id: str
    title: str
    channel: str
    duration_s: int
    published: str | None = None
    thumbnail_url: str | None = None
    description: str | None = None


class TranscriptSegment(BaseModel):
    start: float
    dur: float
    text: str


class Transcript(BaseModel):
    segments: list[TranscriptSegment]
    full_text: str
    language: str | None = None
    source: Literal["official", "whisper"] = "official"


class Chapter(BaseModel):
    title: str
    summary: str
    key_points: list[str] = []
    quotes: list[str] = []


class FullDoc(BaseModel):
    chapters: list[Chapter] = []
    topics: list[str] = []
    people: list[str] = []
    references: list[str] = []


class LazyDoc(BaseModel):
    key_points: list[str] = []
    summary_paragraph: str = ""


class Distillation(BaseModel):
    title: str
    tldr: str
    lazy: LazyDoc
    full: FullDoc


class JobStatus(str, Enum):
    queued = "queued"
    running = "running"
    done = "done"
    failed = "failed"
    partial_success = "partial_success"


class JobStage(str, Enum):
    metadata = "metadata"
    transcript = "transcript"
    distill = "distill"
    render_md = "render_md"
    render_pdf = "render_pdf"
    store = "store"


class JobRecord(BaseModel):
    id: str
    url: str
    slug: str | None = None
    status: JobStatus
    stage: JobStage | None = None
    error_code: str | None = None
    error_message: str | None = None
    retryable: bool = True
    created_at: float | None = None
    updated_at: float | None = None
```

- [ ] **Step 9: Run, verify pass**

```bash
pytest tests/test_models.py tests/test_config.py -v
```

Expected: all PASS.

- [ ] **Step 10: Lint + commit**

```bash
ruff check src tests
ruff format src tests
git add src/youtube_extractor/__init__.py src/youtube_extractor/config.py src/youtube_extractor/models.py tests/test_config.py tests/test_models.py
git commit -m "feat: add Settings + Pydantic models for pipeline I/O"
```

---

## Wave 1 — Pipeline modules (5-way parallel)

> **Dispatch hint:** Tasks 7, 8, 9, 10, 12, 14 share no source files except shared imports from `models.py` (read-only). Group them into 4-5 parallel agents:
> - **Agent A:** Task 7 (url.py)
> - **Agent B:** Task 8 (metadata.py)
> - **Agent C:** Task 9 (transcript.py)
> - **Agent D:** Tasks 10 + 11 (LLM client → distill, sequential within agent)
> - **Agent E:** Task 12 (templates) + Task 13 (render_md) + Task 14 (render_pdf)
> - **Agent F:** Task 15 (store)
>
> Each agent commits its own work; merge happens via shared `main` branch since each Task creates only its own files.

---

### Task 7: pipeline/url.py — video ID extraction

**Repo:** youtube-extractor
**Depends on:** Task 6
**Files:**
- Create: `~/Youtube-extractor/src/youtube_extractor/pipeline/__init__.py` (empty)
- Create: `~/Youtube-extractor/src/youtube_extractor/pipeline/url.py`
- Test: `~/Youtube-extractor/tests/test_url.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_url.py
import pytest
from youtube_extractor.pipeline.url import extract_video_id, InvalidYouTubeUrl

VALID_CASES = [
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://youtube.com/watch?v=dQw4w9WgXcQ&t=42s", "dQw4w9WgXcQ"),
    ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://youtu.be/dQw4w9WgXcQ?si=abc", "dQw4w9WgXcQ"),
    ("https://www.youtube.com/embed/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://www.youtube.com/shorts/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://m.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("dQw4w9WgXcQ", "dQw4w9WgXcQ"),  # bare ID accepted
]

INVALID_CASES = [
    "https://example.com/watch?v=dQw4w9WgXcQ",
    "https://www.youtube.com/",
    "not a url",
    "",
]


@pytest.mark.parametrize("url,expected", VALID_CASES)
def test_extract_valid(url, expected):
    assert extract_video_id(url) == expected


@pytest.mark.parametrize("url", INVALID_CASES)
def test_extract_invalid(url):
    with pytest.raises(InvalidYouTubeUrl):
        extract_video_id(url)
```

- [ ] **Step 2: Run, verify fail**

```bash
pytest tests/test_url.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement**

```python
# src/youtube_extractor/pipeline/url.py
import re
from urllib.parse import urlparse, parse_qs


class InvalidYouTubeUrl(ValueError):
    pass


_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_YT_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "youtu.be"}


def extract_video_id(url: str) -> str:
    if not url or not isinstance(url, str):
        raise InvalidYouTubeUrl("empty or non-string url")

    raw = url.strip()
    # Bare 11-char ID accepted
    if _ID_RE.match(raw):
        return raw

    try:
        parsed = urlparse(raw)
    except Exception as e:
        raise InvalidYouTubeUrl(f"unparseable url: {e}") from e

    host = parsed.hostname or ""
    if host not in _YT_HOSTS:
        raise InvalidYouTubeUrl(f"not a youtube host: {host!r}")

    # youtu.be/<id>
    if host == "youtu.be":
        candidate = parsed.path.lstrip("/").split("/", 1)[0]
    # /watch?v=<id>
    elif parsed.path == "/watch":
        candidate = (parse_qs(parsed.query).get("v") or [""])[0]
    # /embed/<id> or /shorts/<id>
    elif parsed.path.startswith("/embed/") or parsed.path.startswith("/shorts/"):
        candidate = parsed.path.split("/", 2)[2].split("/", 1)[0]
    else:
        raise InvalidYouTubeUrl(f"unrecognised youtube path: {parsed.path!r}")

    if not _ID_RE.match(candidate):
        raise InvalidYouTubeUrl(f"video id failed shape check: {candidate!r}")
    return candidate
```

- [ ] **Step 4: Run, verify pass**

```bash
pytest tests/test_url.py -v
```

Expected: 12/12 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/youtube_extractor/pipeline/__init__.py src/youtube_extractor/pipeline/url.py tests/test_url.py
git commit -m "feat(pipeline): add video ID extractor with parametrised tests"
```

---

### Task 8: pipeline/metadata.py — yt-dlp wrapper

**Repo:** youtube-extractor
**Depends on:** Task 6
**Files:**
- Create: `~/Youtube-extractor/src/youtube_extractor/pipeline/metadata.py`
- Test: `~/Youtube-extractor/tests/test_metadata.py`

- [ ] **Step 1: Write the failing test (mocked yt-dlp)**

```python
# tests/test_metadata.py
from unittest.mock import patch, MagicMock
from youtube_extractor.pipeline.metadata import fetch_metadata, MetadataError


SAMPLE = {
    "id": "dQw4w9WgXcQ",
    "title": "Rick Astley - Never Gonna Give You Up",
    "uploader": "Rick Astley",
    "duration": 213,
    "upload_date": "20091025",
    "thumbnail": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",
    "description": "Music video.",
}


def test_fetch_metadata_happy(monkeypatch):
    fake = MagicMock()
    fake.__enter__.return_value.extract_info.return_value = SAMPLE
    fake.__exit__.return_value = False
    with patch("youtube_extractor.pipeline.metadata.yt_dlp.YoutubeDL", return_value=fake):
        m = fetch_metadata("dQw4w9WgXcQ")
    assert m.title.startswith("Rick Astley")
    assert m.duration_s == 213
    assert m.published == "2009-10-25"


def test_fetch_metadata_failure(monkeypatch):
    import yt_dlp
    fake = MagicMock()
    fake.__enter__.return_value.extract_info.side_effect = yt_dlp.utils.DownloadError("private video")
    fake.__exit__.return_value = False
    import pytest
    with patch("youtube_extractor.pipeline.metadata.yt_dlp.YoutubeDL", return_value=fake):
        with pytest.raises(MetadataError):
            fetch_metadata("dQw4w9WgXcQ")
```

- [ ] **Step 2: Run, verify fail**

```bash
pytest tests/test_metadata.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement**

```python
# src/youtube_extractor/pipeline/metadata.py
from __future__ import annotations
import yt_dlp
from youtube_extractor.models import Metadata


class MetadataError(Exception):
    pass


def _format_date(yyyymmdd: str | None) -> str | None:
    if not yyyymmdd or len(yyyymmdd) != 8:
        return None
    return f"{yyyymmdd[0:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}"


def fetch_metadata(video_id: str) -> Metadata:
    """Fetch video metadata via yt-dlp without downloading the video itself."""
    url = f"https://www.youtube.com/watch?v={video_id}"
    opts = {"quiet": True, "skip_download": True, "no_warnings": True}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as e:
        raise MetadataError(f"yt-dlp could not fetch metadata for {video_id}: {e}") from e
    except Exception as e:
        raise MetadataError(f"unexpected metadata error: {e}") from e

    if not info:
        raise MetadataError("yt-dlp returned empty info")

    return Metadata(
        video_id=info.get("id", video_id),
        title=info.get("title", ""),
        channel=info.get("uploader") or info.get("channel") or "",
        duration_s=int(info.get("duration") or 0),
        published=_format_date(info.get("upload_date")),
        thumbnail_url=info.get("thumbnail"),
        description=info.get("description"),
    )
```

- [ ] **Step 4: Run, verify pass**

```bash
pytest tests/test_metadata.py -v
```

Expected: 2/2 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/youtube_extractor/pipeline/metadata.py tests/test_metadata.py
git commit -m "feat(pipeline): add metadata fetcher backed by yt-dlp"
```

---

### Task 9: pipeline/transcript.py — youtube-transcript-api

**Repo:** youtube-extractor
**Depends on:** Task 6
**Files:**
- Create: `~/Youtube-extractor/src/youtube_extractor/pipeline/transcript.py`
- Test: `~/Youtube-extractor/tests/test_transcript.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_transcript.py
from unittest.mock import patch
import pytest
from youtube_extractor.pipeline.transcript import (
    fetch_transcript, NoTranscriptError,
)


SAMPLE_FETCH = [
    {"text": "Never gonna give you up", "start": 0.0, "duration": 2.5},
    {"text": "Never gonna let you down", "start": 2.5, "duration": 2.5},
]


def test_fetch_transcript_happy(monkeypatch):
    with patch(
        "youtube_extractor.pipeline.transcript.YouTubeTranscriptApi.get_transcript",
        return_value=SAMPLE_FETCH,
    ):
        t = fetch_transcript("dQw4w9WgXcQ")
    assert len(t.segments) == 2
    assert t.segments[0].text == "Never gonna give you up"
    assert "let you down" in t.full_text
    assert t.source == "official"


def test_fetch_transcript_unavailable(monkeypatch):
    from youtube_transcript_api._errors import TranscriptsDisabled
    with patch(
        "youtube_extractor.pipeline.transcript.YouTubeTranscriptApi.get_transcript",
        side_effect=TranscriptsDisabled("dQw4w9WgXcQ"),
    ):
        with pytest.raises(NoTranscriptError):
            fetch_transcript("dQw4w9WgXcQ")
```

- [ ] **Step 2: Run, verify fail**

```bash
pytest tests/test_transcript.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement**

```python
# src/youtube_extractor/pipeline/transcript.py
from __future__ import annotations
import time
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled, NoTranscriptFound, VideoUnavailable,
)
from youtube_extractor.models import Transcript, TranscriptSegment
from youtube_extractor.config import settings


class NoTranscriptError(Exception):
    pass


def fetch_transcript(video_id: str) -> Transcript:
    """Fetch the official transcript for a video, with bounded retries on transient errors."""
    last_exc: Exception | None = None
    delay = 1.0
    for attempt in range(settings.transcript_retries):
        try:
            entries = YouTubeTranscriptApi.get_transcript(video_id)
            break
        except (TranscriptsDisabled, NoTranscriptFound, VideoUnavailable) as e:
            # Permanent — no point retrying
            raise NoTranscriptError(f"no official transcript for {video_id}: {e}") from e
        except Exception as e:
            # Transient — retry
            last_exc = e
            if attempt < settings.transcript_retries - 1:
                time.sleep(delay)
                delay *= 2
    else:
        raise NoTranscriptError(f"transcript fetch failed after retries: {last_exc}") from last_exc

    segments = [
        TranscriptSegment(start=float(e["start"]), dur=float(e["duration"]), text=e["text"])
        for e in entries
    ]
    full_text = " ".join(s.text for s in segments)
    return Transcript(segments=segments, full_text=full_text, language="en", source="official")
```

- [ ] **Step 4: Run, verify pass**

```bash
pytest tests/test_transcript.py -v
```

Expected: 2/2 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/youtube_extractor/pipeline/transcript.py tests/test_transcript.py
git commit -m "feat(pipeline): add transcript fetcher with retry on transient errors"
```

---

### Task 10: llm/client.py — OpenAI-compatible HTTP client

**Repo:** youtube-extractor
**Depends on:** Task 6
**Files:**
- Create: `~/Youtube-extractor/src/youtube_extractor/llm/__init__.py` (empty)
- Create: `~/Youtube-extractor/src/youtube_extractor/llm/client.py`
- Test: `~/Youtube-extractor/tests/test_llm_client.py`

- [ ] **Step 1: Write failing tests (mock with respx)**

```python
# tests/test_llm_client.py
import json
import httpx
import pytest
import respx
from youtube_extractor.llm.client import LLMClient, LLMError


@respx.mock
async def test_chat_json_happy():
    respx.post("http://x/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [{
                    "message": {"role": "assistant", "content": '{"answer": 42}'}
                }]
            },
        )
    )
    client = LLMClient(base_url="http://x", api_key=None, timeout_s=5)
    result = await client.chat_json(
        system="be helpful",
        user="prompt",
        response_schema_name="answer",
    )
    assert result == {"answer": 42}


@respx.mock
async def test_chat_json_retries_on_bad_json():
    route = respx.post("http://x/v1/chat/completions").mock(
        side_effect=[
            httpx.Response(200, json={"choices": [{"message": {"content": "not-json"}}]}),
            httpx.Response(200, json={"choices": [{"message": {"content": '{"ok": true}'}}]}),
        ]
    )
    client = LLMClient(base_url="http://x", api_key=None, timeout_s=5)
    result = await client.chat_json(system="s", user="u", response_schema_name="x")
    assert result == {"ok": True}
    assert route.call_count == 2


@respx.mock
async def test_chat_json_fails_after_retries():
    respx.post("http://x/v1/chat/completions").mock(
        return_value=httpx.Response(200, json={"choices": [{"message": {"content": "still-not-json"}}]})
    )
    client = LLMClient(base_url="http://x", api_key=None, timeout_s=5)
    with pytest.raises(LLMError):
        await client.chat_json(system="s", user="u", response_schema_name="x")


@respx.mock
async def test_http_error():
    respx.post("http://x/v1/chat/completions").mock(return_value=httpx.Response(503))
    client = LLMClient(base_url="http://x", api_key=None, timeout_s=5)
    with pytest.raises(LLMError):
        await client.chat_json(system="s", user="u", response_schema_name="x")
```

- [ ] **Step 2: Run, verify fail**

```bash
pytest tests/test_llm_client.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement**

```python
# src/youtube_extractor/llm/client.py
from __future__ import annotations
import json
import httpx


class LLMError(Exception):
    pass


class LLMClient:
    """Minimal OpenAI-compatible chat client. Works with Hermes, vLLM, Ollama, OpenAI."""

    def __init__(
        self,
        base_url: str,
        api_key: str | None = None,
        model: str | None = None,
        timeout_s: int = 300,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout_s = timeout_s

    async def chat_json(
        self,
        *,
        system: str,
        user: str,
        response_schema_name: str,
        max_retries: int = 1,
    ) -> dict:
        """Call /v1/chat/completions with JSON-mode and parse the response.
        Retries once on malformed JSON; raises LLMError otherwise.
        """
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        body = {
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
        }
        if self.model:
            body["model"] = self.model

        last_err: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout_s) as cli:
                    r = await cli.post(f"{self.base_url}/v1/chat/completions", json=body, headers=headers)
            except httpx.HTTPError as e:
                raise LLMError(f"transport error to {self.base_url}: {e}") from e

            if r.status_code != 200:
                raise LLMError(f"upstream {r.status_code}: {r.text[:200]}")

            try:
                payload = r.json()
                content = payload["choices"][0]["message"]["content"]
                return json.loads(content)
            except (KeyError, IndexError, ValueError, json.JSONDecodeError) as e:
                last_err = e
                continue  # retry once

        raise LLMError(f"could not parse JSON after {max_retries + 1} attempts ({response_schema_name}): {last_err}")
```

- [ ] **Step 4: Run, verify pass**

```bash
pytest tests/test_llm_client.py -v
```

Expected: 4/4 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/youtube_extractor/llm/__init__.py src/youtube_extractor/llm/client.py tests/test_llm_client.py
git commit -m "feat(llm): add OpenAI-compatible chat client with JSON-mode + one retry"
```

---

### Task 11: pipeline/distill.py — call LLM, return Distillation

**Repo:** youtube-extractor
**Depends on:** Task 6, Task 10
**Files:**
- Create: `~/Youtube-extractor/src/youtube_extractor/pipeline/distill.py`
- Test: `~/Youtube-extractor/tests/test_distill.py`
- Test fixture: `~/Youtube-extractor/tests/fixtures/sample_distillation.json`

- [ ] **Step 1: Write fixture**

```json
// tests/fixtures/sample_distillation.json
{
  "title": "Test Video",
  "tldr": "A short summary.",
  "lazy": {
    "key_points": ["Point one", "Point two"],
    "summary_paragraph": "A paragraph."
  },
  "full": {
    "chapters": [
      {"title": "Intro", "summary": "Intro summary", "key_points": ["k1"], "quotes": ["q1"]}
    ],
    "topics": ["test"], "people": [], "references": []
  }
}
```

- [ ] **Step 2: Write failing test**

```python
# tests/test_distill.py
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from youtube_extractor.models import Metadata, Transcript, TranscriptSegment
from youtube_extractor.pipeline.distill import distill, DistillError

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "sample_distillation.json").read_text())


def _meta() -> Metadata:
    return Metadata(video_id="abc", title="t", channel="c", duration_s=600)


def _short_transcript() -> Transcript:
    return Transcript(
        segments=[TranscriptSegment(start=0, dur=2, text="hello world " * 50)],
        full_text="hello world " * 500,
        language="en",
        source="official",
    )


async def test_distill_short_video():
    fake = AsyncMock(return_value=FIXTURE)
    with patch("youtube_extractor.pipeline.distill.LLMClient.chat_json", fake):
        d = await distill(_meta(), _short_transcript())
    assert d.title == "Test Video"
    assert d.lazy.key_points == ["Point one", "Point two"]
    assert d.full.chapters[0].title == "Intro"


async def test_distill_chunked_long_video():
    """Long transcripts get chunked; consolidation merges into one Distillation."""
    long_transcript = Transcript(
        segments=[TranscriptSegment(start=0, dur=1, text="x")],
        full_text=("word " * 30000),  # forces chunking
        language="en",
        source="official",
    )
    fake = AsyncMock(return_value=FIXTURE)
    with patch("youtube_extractor.pipeline.distill.LLMClient.chat_json", fake):
        d = await distill(_meta(), long_transcript)
    # consolidation pass = 1, chunk passes >= 2, total >= 3
    assert fake.call_count >= 3
    assert d.title  # still produces a Distillation
```

- [ ] **Step 3: Run, verify fail**

```bash
pytest tests/test_distill.py -v
```

Expected: ImportError.

- [ ] **Step 4: Implement**

```python
# src/youtube_extractor/pipeline/distill.py
from __future__ import annotations
import json
from youtube_extractor.config import settings
from youtube_extractor.llm.client import LLMClient, LLMError
from youtube_extractor.models import Metadata, Transcript, Distillation


CHUNK_WORDS = 18000  # rough budget per chunk for safety on most context windows


class DistillError(Exception):
    pass


SYSTEM_PROMPT = """You are an expert at distilling YouTube video transcripts into structured knowledge.
You produce two outputs in one JSON response: a LAZY summary (5-10 bullet key points + a 150-word
paragraph) and a FULL chapter-by-chapter breakdown with key points, direct quotes, topics, people,
and references. Return STRICT JSON matching the requested schema. Do not invent quotes.
"""


def _user_prompt(meta: Metadata, transcript_chunk: str, is_chunk: bool, total_chunks: int = 1, idx: int = 0) -> str:
    chunk_note = (
        f"\nThis is chunk {idx+1} of {total_chunks} of a long transcript. Focus on this chunk only; "
        "consolidation will happen later."
        if is_chunk else ""
    )
    return (
        f"Title: {meta.title}\nChannel: {meta.channel}\nDuration: {meta.duration_s}s\n"
        f"Description: {(meta.description or '')[:500]}\n{chunk_note}\n\nTranscript:\n{transcript_chunk}\n\n"
        "Return JSON: {title, tldr, lazy: {key_points[], summary_paragraph}, "
        "full: {chapters: [{title, summary, key_points[], quotes[]}], topics[], people[], references[]}}"
    )


def _consolidate_prompt(meta: Metadata, partials: list[dict]) -> str:
    return (
        f"Consolidate these {len(partials)} chunk-level distillations of '{meta.title}' "
        f"into one final Distillation. Merge chapters in order, dedupe key points, "
        f"keep best quotes (verbatim). Return the same JSON schema.\n\n"
        f"Chunks:\n{json.dumps(partials, indent=2)}"
    )


def _chunk_text(text: str, max_words: int) -> list[str]:
    words = text.split()
    if len(words) <= max_words:
        return [text]
    chunks: list[str] = []
    for i in range(0, len(words), max_words):
        chunks.append(" ".join(words[i : i + max_words]))
    return chunks


async def distill(meta: Metadata, transcript: Transcript) -> Distillation:
    client = LLMClient(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        timeout_s=settings.llm_timeout_s,
    )

    chunks = _chunk_text(transcript.full_text, CHUNK_WORDS)

    if len(chunks) == 1:
        try:
            raw = await client.chat_json(
                system=SYSTEM_PROMPT,
                user=_user_prompt(meta, chunks[0], is_chunk=False),
                response_schema_name="Distillation",
            )
        except LLMError as e:
            raise DistillError(str(e)) from e
        return Distillation.model_validate(raw)

    # Multi-chunk: distill each, then consolidate.
    partials: list[dict] = []
    for i, chunk in enumerate(chunks):
        try:
            partials.append(await client.chat_json(
                system=SYSTEM_PROMPT,
                user=_user_prompt(meta, chunk, is_chunk=True, total_chunks=len(chunks), idx=i),
                response_schema_name="Distillation",
            ))
        except LLMError as e:
            raise DistillError(f"chunk {i+1}/{len(chunks)} failed: {e}") from e

    try:
        consolidated = await client.chat_json(
            system=SYSTEM_PROMPT,
            user=_consolidate_prompt(meta, partials),
            response_schema_name="Distillation",
        )
    except LLMError as e:
        raise DistillError(f"consolidation failed: {e}") from e

    return Distillation.model_validate(consolidated)
```

- [ ] **Step 5: Run, verify pass**

```bash
pytest tests/test_distill.py -v
```

Expected: 2/2 PASS.

- [ ] **Step 6: Commit**

```bash
mkdir -p tests/fixtures
git add src/youtube_extractor/pipeline/distill.py tests/test_distill.py tests/fixtures/sample_distillation.json
git commit -m "feat(pipeline): add LLM distillation with single + chunked + consolidate paths"
```

---

### Task 12: templates — markdown + PDF jinja templates + style.css

**Repo:** youtube-extractor
**Depends on:** Task 6
**Files:**
- Create: `~/Youtube-extractor/templates/obsidian.md.jinja`
- Create: `~/Youtube-extractor/templates/full.html.jinja`
- Create: `~/Youtube-extractor/templates/lazy.html.jinja`
- Create: `~/Youtube-extractor/templates/style.css`

- [ ] **Step 1: Write obsidian.md.jinja**

```jinja
---
title: "{{ meta.title | replace('"', '\\"') }}"
channel: "{{ meta.channel | replace('"', '\\"') }}"
url: https://youtube.com/watch?v={{ meta.video_id }}
duration: {{ meta.duration_s }}
{% if meta.published %}published: {{ meta.published }}{% endif %}
extracted: {{ extracted_date }}
tags: [youtube{% for t in distill.full.topics %}, {{ t }}{% endfor %}]
people: {{ distill.full.people | tojson }}
references: {{ distill.full.references | tojson }}
pdfs:
  full: "{{ pdf_full_path }}"
  lazy: "{{ pdf_lazy_path }}"
---

# {{ distill.title }}

> [!summary] TL;DR
> {{ distill.tldr }}

## Key points
{% for kp in distill.lazy.key_points %}
- {{ kp }}
{% endfor %}

## Summary
{{ distill.lazy.summary_paragraph }}

## Chapters
{% for ch in distill.full.chapters %}
### {{ loop.index }}. {{ ch.title }}

{{ ch.summary }}

{% if ch.key_points %}**Key points:**
{% for kp in ch.key_points %}- {{ kp }}
{% endfor %}{% endif %}
{% if ch.quotes %}
**Quotes:**
{% for q in ch.quotes %}> {{ q }}

{% endfor %}{% endif %}
{% endfor %}

---
*Source: [YouTube](https://youtube.com/watch?v={{ meta.video_id }}) · Extracted {{ extracted_date }} · [PDF FULL]({{ pdf_full_path }}) · [PDF LAZY]({{ pdf_lazy_path }})*
```

- [ ] **Step 2: Write style.css**

```css
@page { size: A4; margin: 18mm 16mm; }
body { font-family: -apple-system, "Segoe UI", Roboto, sans-serif; line-height: 1.5; color: #111; }
h1 { font-size: 24pt; margin-bottom: 4pt; }
h2 { font-size: 16pt; margin-top: 18pt; border-bottom: 1px solid #ddd; padding-bottom: 4pt; }
h3 { font-size: 13pt; margin-top: 14pt; }
.meta { color: #666; font-size: 10pt; margin-bottom: 16pt; }
.tldr { background: #f5f5fa; border-left: 4px solid #6366f1; padding: 10pt 12pt; margin: 12pt 0; font-size: 11pt; }
.kp { padding-left: 18pt; }
.kp li { margin-bottom: 4pt; }
.quote { border-left: 3px solid #ccc; padding: 4pt 12pt; color: #444; font-style: italic; margin: 6pt 0; }
.footer { color: #888; font-size: 9pt; margin-top: 30pt; border-top: 1px solid #eee; padding-top: 8pt; }
```

- [ ] **Step 3: Write full.html.jinja**

```jinja
<!doctype html>
<html><head><meta charset="utf-8"><title>{{ distill.title }} — FULL</title>
<link rel="stylesheet" href="style.css"></head>
<body>
<h1>{{ distill.title }}</h1>
<div class="meta">{{ meta.channel }} · {{ (meta.duration_s // 60) }} min{% if meta.published %} · {{ meta.published }}{% endif %} · YouTube</div>

<div class="tldr"><strong>TL;DR</strong> — {{ distill.tldr }}</div>

<h2>Key points</h2>
<ul class="kp">{% for kp in distill.lazy.key_points %}<li>{{ kp }}</li>{% endfor %}</ul>

<h2>Summary</h2>
<p>{{ distill.lazy.summary_paragraph }}</p>

<h2>Chapters</h2>
{% for ch in distill.full.chapters %}
<h3>{{ loop.index }}. {{ ch.title }}</h3>
<p>{{ ch.summary }}</p>
{% if ch.key_points %}<ul class="kp">{% for kp in ch.key_points %}<li>{{ kp }}</li>{% endfor %}</ul>{% endif %}
{% if ch.quotes %}{% for q in ch.quotes %}<div class="quote">"{{ q }}"</div>{% endfor %}{% endif %}
{% endfor %}

{% if distill.full.references %}<h2>References</h2><ul>{% for r in distill.full.references %}<li>{{ r }}</li>{% endfor %}</ul>{% endif %}

<div class="footer">Source: youtube.com/watch?v={{ meta.video_id }} · Extracted {{ extracted_date }}</div>
</body></html>
```

- [ ] **Step 4: Write lazy.html.jinja**

```jinja
<!doctype html>
<html><head><meta charset="utf-8"><title>{{ distill.title }} — LAZY</title>
<link rel="stylesheet" href="style.css"></head>
<body>
<h1>{{ distill.title }}</h1>
<div class="meta">{{ meta.channel }} · {{ (meta.duration_s // 60) }} min · YouTube</div>

<div class="tldr"><strong>TL;DR</strong> — {{ distill.tldr }}</div>

<h2>Key points</h2>
<ul class="kp">{% for kp in distill.lazy.key_points %}<li>{{ kp }}</li>{% endfor %}</ul>

<h2>Summary</h2>
<p>{{ distill.lazy.summary_paragraph }}</p>

<div class="footer">Source: youtube.com/watch?v={{ meta.video_id }} · Extracted {{ extracted_date }} · Want detail? Open the FULL PDF or the .md in Obsidian.</div>
</body></html>
```

- [ ] **Step 5: Commit**

```bash
git add templates/
git commit -m "feat(templates): add Obsidian markdown + FULL/LAZY HTML + print CSS templates"
```

---

### Task 13: pipeline/render_md.py — markdown writer

**Repo:** youtube-extractor
**Depends on:** Task 6, Task 12
**Files:**
- Create: `~/Youtube-extractor/src/youtube_extractor/pipeline/render_md.py`
- Test: `~/Youtube-extractor/tests/test_render_md.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_render_md.py
from pathlib import Path
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
    assert "ai" in text  # tag
    assert "[!summary]" in text  # Obsidian callout
    assert "/x/full.pdf" in text
```

- [ ] **Step 2: Run, verify fail**

```bash
pytest tests/test_render_md.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement**

```python
# src/youtube_extractor/pipeline/render_md.py
from __future__ import annotations
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape
from youtube_extractor.models import Metadata, Distillation


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
    )
    out = vault_dir / f"{slug}.md"
    out.write_text(content, encoding="utf-8")
    return out
```

- [ ] **Step 4: Run, verify pass**

```bash
pytest tests/test_render_md.py -v
```

Expected: 1/1 PASS.

- [ ] **Step 5: Commit**

```bash
git add src/youtube_extractor/pipeline/render_md.py tests/test_render_md.py
git commit -m "feat(pipeline): render Obsidian markdown via jinja"
```

---

### Task 14: pipeline/render_pdf.py — WeasyPrint HTML→PDF

**Repo:** youtube-extractor
**Depends on:** Task 6, Task 12
**Files:**
- Create: `~/Youtube-extractor/src/youtube_extractor/pipeline/render_pdf.py`
- Test: `~/Youtube-extractor/tests/test_render_pdf.py`

- [ ] **Step 1: Write failing test (smoke — verifies file exists + has PDF magic bytes)**

```python
# tests/test_render_pdf.py
from pathlib import Path
import pytest
from youtube_extractor.models import Metadata, Distillation, LazyDoc, FullDoc, Chapter
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
    # FULL should be at least as large as LAZY (more content)
    assert full_path.stat().st_size >= lazy_path.stat().st_size
```

- [ ] **Step 2: Run, verify fail**

```bash
pytest tests/test_render_pdf.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement**

```python
# src/youtube_extractor/pipeline/render_pdf.py
from __future__ import annotations
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import HTML, CSS
from youtube_extractor.models import Metadata, Distillation


_TEMPLATES_DIR = Path(__file__).parent.parent.parent.parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html"]),
    keep_trailing_newline=True,
)
_CSS_PATH = _TEMPLATES_DIR / "style.css"


def _render_one(template_name: str, meta: Metadata, distill: Distillation, extracted_date: str, out_path: Path) -> None:
    html = _env.get_template(template_name).render(
        meta=meta, distill=distill, extracted_date=extracted_date,
    )
    HTML(string=html, base_url=str(_TEMPLATES_DIR)).write_pdf(
        out_path,
        stylesheets=[CSS(filename=str(_CSS_PATH))],
    )


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
```

- [ ] **Step 4: Run, verify pass**

```bash
pytest tests/test_render_pdf.py -v
```

Expected: PASS. (If WeasyPrint complains about missing system libs, install per its docs: `brew install pango` on macOS.)

- [ ] **Step 5: Commit**

```bash
git add src/youtube_extractor/pipeline/render_pdf.py tests/test_render_pdf.py
git commit -m "feat(pipeline): render FULL + LAZY PDFs via WeasyPrint"
```

---

### Task 15: store — catalog, search, jobs

**Repo:** youtube-extractor
**Depends on:** Task 6
**Files:**
- Create: `~/Youtube-extractor/src/youtube_extractor/store/__init__.py` (empty)
- Create: `~/Youtube-extractor/src/youtube_extractor/store/catalog.py`
- Create: `~/Youtube-extractor/src/youtube_extractor/store/search.py`
- Create: `~/Youtube-extractor/src/youtube_extractor/store/jobs.py`
- Test: `~/Youtube-extractor/tests/test_store.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_store.py
from youtube_extractor.store.catalog import append_entry, read_all, find_by_video_id
from youtube_extractor.store.search import search_entries
from youtube_extractor.store.jobs import JobStore
from youtube_extractor.models import JobRecord, JobStatus


SAMPLE = {
    "slug": "2024-01-15-abc-foo",
    "video_id": "abc",
    "title": "Foo",
    "channel": "Bar",
    "url": "https://y/watch?v=abc",
    "duration": 600,
    "extracted_at": 1700000000.0,
    "md_path": "/v/foo.md",
    "pdf_full_path": "/o/foo-full.pdf",
    "pdf_lazy_path": "/o/foo-lazy.pdf",
    "tags": ["youtube"],
    "topics": ["ai"],
    "people": [],
}


def test_append_and_read(tmp_path):
    p = tmp_path / "catalog.ndjson"
    append_entry(p, SAMPLE)
    rows = read_all(p)
    assert len(rows) == 1
    assert rows[0]["title"] == "Foo"


def test_find_by_video_id(tmp_path):
    p = tmp_path / "catalog.ndjson"
    append_entry(p, SAMPLE)
    found = find_by_video_id(p, "abc")
    assert found and found["slug"] == SAMPLE["slug"]
    missing = find_by_video_id(p, "zzz")
    assert missing is None


def test_search_substring(tmp_path):
    p = tmp_path / "catalog.ndjson"
    append_entry(p, SAMPLE)
    append_entry(p, {**SAMPLE, "slug": "2024-01-16-def-bar", "video_id": "def", "title": "Other", "topics": ["crypto"]})
    rows = search_entries(p, "ai")
    assert len(rows) == 1
    assert rows[0]["video_id"] == "abc"
    rows = search_entries(p, "")
    assert len(rows) == 2  # empty query returns all


def test_jobstore_lifecycle(tmp_path):
    store = JobStore(tmp_path / "jobs.ndjson")
    job = JobRecord(id="j1", url="u", status=JobStatus.queued)
    store.put(job)
    fetched = store.get("j1")
    assert fetched and fetched.status == JobStatus.queued
    job.status = JobStatus.done
    store.put(job)
    assert store.get("j1").status == JobStatus.done
    # NDJSON file should now have 2 lines
    lines = (tmp_path / "jobs.ndjson").read_text().strip().splitlines()
    assert len(lines) == 2
```

- [ ] **Step 2: Run, verify fail**

```bash
pytest tests/test_store.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement catalog**

```python
# src/youtube_extractor/store/catalog.py
from __future__ import annotations
import json
from pathlib import Path


def append_entry(path: Path, entry: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


def read_all(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def find_by_video_id(path: Path, video_id: str) -> dict | None:
    for row in read_all(path):
        if row.get("video_id") == video_id:
            return row
    return None
```

- [ ] **Step 4: Implement search**

```python
# src/youtube_extractor/store/search.py
from __future__ import annotations
from pathlib import Path
from .catalog import read_all


_FIELDS = ("title", "channel", "tags", "topics", "people")


def search_entries(path: Path, query: str) -> list[dict]:
    rows = read_all(path)
    q = (query or "").strip().lower()
    if not q:
        return rows
    results: list[dict] = []
    for row in rows:
        haystack_parts: list[str] = []
        for f in _FIELDS:
            v = row.get(f)
            if isinstance(v, str):
                haystack_parts.append(v)
            elif isinstance(v, list):
                haystack_parts.extend(str(x) for x in v)
        haystack = " ".join(haystack_parts).lower()
        if q in haystack:
            results.append(row)
    return results
```

- [ ] **Step 5: Implement jobs store**

```python
# src/youtube_extractor/store/jobs.py
from __future__ import annotations
import json
from pathlib import Path
from threading import Lock
from youtube_extractor.models import JobRecord


class JobStore:
    """In-memory job dict mirrored to an append-only NDJSON for crash recovery."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._mem: dict[str, JobRecord] = {}
        self._lock = Lock()
        self._reload()

    def _reload(self) -> None:
        if not self.path.exists():
            return
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = JobRecord.model_validate_json(line)
                self._mem[rec.id] = rec
            except Exception:
                continue

    def put(self, job: JobRecord) -> None:
        with self._lock:
            self._mem[job.id] = job
            with self.path.open("a", encoding="utf-8") as f:
                f.write(job.model_dump_json() + "\n")

    def get(self, job_id: str) -> JobRecord | None:
        return self._mem.get(job_id)
```

- [ ] **Step 6: Run, verify pass**

```bash
pytest tests/test_store.py -v
```

Expected: 4/4 PASS.

- [ ] **Step 7: Commit**

```bash
git add src/youtube_extractor/store/ tests/test_store.py
git commit -m "feat(store): catalog NDJSON + substring search + JobStore with crash recovery"
```

---

## Wave 2 — API + service wiring (sequential)

### Task 16: pipeline orchestrator — `pipeline/orchestrator.py`

**Repo:** youtube-extractor
**Depends on:** Tasks 7, 8, 9, 11, 13, 14, 15
**Files:**
- Create: `~/Youtube-extractor/src/youtube_extractor/pipeline/orchestrator.py`
- Test: `~/Youtube-extractor/tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing test (mocks every stage)**

```python
# tests/test_orchestrator.py
from pathlib import Path
from unittest.mock import patch, AsyncMock
import pytest
from youtube_extractor.models import (
    Metadata, Transcript, TranscriptSegment, Distillation, LazyDoc, FullDoc, Chapter,
)
from youtube_extractor.pipeline.orchestrator import run_pipeline, PipelineResult


def _meta(): return Metadata(video_id="abc", title="Hello World", channel="C", duration_s=120, published="2024-01-15")
def _tx():
    return Transcript(segments=[TranscriptSegment(start=0, dur=1, text="hi")], full_text="hi", language="en", source="official")
def _di():
    return Distillation(
        title="Hello World", tldr="t",
        lazy=LazyDoc(key_points=["a"], summary_paragraph="p"),
        full=FullDoc(chapters=[Chapter(title="c", summary="s", key_points=["k"], quotes=["q"])], topics=["x"]),
    )


async def test_run_pipeline_happy(tmp_path):
    vault = tmp_path / "vault"
    output = tmp_path / "output"
    with patch("youtube_extractor.pipeline.orchestrator.fetch_metadata", return_value=_meta()), \
         patch("youtube_extractor.pipeline.orchestrator.fetch_transcript", return_value=_tx()), \
         patch("youtube_extractor.pipeline.orchestrator.distill", new=AsyncMock(return_value=_di())):
        result = await run_pipeline(
            url="https://youtu.be/abc",
            vault_dir=vault,
            output_dir=output,
        )
    assert isinstance(result, PipelineResult)
    assert result.md_path.exists()
    assert result.pdf_full_path.exists()
    assert result.pdf_lazy_path.exists()
    assert result.slug.startswith("2024-01-15-abc-")
    # catalog row was appended
    cat = output / "catalog.ndjson"
    assert cat.exists() and cat.read_text().strip()
```

- [ ] **Step 2: Run, verify fail**

```bash
pytest tests/test_orchestrator.py -v
```

Expected: ImportError.

- [ ] **Step 3: Implement orchestrator**

```python
# src/youtube_extractor/pipeline/orchestrator.py
from __future__ import annotations
import time
from dataclasses import dataclass
from pathlib import Path
from slugify import slugify
from youtube_extractor.pipeline.url import extract_video_id
from youtube_extractor.pipeline.metadata import fetch_metadata
from youtube_extractor.pipeline.transcript import fetch_transcript
from youtube_extractor.pipeline.distill import distill
from youtube_extractor.pipeline.render_md import render_markdown
from youtube_extractor.pipeline.render_pdf import render_pdfs
from youtube_extractor.store.catalog import append_entry, find_by_video_id


@dataclass
class PipelineResult:
    slug: str
    md_path: Path
    pdf_full_path: Path
    pdf_lazy_path: Path


def _make_slug(meta) -> str:
    date_part = meta.published or time.strftime("%Y-%m-%d")
    title_part = slugify(meta.title or meta.video_id, max_length=40)
    return f"{date_part}-{meta.video_id}-{title_part}"[:80]


async def run_pipeline(*, url: str, vault_dir: Path, output_dir: Path) -> PipelineResult:
    video_id = extract_video_id(url)
    catalog_path = output_dir / "catalog.ndjson"

    # Idempotency — skip if already extracted
    existing = find_by_video_id(catalog_path, video_id)
    if existing:
        return PipelineResult(
            slug=existing["slug"],
            md_path=Path(existing["md_path"]),
            pdf_full_path=Path(existing["pdf_full_path"]),
            pdf_lazy_path=Path(existing["pdf_lazy_path"]),
        )

    meta = fetch_metadata(video_id)
    transcript = fetch_transcript(video_id)
    distillation = await distill(meta, transcript)

    slug = _make_slug(meta)
    extracted_date = time.strftime("%Y-%m-%d")
    pdf_full_path, pdf_lazy_path = render_pdfs(
        meta=meta, distill=distillation, slug=slug,
        output_dir=output_dir, extracted_date=extracted_date,
    )
    md_path = render_markdown(
        meta=meta, distill=distillation, slug=slug, vault_dir=vault_dir,
        pdf_full_path=str(pdf_full_path), pdf_lazy_path=str(pdf_lazy_path),
        extracted_date=extracted_date,
    )

    append_entry(catalog_path, {
        "slug": slug,
        "video_id": meta.video_id,
        "title": meta.title,
        "channel": meta.channel,
        "url": f"https://youtube.com/watch?v={meta.video_id}",
        "duration": meta.duration_s,
        "extracted_at": time.time(),
        "md_path": str(md_path),
        "pdf_full_path": str(pdf_full_path),
        "pdf_lazy_path": str(pdf_lazy_path),
        "tags": ["youtube"] + distillation.full.topics[:5],
        "topics": distillation.full.topics,
        "people": distillation.full.people,
    })

    return PipelineResult(slug=slug, md_path=md_path, pdf_full_path=pdf_full_path, pdf_lazy_path=pdf_lazy_path)
```

- [ ] **Step 4: Run, verify pass**

```bash
pytest tests/test_orchestrator.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/youtube_extractor/pipeline/orchestrator.py tests/test_orchestrator.py
git commit -m "feat(pipeline): orchestrator that runs all 6 stages + catalog write + idempotency"
```

---

### Task 17: api/jobs.py — POST /jobs, GET /jobs/{id}, retry

**Repo:** youtube-extractor
**Depends on:** Task 16, Task 15
**Files:**
- Create: `~/Youtube-extractor/src/youtube_extractor/api/__init__.py` (empty)
- Create: `~/Youtube-extractor/src/youtube_extractor/api/jobs.py`
- Test: `~/Youtube-extractor/tests/test_api_jobs.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_api_jobs.py
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient
from youtube_extractor.main import create_app
from youtube_extractor.pipeline.orchestrator import PipelineResult
from pathlib import Path


def _ok_result(tmp_path):
    return PipelineResult(
        slug="2024-01-15-abc-x",
        md_path=tmp_path / "x.md",
        pdf_full_path=tmp_path / "x-full.pdf",
        pdf_lazy_path=tmp_path / "x-lazy.pdf",
    )


def test_post_job_creates_and_completes(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "out"))
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path / "vault"))
    app = create_app()
    with patch(
        "youtube_extractor.api.jobs.run_pipeline",
        new=AsyncMock(return_value=_ok_result(tmp_path)),
    ):
        client = TestClient(app)
        r = client.post("/jobs", json={"url": "https://youtu.be/abc"})
        assert r.status_code == 200
        body = r.json()
        assert "job_id" in body

        job_id = body["job_id"]
        # Poll until done
        for _ in range(20):
            g = client.get(f"/jobs/{job_id}").json()
            if g["status"] in ("done", "failed"):
                break
        assert g["status"] == "done"
        assert g["slug"] == "2024-01-15-abc-x"


def test_post_job_invalid_url():
    app = create_app()
    client = TestClient(app)
    r = client.post("/jobs", json={"url": "not a url"})
    assert r.status_code == 400
    assert r.json()["error_code"] == "INVALID_URL"
```

- [ ] **Step 2: Run, verify fail**

```bash
pytest tests/test_api_jobs.py -v
```

Expected: ImportError on `create_app`.

- [ ] **Step 3: Implement jobs router**

```python
# src/youtube_extractor/api/jobs.py
from __future__ import annotations
import asyncio
import time
import uuid
from pathlib import Path
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from youtube_extractor.config import settings
from youtube_extractor.models import JobRecord, JobStatus, JobStage
from youtube_extractor.pipeline.url import extract_video_id, InvalidYouTubeUrl
from youtube_extractor.pipeline.orchestrator import run_pipeline
from youtube_extractor.pipeline.metadata import MetadataError
from youtube_extractor.pipeline.transcript import NoTranscriptError
from youtube_extractor.pipeline.distill import DistillError
from youtube_extractor.store.jobs import JobStore


router = APIRouter()
_jobs = JobStore(settings.output_dir / "jobs.ndjson")
_semaphore = asyncio.Semaphore(settings.max_concurrent_jobs)


class JobCreateBody(BaseModel):
    url: str


@router.post("/jobs")
async def create_job(body: JobCreateBody, bg: BackgroundTasks) -> dict:
    try:
        extract_video_id(body.url)
    except InvalidYouTubeUrl as e:
        raise HTTPException(status_code=400, detail={"error": "invalid url", "error_code": "INVALID_URL", "error_message": str(e)})

    job_id = "job_" + uuid.uuid4().hex[:12]
    rec = JobRecord(id=job_id, url=body.url, status=JobStatus.queued, created_at=time.time(), updated_at=time.time())
    _jobs.put(rec)
    bg.add_task(_run, job_id, body.url)
    return {"job_id": job_id, "status": rec.status.value}


@router.get("/jobs/{job_id}")
async def get_job(job_id: str) -> dict:
    rec = _jobs.get(job_id)
    if not rec:
        raise HTTPException(status_code=404, detail="job not found")
    out = rec.model_dump(mode="json")
    if rec.status == JobStatus.failed and rec.retryable:
        out["retry_url"] = f"/jobs/{job_id}/retry"
    return out


@router.post("/jobs/{job_id}/retry")
async def retry_job(job_id: str, bg: BackgroundTasks) -> dict:
    rec = _jobs.get(job_id)
    if not rec or not rec.retryable:
        raise HTTPException(status_code=400, detail="not retryable")
    rec.status = JobStatus.queued
    rec.error_code = None
    rec.error_message = None
    rec.updated_at = time.time()
    _jobs.put(rec)
    bg.add_task(_run, job_id, rec.url)
    return {"job_id": job_id, "status": rec.status.value}


async def _run(job_id: str, url: str) -> None:
    async with _semaphore:
        rec = _jobs.get(job_id)
        if not rec:
            return
        rec.status = JobStatus.running
        rec.updated_at = time.time()
        _jobs.put(rec)

        try:
            result = await run_pipeline(
                url=url,
                vault_dir=settings.obsidian_vault_path,
                output_dir=settings.output_dir,
            )
            rec.status = JobStatus.done
            rec.slug = result.slug
            rec.updated_at = time.time()
            _jobs.put(rec)
        except InvalidYouTubeUrl as e:
            _fail(rec, JobStage.metadata, "INVALID_URL", str(e), retryable=False)
        except MetadataError as e:
            _fail(rec, JobStage.metadata, "VIDEO_UNAVAILABLE", str(e), retryable=True)
        except NoTranscriptError as e:
            _fail(rec, JobStage.transcript, "NO_TRANSCRIPT", str(e), retryable=False)
        except DistillError as e:
            _fail(rec, JobStage.distill, "HERMES_OFFLINE", str(e), retryable=True)
        except Exception as e:
            _fail(rec, None, "UNKNOWN", str(e), retryable=True)


def _fail(rec: JobRecord, stage: JobStage | None, code: str, msg: str, retryable: bool) -> None:
    rec.status = JobStatus.failed
    rec.stage = stage
    rec.error_code = code
    rec.error_message = msg
    rec.retryable = retryable
    rec.updated_at = time.time()
    _jobs.put(rec)
```

- [ ] **Step 4: Run, verify pass (test will also need Task 19's `main.create_app`)**

After Task 19 lands:
```bash
pytest tests/test_api_jobs.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/youtube_extractor/api/__init__.py src/youtube_extractor/api/jobs.py tests/test_api_jobs.py
git commit -m "feat(api): add jobs router with create/get/retry + bounded concurrency"
```

---

### Task 18: api/archive.py + api/files.py

**Repo:** youtube-extractor
**Depends on:** Task 15
**Files:**
- Create: `~/Youtube-extractor/src/youtube_extractor/api/archive.py`
- Create: `~/Youtube-extractor/src/youtube_extractor/api/files.py`
- Test: `~/Youtube-extractor/tests/test_api_archive.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_api_archive.py
from fastapi.testclient import TestClient
from youtube_extractor.main import create_app
from youtube_extractor.store.catalog import append_entry


def test_archive_list_and_search(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path / "vault"))
    cat = tmp_path / "catalog.ndjson"
    append_entry(cat, {
        "slug": "s1", "video_id": "v1", "title": "AI Talk", "channel": "C",
        "url": "https://y/watch?v=v1", "duration": 100, "extracted_at": 1.0,
        "md_path": "/x.md", "pdf_full_path": "/f.pdf", "pdf_lazy_path": "/l.pdf",
        "tags": ["youtube", "ai"], "topics": ["ai"], "people": [],
    })
    app = create_app()
    client = TestClient(app)

    r = client.get("/archive")
    assert r.status_code == 200
    assert len(r.json()) == 1

    r = client.get("/archive?q=AI")
    assert r.status_code == 200
    assert len(r.json()) == 1

    r = client.get("/archive?q=nope")
    assert r.json() == []


def test_files_pdf_serve(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path / "vault"))
    pdf = tmp_path / "s1-full.pdf"
    pdf.write_bytes(b"%PDF-1.4 minimal")
    app = create_app()
    client = TestClient(app)
    r = client.get("/pdfs/s1/full")
    assert r.status_code == 200
    assert r.content.startswith(b"%PDF-")


def test_files_md_serve(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    vault = tmp_path / "vault"
    vault.mkdir()
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(vault))
    (vault / "s1.md").write_text("# Hi", encoding="utf-8")
    app = create_app()
    client = TestClient(app)
    r = client.get("/files/s1/md")
    assert r.status_code == 200
    assert "# Hi" in r.text


def test_files_404(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path))
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path / "vault"))
    app = create_app()
    client = TestClient(app)
    assert client.get("/pdfs/missing/full").status_code == 404
    assert client.get("/files/missing/md").status_code == 404
```

- [ ] **Step 2: Implement archive.py**

```python
# src/youtube_extractor/api/archive.py
from fastapi import APIRouter
from youtube_extractor.config import settings
from youtube_extractor.store.search import search_entries

router = APIRouter()


@router.get("/archive")
async def archive(q: str = "") -> list[dict]:
    catalog = settings.output_dir / "catalog.ndjson"
    return search_entries(catalog, q)
```

- [ ] **Step 3: Implement files.py**

```python
# src/youtube_extractor/api/files.py
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from youtube_extractor.config import settings

router = APIRouter()


@router.get("/pdfs/{slug}/{kind}")
async def get_pdf(slug: str, kind: str) -> FileResponse:
    if kind not in ("full", "lazy"):
        raise HTTPException(status_code=400, detail="kind must be full or lazy")
    p = settings.output_dir / f"{slug}-{kind}.pdf"
    if not p.exists():
        raise HTTPException(status_code=404, detail="pdf not found")
    return FileResponse(p, media_type="application/pdf", filename=p.name)


@router.get("/files/{slug}/md", response_class=PlainTextResponse)
async def get_md(slug: str) -> str:
    p = settings.obsidian_vault_path / f"{slug}.md"
    if not p.exists():
        raise HTTPException(status_code=404, detail="md not found")
    return p.read_text(encoding="utf-8")
```

- [ ] **Step 4: Commit (tests run after Task 19's `main.create_app` lands)**

```bash
git add src/youtube_extractor/api/archive.py src/youtube_extractor/api/files.py tests/test_api_archive.py
git commit -m "feat(api): add archive list/search + file serving for PDFs and MD"
```

---

### Task 19: main.py — FastAPI app factory + uvicorn entrypoint

**Repo:** youtube-extractor
**Depends on:** Tasks 17, 18
**Files:**
- Create: `~/Youtube-extractor/src/youtube_extractor/main.py`
- Test: `~/Youtube-extractor/tests/test_main_health.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_main_health.py
from fastapi.testclient import TestClient
from youtube_extractor.main import create_app


def test_health():
    app = create_app()
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body
```

- [ ] **Step 2: Implement main.py**

```python
# src/youtube_extractor/main.py
from __future__ import annotations
import logging
import httpx
from fastapi import FastAPI
from youtube_extractor import __version__
from youtube_extractor.config import settings
from youtube_extractor.api.jobs import router as jobs_router
from youtube_extractor.api.archive import router as archive_router
from youtube_extractor.api.files import router as files_router


def create_app() -> FastAPI:
    logging.basicConfig(level=settings.log_level)
    app = FastAPI(title="YouTube Extractor", version=__version__)
    app.include_router(jobs_router)
    app.include_router(archive_router)
    app.include_router(files_router)

    @app.get("/health")
    async def health() -> dict:
        # Best-effort: probe LLM endpoint, don't block on it
        hermes_ok = False
        try:
            async with httpx.AsyncClient(timeout=2) as c:
                r = await c.get(f"{settings.llm_base_url.rstrip('/')}/v1/models")
                hermes_ok = r.status_code == 200
        except Exception:
            pass
        return {"status": "ok", "version": __version__, "hermes_reachable": hermes_ok}

    return app


def serve() -> None:
    """Entrypoint used by `youtube-extractor serve` and the launchd unit."""
    import uvicorn
    uvicorn.run(
        "youtube_extractor.main:create_app",
        factory=True,
        host=settings.host,
        port=settings.port,
        log_level=settings.log_level.lower(),
    )
```

- [ ] **Step 3: Run all API tests**

```bash
pytest tests/test_main_health.py tests/test_api_jobs.py tests/test_api_archive.py -v
```

Expected: all PASS.

- [ ] **Step 4: Smoke test — start the service**

```bash
youtube-extractor serve &
sleep 2
curl -s http://127.0.0.1:18765/health | tee /dev/stderr
kill %1
```

Expected: `{"status": "ok", ...}`.

- [ ] **Step 5: Commit**

```bash
git add src/youtube_extractor/main.py tests/test_main_health.py
git commit -m "feat(api): wire FastAPI app factory + /health + uvicorn serve entrypoint"
```

---

### Task 20: cli.py — Click CLI for standalone usage

**Repo:** youtube-extractor
**Depends on:** Task 16, Task 19
**Files:**
- Create: `~/Youtube-extractor/src/youtube_extractor/cli.py`
- Test: `~/Youtube-extractor/tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli.py
from unittest.mock import patch, AsyncMock
from click.testing import CliRunner
from pathlib import Path
from youtube_extractor.cli import cli
from youtube_extractor.pipeline.orchestrator import PipelineResult


def test_cli_extract(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "out"))
    monkeypatch.setenv("OBSIDIAN_VAULT_PATH", str(tmp_path / "vault"))
    fake = AsyncMock(return_value=PipelineResult(
        slug="s", md_path=tmp_path/"s.md",
        pdf_full_path=tmp_path/"s-full.pdf", pdf_lazy_path=tmp_path/"s-lazy.pdf",
    ))
    with patch("youtube_extractor.cli.run_pipeline", new=fake):
        runner = CliRunner()
        result = runner.invoke(cli, ["extract", "https://youtu.be/abc"])
    assert result.exit_code == 0
    assert "slug: s" in result.output


def test_cli_serve_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["serve", "--help"])
    assert result.exit_code == 0
    assert "host" in result.output.lower()
```

- [ ] **Step 2: Implement cli.py**

```python
# src/youtube_extractor/cli.py
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
    result = asyncio.run(run_pipeline(
        url=url,
        vault_dir=settings.obsidian_vault_path,
        output_dir=settings.output_dir,
    ))
    click.echo(f"slug: {result.slug}")
    click.echo(f"md:   {result.md_path}")
    click.echo(f"full: {result.pdf_full_path}")
    click.echo(f"lazy: {result.pdf_lazy_path}")


@cli.command("serve")
@click.option("--host", default=None, help="override HOST env")
@click.option("--port", default=None, type=int, help="override PORT env")
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
```

- [ ] **Step 3: Run tests**

```bash
pytest tests/test_cli.py -v
youtube-extractor --help
```

Expected: tests PASS, CLI shows `extract` and `serve` subcommands.

- [ ] **Step 4: Commit**

```bash
git add src/youtube_extractor/cli.py tests/test_cli.py
git commit -m "feat(cli): add Click CLI with extract + serve subcommands"
```

---

## Wave 3 — Deployment + Mission Control (parallel where possible)

> **Dispatch hint:** Tasks 21 (launchd) and 22 (real-video smoke test) are independent of MC integration tasks 23-29. Run them in parallel.
> - **Agent G:** Tasks 21 + 22 (deployment of the standalone service)
> - **Agent H:** Tasks 23-26 (MC API proxy routes)
> - **Agent I:** Tasks 27-29 (MC tab UI)
>
> Tasks 27-29 build on 23-26 — same agent can do both, or split if the agent is fast.

### Task 21: launchd plist + install instructions

**Repo:** youtube-extractor
**Depends on:** Task 19
**Files:**
- Create: `~/Youtube-extractor/deploy/com.deedee.youtube-extractor.plist`
- Modify: `~/Youtube-extractor/README.md` (add "Run as a service" install instructions)

- [ ] **Step 1: Write the plist**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.deedee.youtube-extractor</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/user/Youtube-extractor/.venv/bin/youtube-extractor</string>
    <string>serve</string>
  </array>
  <key>WorkingDirectory</key>
  <string>/Users/user/Youtube-extractor</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/Users/user/Youtube-extractor/.venv/bin:/usr/local/bin:/usr/bin:/bin</string>
  </dict>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>/Users/user/.openclaw/logs/youtube-extractor.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/user/.openclaw/logs/youtube-extractor.err</string>
</dict>
</plist>
```

- [ ] **Step 2: Append "Run as a service" section to README**

Append after the existing "Run as a service" stub:

```markdown
### Auto-start on macOS (launchd)

```bash
mkdir -p ~/.openclaw/logs
cp deploy/com.deedee.youtube-extractor.plist ~/Library/LaunchAgents/
launchctl load -w ~/Library/LaunchAgents/com.deedee.youtube-extractor.plist
launchctl list | grep youtube-extractor   # status 0 = running
```

To stop / restart:

```bash
launchctl stop com.deedee.youtube-extractor
launchctl start com.deedee.youtube-extractor
launchctl unload ~/Library/LaunchAgents/com.deedee.youtube-extractor.plist
```
```

- [ ] **Step 3: Install on the Mac**

```bash
mkdir -p ~/.openclaw/logs
cp ~/Youtube-extractor/deploy/com.deedee.youtube-extractor.plist ~/Library/LaunchAgents/
launchctl load -w ~/Library/LaunchAgents/com.deedee.youtube-extractor.plist
sleep 2
launchctl list | grep youtube-extractor
curl -s http://127.0.0.1:18765/health
```

Expected: status `0`, `/health` returns 200 JSON.

- [ ] **Step 4: Commit**

```bash
git add deploy/ README.md
git commit -m "feat(deploy): add launchd plist + install/uninstall docs"
```

---

### Task 22: Real-video smoke test (CLI end-to-end on a real YouTube URL)

**Repo:** youtube-extractor
**Depends on:** Task 20

- [ ] **Step 1: Pick a short, stable test video with official captions**

Use Karpathy's "Intro to Large Language Models" (~1h, has captions) or a 3Blue1Brown short. Avoid music videos (often blocked) and fresh uploads.

- [ ] **Step 2: Run end-to-end via CLI**

```bash
cd ~/Youtube-extractor
source .venv/bin/activate
time youtube-extractor extract "https://www.youtube.com/watch?v=zjkBMFhNj_g"
```

Expected output:
```
slug: 2023-11-22-zjkBMFhNj_g-intro-to-large-language-models
md:   /Users/user/.claude/obsidian-mind/youtube/2023-11-22-zjkBMFhNj_g-intro-to-large-language-models.md
full: /Users/user/Youtube-extractor/output/2023-11-22-zjkBMFhNj_g-intro-to-large-language-models-full.pdf
lazy: /Users/user/Youtube-extractor/output/2023-11-22-zjkBMFhNj_g-intro-to-large-language-models-lazy.pdf
```

- [ ] **Step 3: Manual verification**

Open the `.md` in Obsidian → frontmatter renders, callouts render, chapter sections look right.
Open both PDFs → FULL is multi-page with chapters, LAZY is 1-2 pages with bullets.

- [ ] **Step 4: Re-run to verify idempotency**

```bash
youtube-extractor extract "https://www.youtube.com/watch?v=zjkBMFhNj_g"
```

Expected: same paths, instant return (idempotent — catalog hit, no LLM call).

- [ ] **Step 5: Commit nothing — this is a verification task. Add a manual-test-log entry to docs.**

```bash
echo "- 2026-05-03: smoke-tested with zjkBMFhNj_g — md + 2 PDFs generated cleanly, ~80s end-to-end" >> docs/manual-test-log.md
git add docs/manual-test-log.md
git commit -m "docs: log first real-video smoke test"
```

---

## Wave 4 — Mission Control integration

### Task 23: MC `lib/youtube-extractor.ts` — typed HTTP client

**Repo:** OpenDeeDee/mission-control
**Depends on:** Task 19 running locally
**Files:**
- Create: `~/OpenDeeDee/mission-control/src/lib/youtube-extractor.ts`

- [ ] **Step 1: Write the client**

```typescript
// src/lib/youtube-extractor.ts
/**
 * Typed HTTP client for the YouTube Extractor service (default 127.0.0.1:18765).
 * Mirrors the pattern used by lib/dgx.ts / lib/uncensored.ts.
 */
import { NextResponse } from 'next/server'

export const YT_EXTRACTOR_URL = process.env.YT_EXTRACTOR_URL || 'http://127.0.0.1:18765'
export const YT_EXTRACTOR_TIMEOUT_MS = 6_000

export type YtErrorCode =
  | 'EXTRACTOR_OFFLINE'
  | 'EXTRACTOR_TIMEOUT'
  | 'EXTRACTOR_ERROR'

export class YtProxyError extends Error {
  code: YtErrorCode
  status: number
  constructor(code: YtErrorCode, message: string, status = 502) {
    super(message)
    this.code = code
    this.status = status
  }
}

export async function ytFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const ac = new AbortController()
  const t = setTimeout(() => ac.abort(), YT_EXTRACTOR_TIMEOUT_MS)
  try {
    return await fetch(`${YT_EXTRACTOR_URL}${path}`, {
      ...init,
      signal: ac.signal,
      cache: 'no-store',
    })
  } catch (e: unknown) {
    if ((e as Error).name === 'AbortError') {
      throw new YtProxyError('EXTRACTOR_TIMEOUT', `timeout to ${YT_EXTRACTOR_URL}`, 504)
    }
    throw new YtProxyError('EXTRACTOR_OFFLINE', `cannot reach ${YT_EXTRACTOR_URL}: ${(e as Error).message}`, 502)
  } finally {
    clearTimeout(t)
  }
}

export function ytErrorResponse(err: unknown): NextResponse {
  if (err instanceof YtProxyError) {
    return NextResponse.json({ error: err.message, code: err.code }, { status: err.status })
  }
  const msg = err instanceof Error ? err.message : 'unknown error'
  return NextResponse.json({ error: msg, code: 'EXTRACTOR_ERROR' }, { status: 502 })
}
```

- [ ] **Step 2: Commit**

```bash
cd ~/OpenDeeDee/mission-control
git add src/lib/youtube-extractor.ts
git commit -m "feat(youtube): add typed HTTP client for the extractor service"
```

---

### Task 24: MC `/api/youtube/jobs` proxy

**Repo:** OpenDeeDee/mission-control
**Depends on:** Task 23
**Files:**
- Create: `~/OpenDeeDee/mission-control/src/app/api/youtube/jobs/route.ts`
- Create: `~/OpenDeeDee/mission-control/src/app/api/youtube/jobs/[id]/route.ts`
- Create: `~/OpenDeeDee/mission-control/src/app/api/youtube/jobs/[id]/retry/route.ts`

- [ ] **Step 1: Write POST + GET** (`jobs/route.ts`)

```typescript
// src/app/api/youtube/jobs/route.ts
import { NextResponse } from 'next/server'
import { ytFetch, ytErrorResponse } from '@/lib/youtube-extractor'

export const dynamic = 'force-dynamic'

export async function POST(req: Request) {
  try {
    const body = await req.json().catch(() => ({}))
    const r = await ytFetch('/jobs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    const data = await r.json().catch(() => ({}))
    return NextResponse.json(data, { status: r.status })
  } catch (err) {
    return ytErrorResponse(err)
  }
}
```

- [ ] **Step 2: Write GET single job** (`jobs/[id]/route.ts`)

```typescript
// src/app/api/youtube/jobs/[id]/route.ts
import { NextResponse } from 'next/server'
import { ytFetch, ytErrorResponse } from '@/lib/youtube-extractor'

export const dynamic = 'force-dynamic'

export async function GET(_req: Request, { params }: { params: { id: string } }) {
  try {
    const r = await ytFetch(`/jobs/${encodeURIComponent(params.id)}`)
    const data = await r.json().catch(() => ({}))
    return NextResponse.json(data, { status: r.status })
  } catch (err) {
    return ytErrorResponse(err)
  }
}
```

- [ ] **Step 3: Write retry** (`jobs/[id]/retry/route.ts`)

```typescript
// src/app/api/youtube/jobs/[id]/retry/route.ts
import { NextResponse } from 'next/server'
import { ytFetch, ytErrorResponse } from '@/lib/youtube-extractor'

export const dynamic = 'force-dynamic'

export async function POST(_req: Request, { params }: { params: { id: string } }) {
  try {
    const r = await ytFetch(`/jobs/${encodeURIComponent(params.id)}/retry`, { method: 'POST' })
    const data = await r.json().catch(() => ({}))
    return NextResponse.json(data, { status: r.status })
  } catch (err) {
    return ytErrorResponse(err)
  }
}
```

- [ ] **Step 4: Commit**

```bash
git add src/app/api/youtube/jobs
git commit -m "feat(youtube): proxy routes for POST /jobs, GET /jobs/[id], retry"
```

---

### Task 25: MC `/api/youtube/archive` proxy

**Repo:** OpenDeeDee/mission-control
**Depends on:** Task 23
**Files:**
- Create: `~/OpenDeeDee/mission-control/src/app/api/youtube/archive/route.ts`

- [ ] **Step 1: Write the proxy**

```typescript
// src/app/api/youtube/archive/route.ts
import { NextRequest, NextResponse } from 'next/server'
import { ytFetch, ytErrorResponse } from '@/lib/youtube-extractor'

export const dynamic = 'force-dynamic'

export async function GET(req: NextRequest) {
  try {
    const q = req.nextUrl.searchParams.get('q') ?? ''
    const r = await ytFetch(`/archive${q ? `?q=${encodeURIComponent(q)}` : ''}`)
    const data = await r.json().catch(() => [])
    return NextResponse.json(data, { status: r.status })
  } catch (err) {
    return ytErrorResponse(err)
  }
}
```

- [ ] **Step 2: Commit**

```bash
git add src/app/api/youtube/archive
git commit -m "feat(youtube): proxy archive list/search"
```

---

### Task 26: MC `/api/youtube/files/[slug]/[kind]` proxy

**Repo:** OpenDeeDee/mission-control
**Depends on:** Task 23
**Files:**
- Create: `~/OpenDeeDee/mission-control/src/app/api/youtube/files/[slug]/[kind]/route.ts`

- [ ] **Step 1: Write the proxy (streams bytes)**

```typescript
// src/app/api/youtube/files/[slug]/[kind]/route.ts
import { NextResponse } from 'next/server'
import { ytFetch, ytErrorResponse } from '@/lib/youtube-extractor'

export const dynamic = 'force-dynamic'

export async function GET(_req: Request, { params }: { params: { slug: string; kind: string } }) {
  const { slug, kind } = params
  try {
    let upstream: string
    if (kind === 'full' || kind === 'lazy') {
      upstream = `/pdfs/${encodeURIComponent(slug)}/${kind}`
    } else if (kind === 'md') {
      upstream = `/files/${encodeURIComponent(slug)}/md`
    } else {
      return NextResponse.json({ error: 'kind must be full|lazy|md' }, { status: 400 })
    }
    const r = await ytFetch(upstream)
    if (r.status !== 200) {
      const text = await r.text().catch(() => '')
      return NextResponse.json({ error: text || `upstream ${r.status}` }, { status: r.status })
    }
    const headers = new Headers()
    const ct = r.headers.get('content-type')
    if (ct) headers.set('content-type', ct)
    if (kind !== 'md') headers.set('content-disposition', `inline; filename="${slug}-${kind}.pdf"`)
    return new Response(r.body, { status: 200, headers })
  } catch (err) {
    return ytErrorResponse(err)
  }
}
```

- [ ] **Step 2: Commit**

```bash
git add src/app/api/youtube/files
git commit -m "feat(youtube): proxy PDF and MD file delivery"
```

---

### Task 27: MC `/youtube` page scaffold

**Repo:** OpenDeeDee/mission-control
**Depends on:** Tasks 24-26
**Files:**
- Create: `~/OpenDeeDee/mission-control/src/app/youtube/page.tsx`
- Create: `~/OpenDeeDee/mission-control/src/app/youtube/types.ts`

- [ ] **Step 1: Write types**

```typescript
// src/app/youtube/types.ts
export interface CatalogRow {
  slug: string
  video_id: string
  title: string
  channel: string
  url: string
  duration: number
  extracted_at: number
  md_path: string
  pdf_full_path: string
  pdf_lazy_path: string
  tags: string[]
  topics: string[]
  people: string[]
}

export interface JobView {
  job_id?: string
  id?: string
  url?: string
  slug?: string | null
  status: 'queued' | 'running' | 'done' | 'failed' | 'partial_success'
  stage?: string | null
  error_code?: string | null
  error_message?: string | null
  retryable?: boolean
}
```

- [ ] **Step 2: Write the page (composition only — components in next tasks)**

```typescript
// src/app/youtube/page.tsx
'use client'
import { useEffect, useState } from 'react'
import { PasteForm } from './_components/PasteForm'
import { ActiveJobs } from './_components/ActiveJobs'
import { ArchiveList } from './_components/ArchiveList'
import { SearchBox } from './_components/SearchBox'
import type { CatalogRow, JobView } from './types'

export default function YouTubePage() {
  const [archive, setArchive] = useState<CatalogRow[]>([])
  const [activeJobs, setActiveJobs] = useState<JobView[]>([])
  const [query, setQuery] = useState('')

  async function refreshArchive(q = '') {
    const url = q ? `/api/youtube/archive?q=${encodeURIComponent(q)}` : '/api/youtube/archive'
    const r = await fetch(url, { cache: 'no-store' })
    if (r.ok) setArchive(await r.json())
  }

  useEffect(() => { refreshArchive() }, [])

  // Poll active jobs
  useEffect(() => {
    if (activeJobs.length === 0) return
    const id = setInterval(async () => {
      const updated: JobView[] = []
      let anyDone = false
      for (const j of activeJobs) {
        const jid = j.job_id ?? j.id
        if (!jid) continue
        const r = await fetch(`/api/youtube/jobs/${jid}`, { cache: 'no-store' })
        if (r.ok) {
          const view = await r.json() as JobView
          if (view.status === 'done' || view.status === 'failed') anyDone = true
          updated.push(view)
        } else {
          updated.push(j)
        }
      }
      setActiveJobs(updated)
      if (anyDone) refreshArchive(query)
    }, 2000)
    return () => clearInterval(id)
  }, [activeJobs.length, query])

  async function onSubmit(url: string) {
    const r = await fetch('/api/youtube/jobs', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    })
    if (r.ok) {
      const j = await r.json() as JobView
      setActiveJobs(prev => [...prev, j])
    }
  }

  return (
    <div style={{ padding: 20 }}>
      <header style={{ marginBottom: 14 }}>
        <h1 style={{ margin: 0, fontSize: 18, fontWeight: 700 }}>YouTube Extractor</h1>
        <p style={{ margin: '4px 0 0', fontSize: 12, color: '#a0a0c8' }}>
          Paste a video link — get .md in Obsidian + 2 PDFs (FULL + LAZY)
        </p>
      </header>

      <PasteForm onSubmit={onSubmit} />
      <ActiveJobs jobs={activeJobs} />
      <SearchBox value={query} onChange={(q) => { setQuery(q); refreshArchive(q) }} count={archive.length} />
      <ArchiveList rows={archive} />
    </div>
  )
}
```

- [ ] **Step 3: Commit (compiles after Task 28's components land)**

```bash
git add src/app/youtube/page.tsx src/app/youtube/types.ts
git commit -m "feat(youtube): page scaffold + types"
```

---

### Task 28: MC tab components — PasteForm, ActiveJobs, SearchBox, ArchiveList

**Repo:** OpenDeeDee/mission-control
**Depends on:** Task 27
**Files:**
- Create: `~/OpenDeeDee/mission-control/src/app/youtube/_components/PasteForm.tsx`
- Create: `~/OpenDeeDee/mission-control/src/app/youtube/_components/ActiveJobs.tsx`
- Create: `~/OpenDeeDee/mission-control/src/app/youtube/_components/SearchBox.tsx`
- Create: `~/OpenDeeDee/mission-control/src/app/youtube/_components/ArchiveList.tsx`

- [ ] **Step 1: PasteForm.tsx**

```typescript
'use client'
import { useState } from 'react'

export function PasteForm({ onSubmit }: { onSubmit: (url: string) => Promise<void> }) {
  const [url, setUrl] = useState('')
  const [busy, setBusy] = useState(false)
  return (
    <form
      style={{ background: '#08090e', border: '1px solid #1a1a30', borderRadius: 8, padding: 14, marginBottom: 18, display: 'flex', gap: 10 }}
      onSubmit={async (e) => {
        e.preventDefault()
        if (!url || busy) return
        setBusy(true)
        try { await onSubmit(url); setUrl('') } finally { setBusy(false) }
      }}
    >
      <input
        style={{ flex: 1, background: '#0d0d1a', border: '1px solid #1a1a30', color: '#e0e0f8', padding: '10px 12px', borderRadius: 6 }}
        placeholder="https://youtube.com/watch?v=..."
        value={url}
        onChange={(e) => setUrl(e.target.value)}
        disabled={busy}
      />
      <button
        type="submit"
        disabled={busy}
        style={{ background: '#6366f1', color: 'white', border: 'none', padding: '10px 20px', borderRadius: 6, fontWeight: 600, cursor: busy ? 'wait' : 'pointer' }}
      >
        {busy ? '...' : 'Extract'}
      </button>
    </form>
  )
}
```

- [ ] **Step 2: ActiveJobs.tsx**

```typescript
'use client'
import type { JobView } from '../types'

export function ActiveJobs({ jobs }: { jobs: JobView[] }) {
  if (jobs.length === 0) return null
  return (
    <div style={{ marginBottom: 18 }}>
      <div style={{ fontSize: 11, letterSpacing: '0.1em', textTransform: 'uppercase', color: '#6b6b98', marginBottom: 8 }}>
        Active jobs
      </div>
      <div style={{ background: '#08090e', border: '1px solid #1a1a30', borderRadius: 8 }}>
        {jobs.map((j) => (
          <Row key={j.job_id ?? j.id} j={j} />
        ))}
      </div>
    </div>
  )
}

function Row({ j }: { j: JobView }) {
  const id = j.job_id ?? j.id ?? ''
  const dot = j.status === 'done' ? '✓' : j.status === 'failed' ? '✗' : '●'
  const color = j.status === 'done' ? '#22c55e' : j.status === 'failed' ? '#ef4444' : '#818cf8'
  return (
    <div style={{ padding: '10px 14px', borderBottom: '1px solid #1a1a30', display: 'flex', alignItems: 'center', gap: 12, fontSize: 12 }}>
      <span style={{ color, fontWeight: 700 }}>{dot}</span>
      <span style={{ flex: 1, color: '#e0e0f8' }}>{j.url ?? id}</span>
      <span style={{ color: '#6b6b98', fontSize: 11 }}>
        {j.status}
        {j.stage ? ` · ${j.stage}` : ''}
        {j.error_code ? ` · ${j.error_code}` : ''}
      </span>
    </div>
  )
}
```

- [ ] **Step 3: SearchBox.tsx**

```typescript
'use client'
export function SearchBox({ value, onChange, count }: { value: string; onChange: (v: string) => void; count: number }) {
  return (
    <div style={{ marginBottom: 12, display: 'flex', gap: 10, alignItems: 'center' }}>
      <div style={{ fontSize: 11, letterSpacing: '0.1em', textTransform: 'uppercase', color: '#6b6b98' }}>
        Archive · {count} entries
      </div>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        style={{ flex: 1, background: '#0d0d1a', border: '1px solid #1a1a30', color: '#e0e0f8', padding: '6px 10px', borderRadius: 6, fontSize: 12 }}
        placeholder="search title, channel, tag, person…"
      />
    </div>
  )
}
```

- [ ] **Step 4: ArchiveList.tsx**

```typescript
'use client'
import type { CatalogRow } from '../types'

const isMacUA = (typeof navigator !== 'undefined' && /Macintosh/.test(navigator.userAgent))

export function ArchiveList({ rows }: { rows: CatalogRow[] }) {
  if (rows.length === 0) {
    return <div style={{ padding: 20, color: '#6b6b98', fontSize: 12 }}>Nothing in the archive yet — paste a YouTube URL above.</div>
  }
  return (
    <div style={{ background: '#08090e', border: '1px solid #1a1a30', borderRadius: 8 }}>
      {rows.map((r, i) => (
        <RowItem key={r.slug} row={r} last={i === rows.length - 1} />
      ))}
    </div>
  )
}

function RowItem({ row, last }: { row: CatalogRow; last: boolean }) {
  const min = Math.round(row.duration / 60)
  const date = new Date(row.extracted_at * 1000).toISOString().slice(0, 10)
  const obsidianUrl = `obsidian://open?file=${encodeURIComponent(row.slug)}`
  return (
    <div style={{ display: 'flex', gap: 14, padding: '12px 14px', borderBottom: last ? 'none' : '1px solid #1a1a30' }}>
      <div style={{ width: 120, height: 68, background: '#1a1a30', borderRadius: 4, flexShrink: 0 }} />
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: '#e0e0f8', marginBottom: 2 }}>{row.title}</div>
        <div style={{ fontSize: 11, color: '#6b6b98', marginBottom: 6 }}>
          {row.channel} · {min}m · extracted {date}
          {row.topics.length ? ` · tags: ${row.topics.slice(0, 3).join(', ')}` : ''}
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          {isMacUA ? (
            <a href={obsidianUrl} style={btnPrimary}>Open .md in Obsidian</a>
          ) : (
            <a href={`/api/youtube/files/${row.slug}/md`} target="_blank" rel="noreferrer" style={btnPrimary}>View .md</a>
          )}
          <a href={`/api/youtube/files/${row.slug}/full`} target="_blank" rel="noreferrer" style={btnSecondary}>PDF FULL</a>
          <a href={`/api/youtube/files/${row.slug}/lazy`} target="_blank" rel="noreferrer" style={btnSecondary}>PDF LAZY</a>
        </div>
      </div>
    </div>
  )
}

const btnPrimary: React.CSSProperties = { background: '#6366f1', color: 'white', padding: '4px 10px', borderRadius: 4, fontSize: 11, fontWeight: 500, textDecoration: 'none' }
const btnSecondary: React.CSSProperties = { background: 'transparent', border: '1px solid #1a1a30', color: '#a0a0c8', padding: '4px 10px', borderRadius: 4, fontSize: 11, textDecoration: 'none' }
```

- [ ] **Step 5: Commit**

```bash
git add src/app/youtube/_components
git commit -m "feat(youtube): tab components — PasteForm, ActiveJobs, SearchBox, ArchiveList"
```

---

### Task 29: MC sidebar entry

**Repo:** OpenDeeDee/mission-control
**Depends on:** Task 27
**Files:**
- Modify: `~/OpenDeeDee/mission-control/src/components/Sidebar.tsx`

- [ ] **Step 1: Add nav entry to the `tools` group**

```typescript
// In src/components/Sidebar.tsx, add after the recon entry:
{ href: '/youtube',    icon: '🎬', label: 'YouTube',  group: 'tools' },
```

- [ ] **Step 2: Build + restart MC**

```bash
cd ~/OpenDeeDee/mission-control
npm run build
launchctl stop com.deedee.dashboard && launchctl start com.deedee.dashboard
sleep 3
curl -sm 5 -o /dev/null -w "/youtube → %{http_code}\n" http://localhost:3000/youtube
```

Expected: 200.

- [ ] **Step 3: Commit**

```bash
git add src/components/Sidebar.tsx
git commit -m "feat(sidebar): add YouTube tab nav entry under TOOLS"
```

---

## Wave 5 — End-to-end + finalisation

### Task 30: End-to-end smoke test through Mission Control

**Repo:** both (manual verification)
**Depends on:** Tasks 21, 29

- [ ] **Step 1: Confirm both services are healthy**

```bash
curl -s http://127.0.0.1:18765/health | python3 -m json.tool
curl -sm 5 -o /dev/null -w "MC :3000/youtube → %{http_code}\n" http://localhost:3000/youtube
launchctl list | grep -E "youtube-extractor|dashboard"
```

Expected: extractor `status: ok`, MC 200, both launchd statuses `0`.

- [ ] **Step 2: From the browser, paste a fresh YouTube URL into the tab**

Use a video different from Task 22's so it actually exercises the path (e.g. a 3Blue1Brown short).

- Confirm: paste form clears after submit, an `Active jobs` row appears, status progresses `queued → running → done` within ~2 minutes.
- Confirm: archive list refreshes and the new entry shows up.
- Confirm: clicking PDF FULL and PDF LAZY downloads valid PDFs (open in browser, not corrupted).
- Confirm: `Open .md in Obsidian` opens Obsidian on the deep-link click (Mac), or shows the rendered MD inline on a non-Mac browser.

- [ ] **Step 3: Verify on LAN from a second device**

From a second device on the LAN at `http://<your-lan-ip>:3000/youtube` (or your Tailscale URL): confirm the archive renders, the PDF buttons download, and the "View .md" button (non-Mac fallback) shows the markdown.

- [ ] **Step 4: Verify duplicate-URL idempotency**

Paste the same URL again → archive shouldn't grow, no new active job runs end-to-end (extractor short-circuits via catalog hit).

- [ ] **Step 5: Commit a smoke-test log entry**

```bash
cd ~/Youtube-extractor
echo "- 2026-05-03: end-to-end MC tab smoke — paste → done in 90s, PDFs + .md verified, LAN access OK" >> docs/manual-test-log.md
git add docs/manual-test-log.md
git commit -m "docs: log end-to-end MC tab smoke test"
```

---

### Task 31: Update README "How I use it" section + push final state

**Repo:** youtube-extractor
**Depends on:** Task 30
**Files:**
- Modify: `~/Youtube-extractor/README.md`

- [ ] **Step 1: Add a screenshot reference**

Take a screenshot of the MC tab with the archive populated. Save to `docs/screenshots/mc-tab.png`. Reference in README:

```markdown
## How I use it

I run this on a Mac Studio with a tab in Mission Control (private repo) that proxies to it. The LLM lives on a DGX Spark on my LAN, routed through Hermes. End-to-end takes ~90 seconds for a 1-hour video.

![Mission Control YouTube tab](docs/screenshots/mc-tab.png)
```

- [ ] **Step 2: Pre-push security scan**

```bash
cd ~/Youtube-extractor
git diff --cached --name-only
git log --all --pretty=format: --name-only --diff-filter=A | sort -u | grep -iE "\.env$|secret|credential|id_rsa|api.key"
```

Expected: no matches.

- [ ] **Step 3: Push final state to public repo**

```bash
git push origin main
gh repo view psyd3x/youtube-extractor --web
```

Confirm GitHub shows: README rendered with screenshot, latest commit, green CI on main.

- [ ] **Step 4: Commit any post-screenshot README tweaks**

```bash
git add README.md docs/screenshots/
git commit -m "docs: add MC tab screenshot to How I use it"
git push
```

---

## Self-review

**Spec coverage check** — every spec section maps to one or more tasks:

| Spec section | Implementing tasks |
|--------------|---------------------|
| §1 Purpose | covered by every task that produces output (md + PDFs) |
| §2 Architecture | Tasks 1-5 (repo), Task 19 (FastAPI), Tasks 23-26 (MC proxy) |
| §3 Pipeline modules | Tasks 7-15 |
| §4 Distillation contract | Tasks 10, 11 |
| §5 Storage layout | Tasks 6 (Settings paths), 13 (md), 14 (pdf), 15 (catalog), 16 (slug + idempotency) |
| §6 API surface | Tasks 17, 18, 19 (extractor); Tasks 24, 25, 26 (MC proxy) |
| §7 MC tab UX | Tasks 27, 28, 29 |
| §8 Access architecture (LAN/Tailscale) | Task 6 (settings.host=127.0.0.1), Task 26 (file proxy), Task 30 (verification) |
| §9 Error handling | Task 17 (job error mapping), Task 9 (NoTranscriptError), Task 10 (LLMError), Task 8 (MetadataError) |
| §10 Configuration env vars | Task 6 (Settings) |
| §11 Public repo deliverables | Tasks 1-5, 21 (deploy/) |
| §12 Out of scope | not implemented (correct — Whisper/batch deferred) |
| §13 Implementation order | mirrored in this plan's wave ordering |
| §14 Acceptance criteria | Task 22 (CLI smoke), Task 30 (E2E smoke), Task 31 (CI green + repo public) |

**Placeholder scan:** none — every code step has full content. No "TBD", no "implement later", no "similar to Task N".

**Type consistency:**
- `Metadata` fields used same way across tasks 8, 11, 13, 14, 16
- `Distillation` shape matches between models.py (Task 6), distill.py (Task 11), templates (Task 12)
- `JobRecord` / `JobStatus` / `JobStage` referenced consistently in Tasks 6, 15, 17
- `PipelineResult` defined in Task 16, used in Tasks 17, 20

---

## Execution choice

Plan complete and saved to `~/Youtube-extractor/docs/superpowers/plans/2026-05-03-youtube-extractor.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration. Wave 1 tasks (7, 8, 9, 10, 12-14, 15) get dispatched as parallel agents per the dispatch hints; Waves 2-5 sequential.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints for review.

**Which approach?**
