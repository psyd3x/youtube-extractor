---
title: YouTube Extractor — Design Spec
description: Public Python service that turns a YouTube link into a distilled Obsidian .md plus FULL and LAZY PDFs, called via a new Mission Control tab and routed through Hermes to DGX qwen36 by default.
date: 2026-05-03
status: design-approved
type: spec
project: youtube-extractor
tags: [youtube-extractor, design, spec, mission-control, hermes, obsidian]
related:
  - "[[Mission Control]]"
  - "[[Hermes]]"
  - "[[DGX]]"
  - "[[Obsidian Vault]]"
---

# YouTube Extractor — Design Spec

**Status**: design approved, awaiting implementation plan
**Date**: 2026-05-03
**Owner**: Dexter (psyd3x)
**Repo**: `github.com/psyd3x/youtube-extractor` (public, MIT)
**Related**: [[Mission Control]] · [[Hermes]] · [[DGX]] · [[Obsidian Vault]]

---

## 1. Purpose

Paste a YouTube link → get a distilled `.md` in your Obsidian vault + two PDFs (FULL and LAZY) on disk.

**Use case**: knowledge archive. The user watches/skims videos, extracts the substance, makes it searchable in Obsidian, prints PDFs for offline reading. No raw transcript is stored — only the distillation.

**Two PDF modes**, generated for every video:
- **FULL** — comprehensive distillation: chapter-by-chapter breakdown, key points, quotes, references. Length scales with video length. Reading time roughly 10% of video length.
- **LAZY** — short version: hook + 5-10 key points + 1-paragraph summary. ~1-2 pages, readable in 60 seconds.

The Markdown file is the single source of truth (Obsidian-native, wikilinkable). PDFs are derivatives.

---

## 2. Architecture

```
phone (Tailscale)            laptop (LAN)            Mac (local)
       │                          │                        │
       └─────────────┬────────────┴────────────────────────┘
                     ▼
       <your-tailscale-host>.ts.net (Tailscale serve)
                     │
                     ▼
       Mission Control :3000        ← single externally-reachable surface
       (auth-gated, CORS-locked, MC_API_TOKEN required)
                     │
                     ▼  /api/youtube/*   (server-side, same host)
                     │
       YouTube Extractor :18765    ← 127.0.0.1 only, never exposed
       (FastAPI, Python service)
                     │
       ┌─────────────┴──────────────────┐
       ▼                                ▼
   Hermes (LLM router)            Local disk
   :8642 → DGX qwen36 today       (.md to vault, PDFs to repo output)
```

**Three components, three responsibilities:**

| Component | Owns |
|-----------|------|
| Mission Control | UI tab + auth + proxy routes. Knows nothing about YouTube/PDFs/LLMs. |
| YouTube Extractor service | Pipeline (URL → metadata → transcript → distill → render → store), catalog, file writes. |
| Obsidian vault | Searchable knowledge layer. Receives `.md` files; runs no code. |

**Service ports:**
- Mission Control: `:3000` (existing)
- Hermes: `:8642` (existing)
- **YouTube Extractor: `:18765`** (new, 127.0.0.1 only)

**Service runs as a launchd unit** (`com.deedee.youtube-extractor`) auto-starting at login, mirroring `com.deedee.hermes`.

**LLM dependency:**
The extractor talks to **Hermes** by default (so when you change Hermes routing, the extractor follows). Configurable via `LLM_BASE_URL` env var so outsiders can point at any OpenAI-compatible endpoint (Hermes, vLLM, Ollama, OpenRouter, OpenAI).

---

## 3. Pipeline modules

Six stages, each its own module, single responsibility.

```
URL ── url.py ──► video_id ── metadata.py ──► metadata
                                                  │
                                                  ▼
                                          transcript.py ──► transcript
                                                  │
                                                  ▼
                                            distill.py  (Hermes call)
                                                  │
                                          ┌───────┴───────┐
                                          ▼               ▼
                                       FULL doc       LAZY doc
                                          │               │
                                          └───────┬───────┘
                                                  ▼
                                          render_md.py + render_pdf.py
                                                  │
                                                  ▼
                                            store.py (catalog write)
```

**Module contracts:**

