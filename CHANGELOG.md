# Changelog

Notable user-facing changes are recorded here. This project follows a versioned release scheme.

## [3.0.0] - 2026-10-27

- Reworked as a cross-platform Python web application for macOS, Windows, and Raspberry Pi.
- Added gallery-first collection browsing, search, filtering, sorting, and editable record details.
- Added import of 1–6 role-labelled images per record with grouping checks and background jobs.
- Added configurable OpenAI, Anthropic, and Gemini enrichment, with confidence information.
- Added Discogs lookup, rate-aware requests, scored candidate matching, and a threshold of 60 for automatic selection.
- Added CSV, Excel, JSON, and printable HTML exports.
- Added full database-and-image ZIP backup and restore.
- Stores runtime collection data and settings outside the source repository in per-user application data.
- Uses FastAPI, SQLite, and a vanilla JavaScript frontend; no Node build step.
