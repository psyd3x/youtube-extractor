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

## Design + Plan
- Design spec: `docs/specs/2026-05-03-youtube-extractor-design.md`
- Implementation plan: `docs/superpowers/plans/2026-05-03-youtube-extractor.md`