| Module | Input | Output | External deps |
|--------|-------|--------|---------------|
| `url.py` | string URL | `video_id` (str) | none |
| `metadata.py` | `video_id` | `Metadata{title, channel, duration_s, published, thumbnail_url, description}` | yt-dlp |
| `transcript.py` | `video_id` | `Transcript{segments, full_text, language, source: 'official'}` | youtube-transcript-api |
| `distill.py` | metadata + transcript | `Distillation{full: FullDoc, lazy: LazyDoc}` | Hermes HTTP |
| `render_md.py` | metadata + distillation | writes `.md` to vault | jinja |
| `render_pdf.py` | metadata + distillation | writes `{slug}-full.pdf` + `{slug}-lazy.pdf` | WeasyPrint + jinja |
| `store.py` | full job record | appends to `catalog.ndjson` | none |

**Whisper fallback is deferred to v2.** v1 fails-fast on videos without official captions (`error_code: NO_TRANSCRIPT`).

**Chunking for long videos:** transcripts that exceed the LLM context window get split (by chapter or 20k-token windows), each chunk distilled independently, then a second-pass consolidation. Logic lives entirely in `distill.py`.

---

## 4. Distillation contract

One Hermes call returns structured JSON for both modes (single round-trip):

```json
{
  "title": "string — cleaned title",
  "tldr": "string — 1 sentence",
  "lazy": {
    "key_points": ["string", "..."],
    "summary_paragraph": "string — ~150 words"
  },
  "full": {
    "chapters": [
      {
        "title": "string",
        "summary": "string",
        "key_points": ["string", "..."],
        "quotes": ["string verbatim from transcript", "..."]
      }
    ],
    "topics": ["string — for tags"],
    "people": ["string — named in video"],
    "references": ["string — URLs/books/papers mentioned"]
  }
}
```

Hermes is called with `response_format: json_object` and a strict system prompt. On malformed JSON, one retry; on second failure, mark the job failed.

---

## 5. Storage layout

**Slug format** (canonical key):
```
{published_date}-{youtube_id}-{kebab-title}
2026-04-22-dQw4w9WgXcQ-rick-astley-never-gonna-give-you-up
```

Truncated to 80 chars. Used as the filename root for `.md`, both PDFs, the meta JSON, and the catalog row.

**Output paths:**

```
~/.claude/obsidian-mind/youtube/                        ← vault, configurable
  {slug}.md

~/Youtube-extractor/output/                              ← repo output, gitignored
  {slug}-full.pdf
  {slug}-lazy.pdf
  {slug}-meta.json     ← original URL, full distillation JSON, paths, durations
  catalog.ndjson       ← append-only, one line per video, drives archive list
  jobs.ndjson          ← append-only, one line per job state transition
```

**Markdown frontmatter (Obsidian):**

```yaml
---
title: "..."
channel: "..."
url: https://youtube.com/watch?v=...
duration: 213
published: 2009-10-25
extracted: 2026-05-03
tags: [youtube, ...]
people: ["..."]
references: ["..."]
pdfs:
  full: "~/Youtube-extractor/output/{slug}-full.pdf"
  lazy: "~/Youtube-extractor/output/{slug}-lazy.pdf"
---
```

Body: H1 title, callout TL;DR, key points, chapter sections (each with summary + key_points + quotes), source footer.

**Catalog row** (one NDJSON line):
```json
{"slug":"...","title":"...","channel":"...","url":"...","duration":213,"extracted_at":1777812345,"md_path":"...","pdf_full_path":"...","pdf_lazy_path":"...","tags":[...],"topics":[...]}
```

Drives the MC archive list and the search endpoint.

---

## 6. API surface

