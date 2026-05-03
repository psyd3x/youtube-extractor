---
title: Manual test log
project: youtube-extractor
type: smoke-log
date: 2026-05-03
tags: [youtube-extractor, smoke-test, mission-control, manual-qa]
description: Running log of manual end-to-end smoke runs against the live YouTube Extractor service and the Mission Control /youtube tab. Each entry records the date, what was exercised, observed behavior, and any deferred verification steps that still need a human.
---

# Manual test log

Smoke runs against the live extractor + Mission Control proxy. See [[2026-05-03-youtube-extractor-design]] for the spec and [[2026-05-03-youtube-extractor]] for the plan.

- 2026-05-03: end-to-end MC tab smoke (API path) — extractor :18765 healthy (hermes_reachable=true), MC :3000/youtube returns 200, archive proxy returns 1 entry from Task 22 smoke. Idempotency confirmed: re-POSTing same URL via MC proxy short-circuits to `done` in ~1ms with no archive growth. File proxy: md→200 text/plain, pdf full→30058 bytes (valid PDF 1.7), pdf lazy→14464 bytes (valid PDF 1.7), bogus kind→400. LAN/Tailscale + browser-paste verification deferred to Dexter.
- 2026-05-03: archive-delete API smoke — extractor + MC restarted to pick up DELETE route. Sidebar reads "YT Extractor" (renamed from "YouTube"). `DELETE /api/youtube/archive/totally-nonexistent-xyz` via MC proxy returns 404 `{"detail":"slug not found: totally-nonexistent-xyz"}` — full chain (Next route → ytFetch → FastAPI → ArchiveEntryNotFound → HTTPException) works end-to-end. Backend tests 69/69, ruff clean. Browser-level two-click confirm UI smoke (arm → 3s auto-disarm → confirm → row vanishes → on-disk verification of .md + 2 PDFs + catalog row + jobs.ndjson row gone) deferred to Dexter; the 3Blue1Brown smoke entry intentionally preserved.
