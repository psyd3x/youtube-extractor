# YouTube Extractor

Turn a YouTube link into a distilled Markdown note in your Obsidian vault plus two PDFs (FULL + LAZY) — calling any OpenAI-compatible LLM endpoint to do the distillation.

## Why

Watching long videos is slow. Reading distilled notes is fast. This service takes a YouTube URL and produces a comprehensive `.md` in your knowledge base plus print-ready PDFs, never storing the raw transcript — only the substance.

**Two PDF modes per video:**
- **FULL** — chapter-by-chapter breakdown with key points, quotes, references. Length scales with video length.
- **LAZY** — hook + 5-10 key points + 1-paragraph summary. ~1-2 pages, readable in 60 seconds.

The Markdown file lands in your Obsidian vault and is the single source of truth (wikilinkable, searchable). PDFs are derivatives.

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

PDF rendering uses [WeasyPrint](https://weasyprint.org/), which requires Pango at the OS level:

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

## Run as a service

```bash
youtube-extractor serve
# binds 127.0.0.1:18765 by default
```

REST API surface: `POST /jobs`, `GET /jobs/{id}`, `GET /archive`, `GET /pdfs/{slug}/{full|lazy}`, `GET /files/{slug}/md`. See `docs/specs/2026-05-03-youtube-extractor-design.md` for the full spec.

### Auto-start on macOS (launchd)

```bash
mkdir -p ~/.openclaw/logs   # or wherever you want logs
cp deploy/com.deedee.youtube-extractor.plist ~/Library/LaunchAgents/
launchctl load -w ~/Library/LaunchAgents/com.deedee.youtube-extractor.plist
launchctl list | grep youtube-extractor   # status 0 = running
```

The plist assumes the repo lives at `/Users/<you>/Youtube-extractor/` with a venv at `.venv/`. Edit `ProgramArguments`, `WorkingDirectory`, and the log paths if your setup differs.

To stop / restart / uninstall:

```bash
launchctl stop com.deedee.youtube-extractor
launchctl start com.deedee.youtube-extractor
launchctl unload ~/Library/LaunchAgents/com.deedee.youtube-extractor.plist
```

### Auto-start on Linux (systemd)

A user-unit is straightforward — call `youtube-extractor serve` from `~/.config/systemd/user/youtube-extractor.service`. PR welcome if you want this committed.

## Configuration

All paths and endpoints are env-overridable. See `.env.example`.

LLM backend works with any OpenAI-compatible API:
- [Hermes](https://github.com/psyd3x/hermes) (default)
- vLLM, Ollama, LM Studio (local)
- OpenAI, OpenRouter, Anthropic via proxy (cloud)

## How I use it

I run this on a Mac Studio with a tab in Mission Control (private repo) that proxies to it. The LLM lives on a DGX Spark on my LAN, routed through Hermes. End-to-end takes ~90 seconds for a 1-hour video.

## Architecture

See `docs/specs/2026-05-03-youtube-extractor-design.md` for the full design including pipeline, storage layout, and error handling.

## Roadmap

- [ ] v2: Whisper fallback for videos without official captions
- [ ] v2: Batch / playlist input
- [ ] v3: Browser extension

## License

MIT
