# Contributing

Thanks for helping improve Vinyl Catalog. Contributions of code, tests, documentation, translations, and careful bug reports are welcome.

## Before you start

1. Search existing issues and discussions. For significant changes, open a feature request first so the direction can be discussed.
2. For a bug report, include operating system, Python version, steps to reproduce, expected/actual result, and sanitized logs. Never attach API keys, private collection data, or unredacted photos.
3. Follow the [Code of Conduct](CODE_OF_CONDUCT.md). Keep the application interface and user-facing documentation in English.

## Local setup

Python 3.10–3.12 is supported. From the repository root:

```bash
python -m venv .venv
# macOS/Linux: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
pytest -q
```

## Pull requests

- Fork the repository and create a focused branch, for example `fix/image-grouping`.
- Keep changes small and explain the user problem they solve.
- Add or update tests in `tests/` for behavior changes. Avoid network calls in tests; use deterministic fixtures/mocks.
- Run `pytest -q` and report the result. If a test cannot run on your platform, say so.
- Update relevant docs, `CHANGELOG.md`, or `ROADMAP.md` when user-facing behavior changes.
- Never commit collection databases, photos, backups, `.env` files, settings files, API keys, or other personal data.
- Submit a pull request with a clear summary, testing notes, and screenshots for UI changes (use anonymized data).

Maintainers may request changes before merging. By submitting a contribution, you agree that it is provided under the project's MIT license.