### YouTube Extractor (`http://127.0.0.1:18765`)

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/jobs` | Body: `{url}`. Validates, creates job, queues. Returns `{job_id, slug}` or `{error, code}` for invalid URL or duplicate. |
| GET | `/jobs/{id}` | Status: `queued` / `running` / `done` / `failed`, with `stage`, `error_code`, `error_message`, `retryable`. |
| POST | `/jobs/{id}/retry` | Re-runs from cached state (skips stages already cached on disk via `-meta.json`). |
| GET | `/archive` | List all rows from `catalog.ndjson`. Supports `?q=...` substring search across title/channel/tags/people. |
| GET | `/pdfs/{slug}/{full\|lazy}` | Serves the PDF bytes. |
| GET | `/files/{slug}/md` | Serves the `.md` raw text. |
| GET | `/health` | `{status: ok, version, hermes_reachable: bool}`. |

### Mission Control proxy (`/api/youtube/*`)

Mirrors the extractor surface 1:1, with bearer-token auth (existing MC middleware) and CORS handling. MC adds nothing semantic — it's pure proxy.

---

## 7. Mission Control tab UX

New left-nav entry under TOOLS group:

```
TOOLS
  📥 ReClip
  🕷 Scraper
  📄 CV Builder
  📡 Recon AI Radar
  🎬 YouTube Extractor   ← new
```

**Tab layout** (single column, matches existing tabs):

1. **Header** — title + extractor health badge (● online / ● offline)
2. **Paste form** — URL input + `Extract` button + footer note about destinations
3. **Active jobs** — in-flight jobs with status (`distilling (3/4)`), recently-done jobs with action buttons inline
4. **Search** — free-text search box ("title, channel, tag, person…")
5. **Archive list** — virtualised, each row: thumbnail + title + meta line + 3 action buttons:
   - Primary: `Open .md in Obsidian` (Mac only — `obsidian://` deep link)
     OR `View` (non-Mac — renders `.md` inline using existing `react-markdown`)
   - Secondary: `PDF FULL` + `PDF LAZY` (browser downloads via MC proxy)

**Device detection:** server reads `?host=mac` query param OR User-Agent. On Mac browsers, show Obsidian deep link. Elsewhere, show inline viewer.

---

## 8. Access architecture (LAN + Tailscale)

The only externally-reachable service is Mission Control. Everything else binds to `127.0.0.1`.

- **Extractor** binds `127.0.0.1:18765`. Reachable only by MC on the same host.
- **All file delivery proxies through MC.** Mobile/LAN devices receive PDFs and `.md` bytes via `/api/youtube/files/...` — never via direct extractor URLs.
- **CORS** stays whatever MC has in `MC_ALLOWED_ORIGINS` today (Tailscale hostname already included for `/tasks`).
- **Auth** via existing MC bearer token (`MC_API_TOKEN`). No new auth layer.

No firewall changes required. No new exposed ports.

---

## 9. Error handling

| Failure | Code | Recovery | UX |
|---------|------|----------|-----|
| Invalid URL | client-side | reject before queue | inline form error |
| Video unavailable / private | `VIDEO_UNAVAILABLE` | mark failed | red row + reason |
| No official transcript | `NO_TRANSCRIPT` | mark failed (Whisper deferred to v2) | row shows reason |
| YT rate-limit | retried | exp backoff 1s→2s→4s, max 3 | `retrying (2/3)` |
| Hermes offline | `HERMES_OFFLINE` | mark failed, transcript cached | `retry` button uses cache |
| Context overflow | chunked | transparent | `distilling (3/5 chunks)` |
| Hermes returns malformed JSON | `LLM_FORMAT` | one retry with stricter prompt | error reason shown |
| PDF render fails | `RENDER_FAIL` | `partial_success` (md saved) | `.md ✓ · PDF ✗ retry` |
| Disk full | `STORAGE_ERROR` | abort, log | top-of-page banner |
| Duplicate URL | not an error | return existing entry | "already extracted on {date} → [open]" |
| Concurrency | bounded queue | max 2 in-flight | `queued (3 ahead)` |
| Extractor service down | MC handles | MC returns 503 | banner with `launchctl` recovery hint |

**Retry semantics:** idempotent on slug. Cached stages on disk are skipped. Failed PDF render only re-runs render, not the 90-second distillation.

**Error envelope** (every failed `GET /jobs/{id}`):
```json
{
  "id": "...",
  "status": "failed",
  "stage": "transcript|distill|render_pdf|store",
  "error_code": "...",
  "error_message": "...",
  "retryable": true,
  "retry_url": "/api/youtube/jobs/{id}/retry"
}
```

---

## 10. Configuration

All paths and endpoints are env-overridable. Defaults match the author's setup; outsiders override one or two and they're done.

```bash
# .env.example

# LLM endpoint — OpenAI-compatible
LLM_BASE_URL=http://localhost:8642        # default: Hermes
LLM_API_KEY=                              # optional
LLM_MODEL=                                # optional override (else router default)

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

---

## 11. Public repo deliverables

**Repository**: `github.com/psyd3x/youtube-extractor`, public, MIT license.

**Structure** (committed):
```
~/Youtube-extractor/
├── README.md                  # 30-second quickstart + architecture + "How I use it"
├── LICENSE                    # MIT
├── CLAUDE.md                  # repo conventions
├── pyproject.toml
├── .env.example
├── .gitignore                 # blocks output/, .env, __pycache__, .venv, *.pdf
├── docs/
│   └── specs/
│       └── 2026-05-03-youtube-extractor-design.md   ← this file
├── src/youtube_extractor/
│   ├── __init__.py
│   ├── main.py                # FastAPI app + uvicorn entrypoint
│   ├── cli.py                 # standalone CLI (no MC required)
│   ├── api/
│   │   ├── jobs.py
│   │   ├── archive.py
│   │   └── files.py
│   ├── pipeline/
│   │   ├── url.py
│   │   ├── metadata.py
│   │   ├── transcript.py
│   │   ├── distill.py
│   │   ├── render_md.py
│   │   └── render_pdf.py
│   ├── store/
│   │   ├── catalog.py
│   │   └── search.py
│   └── llm/
│       └── client.py           # OpenAI-compatible HTTP client
├── templates/
│   ├── full.html.jinja
│   ├── lazy.html.jinja
│   └── obsidian.md.jinja
├── tests/
│   ├── test_url.py
│   ├── test_pipeline.py
│   └── fixtures/
└── .github/
    └── workflows/
        └── ci.yml              # pytest + ruff on push (v1)
```

**Pre-push security** (per global rule): `.gitignore` covers all secret-shaped paths; pre-push runs `gitleaks protect --staged` if installed.

**README scope:**
1. 30-second quickstart (install, set env, `youtube-extractor extract <url>`)
2. Architecture diagram (same as section 2 of this spec)
3. Configuration reference
4. "How I use it" — pointer to Mission Control integration as one consumer
5. Roadmap / v2 (Whisper fallback, batch/playlist, browser extension)

---

## 12. Out of scope (v1)

Documented here so the implementation plan doesn't drift:

- Whisper fallback — deferred to v2
- Batch/playlist input — v2
- Tag editing / metadata correction in UI — v2
- Vector search (Hermes/ChromaDB ingestion) — v2
- Browser extension — v3+
- Multi-user / API auth on extractor — v3+ (not needed while it's localhost-only)

---

## 13. Suggested implementation order

For the writing-plans skill to consume. Independent groups can be parallelised across agents.

| # | Group | Independent of | Owner |
|---|-------|----------------|-------|
| 1 | Repo scaffold + CI + LICENSE + README skeleton + .gitignore | — | foundation, must run first |
| 2 | `pipeline/url.py` + `pipeline/metadata.py` + tests | 1 | parallel-A |
| 3 | `pipeline/transcript.py` + tests | 1 | parallel-B |
| 4 | `llm/client.py` + `pipeline/distill.py` + tests (mock Hermes) | 1 | parallel-C |
| 5 | `templates/*.jinja` + `pipeline/render_md.py` + `pipeline/render_pdf.py` + visual smoke test | 1 | parallel-D |
| 6 | `store/catalog.py` + `store/search.py` + tests | 1 | parallel-E |
| 7 | `api/jobs.py` + `api/archive.py` + `api/files.py` + `main.py` (wire pipeline + store) | 2-6 | sequential, after parallel waves |
| 8 | `cli.py` (standalone usage) | 7 | sequential |
| 9 | launchd plist + service install instructions | 7 | sequential, can run alongside 8 |
| 10 | MC `/api/youtube/*` proxy routes (in OpenDeeDee/mission-control repo) | 7 | sequential |
| 11 | MC `/youtube` tab UI + sidebar entry | 10 | sequential |
| 12 | End-to-end smoke test on a real video | 11 | final |

Phases 2-6 can run as 5 parallel agents after phase 1 lands. Phase 7 collects.

---

## 14. Acceptance criteria

The feature is shipped when:

1. `youtube-extractor extract https://youtu.be/<id>` from CLI produces `.md` in vault + 2 PDFs in output dir, on a video with official captions.
2. Mission Control `/youtube` tab is visible in sidebar (TOOLS group), paste form accepts a URL, archive list shows the entry within 2 minutes, and PDF downloads work from the LAN URL on a phone.
3. The error rows in section 9 each render correctly when the corresponding failure is induced (manual test or fixture).
4. `pytest -q` passes locally and on GitHub Actions CI.
5. Public repo at `github.com/psyd3x/youtube-extractor` exists with README, LICENSE, and a clean first commit (no leaked secrets per pre-push scan).

---
