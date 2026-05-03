# YouTube Extractor

A small self-hosted service that turns any YouTube URL into a distilled Markdown note in your Obsidian vault plus two print-ready PDFs — using any OpenAI-compatible LLM endpoint to do the distillation.

It never stores the raw transcript. Only the substance survives the pipeline.

## What it does

You paste a URL. About ninety seconds later (for a one-hour video, depending on your LLM), three artefacts land on disk:

1. **A Markdown note** in your Obsidian vault — chapter-by-chapter, with key points, named entities, references, and a YAML frontmatter you can wikilink and search across the rest of your knowledge base. This is the source of truth.
2. **`{slug}-full.pdf`** — a comprehensive write-up that scales with the video length. Quotes, callouts, references, the whole thing. Print it, read it on a tablet, mark it up.
3. **`{slug}-lazy.pdf`** — one to two pages. A hook, five to ten key points, and a single-paragraph summary. Readable in a minute. The version you actually share with people.

The Markdown is canonical. The PDFs are renderings of it. If you edit the note in Obsidian, the next re-extraction does not overwrite your work — videos are cached by stable slug, so re-running the same URL is a near-instant catalog hit, not a re-run of the LLM.

## Why this exists

Long videos are an inefficient way to get information into your head. Most of what you watch is filler, framing, repetition, and pleasantries. The thirty minutes of substance buried inside a ninety-minute interview is what you actually want.

The pattern of "watch a video → take notes → never look at the notes again" wastes both the watching time and the note-taking time. This flips it: spend ninety seconds of compute, get a structured note that is searchable forever, and use the time you saved to actually think.

The output goes to your own vault on your own disk, distilled by your own LLM if you want it that way. Nothing about the source video, the transcript, or your reading patterns leaves the machine.

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

### System dependencies

PDF rendering uses [WeasyPrint](https://weasyprint.org/), which depends on Pango at the OS level:

```bash
# macOS
brew install pango

# Debian/Ubuntu
sudo apt-get install -y libpango-1.0-0 libpangoft2-1.0-0
```

Outputs land in:
- `$OBSIDIAN_VAULT_PATH/{slug}.md`
- `$OUTPUT_DIR/{slug}-full.pdf`
- `$OUTPUT_DIR/{slug}-lazy.pdf`

The slug is derived from the upload date, video id, and a slugified title — stable across re-runs, safe across filesystems, and short enough to fit comfortably in URLs and shell completion.

## Run as a service

The CLI is convenient for one-offs. If you want to feed it from a browser tab, a shortcut, or another tool, run it as an HTTP service:

```bash
youtube-extractor serve
# binds 127.0.0.1:18765 by default — localhost only, no network exposure
```

REST surface:

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/jobs` | Submit a URL, get a job id back. Idempotent — re-submitting a known video short-circuits to the cached entry in milliseconds. |
| `GET` | `/jobs/{id}` | Poll for status (`queued` → `running` → `done` / `failed`). Failed jobs include a `retry_url` when the failure was transient. |
| `POST` | `/jobs/{id}/retry` | Restart a failed job. |
| `GET` | `/archive?q=...` | List or search the catalog. Substring match across title, channel, tags, topics, people. |
| `GET` | `/pdfs/{slug}/{full\|lazy}` | Serve the rendered PDF. |
| `GET` | `/files/{slug}/md` | Serve the rendered Markdown as `text/plain`. |
| `DELETE` | `/archive/{slug}` | Hard-delete an entry: catalog row, the `.md`, both PDFs, and every job-history row tied to that slug. Returns a per-step report. |
| `GET` | `/health` | Liveness + downstream LLM reachability. |

The full design — pipeline stages, storage layout, error taxonomy, idempotency rules — is in `docs/specs/2026-05-03-youtube-extractor-design.md`.

### Auto-start on macOS (launchd)

```bash
mkdir -p ~/.openclaw/logs   # or wherever you want logs
cp deploy/com.deedee.youtube-extractor.plist ~/Library/LaunchAgents/
launchctl load -w ~/Library/LaunchAgents/com.deedee.youtube-extractor.plist
launchctl list | grep youtube-extractor   # status 0 = running
```

The plist assumes the repo lives at `/Users/<you>/Youtube-extractor/` with a venv at `.venv/`. Edit `ProgramArguments`, `WorkingDirectory`, and the log paths if your setup differs.

Stop, restart, or uninstall:

```bash
launchctl stop com.deedee.youtube-extractor
launchctl start com.deedee.youtube-extractor
launchctl unload ~/Library/LaunchAgents/com.deedee.youtube-extractor.plist
```

### Auto-start on Linux (systemd)

A user-unit is a five-line wrapper around `youtube-extractor serve` in `~/.config/systemd/user/youtube-extractor.service`. PR welcome if you want one committed to the repo.

## Configuration

Every path and endpoint is env-overridable. See `.env.example` for the full surface.

The LLM backend speaks OpenAI's chat-completions dialect, so anything that does works:

- **Local** — vLLM, Ollama, LM Studio, or any other server fronting a local model.
- **Self-hosted gateways** — [Hermes](https://github.com/psyd3x/hermes) is the default in `.env.example`.
- **Cloud** — OpenAI, OpenRouter, Together, Groq, or any compatible proxy.

There is no provider-specific code path. Switch endpoints by editing one variable.

## Design notes

A few decisions worth surfacing because they are not obvious from the code:

- **The Markdown is the artefact, the PDFs are renderings.** Anything you do to the `.md` survives. The PDFs are regenerated on demand from a template, so changing the template re-flows everything without re-running the LLM.
- **Atomic catalog and job-log writes.** Mutations to `catalog.ndjson` and `jobs.ndjson` go through a temp file plus `os.replace`, so concurrent readers always see either the old file or the new one — never a partial. This is visibility-atomic, not crash-durable; matches the "single user, single machine" deployment model the rest of the service assumes.
- **Idempotency by slug.** The slug is computed before the LLM step, so the de-dup happens early. Re-submitting a known URL costs a catalog lookup, not a distillation.
- **Failure modes are recoverable.** A delete that crashes mid-flight (after files are unlinked but before the catalog is rewritten) heals on the next attempt — the second delete simply finds the files already gone and finishes the job. No checkpoint machinery, no manual cleanup.

## Roadmap

- [ ] Whisper fallback for videos without official captions.
- [ ] Batch / playlist input.
- [ ] Browser extension that POSTs the current tab to `/jobs` with one keystroke.

## License

MIT.
