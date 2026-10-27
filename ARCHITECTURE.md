# Architecture

## Overview

Vinyl Catalog is a single-user, self-hosted web application. A FastAPI/uvicorn server delivers the HTML interface, static assets, JSON APIs, and local collection operations. There is no frontend build system or required Node.js runtime.

## Components

- `app/api/server.py` creates the FastAPI application, serves `templates/index.html` and `static/`, exposes API routes, and starts uvicorn.
- `app/config.py` defines runtime settings (default port 8501 and default listener) and resolves the per-user data directory through `platformdirs` with a fallback.
- `app/db/schema.py` initializes the SQLite schema; `app/db/repository.py` encapsulates record and related data operations.
- `app/services/` contains image grouping/cleaning, import and background-job logic, thumbnail processing, and export/backup/restore operations.
- `app/ai/providers.py` integrates supported AI providers. `app/discogs/client.py` communicates with Discogs; `scoring.py` scores candidates and gates auto-selection at 60.
- `static/app.js` implements browser interactions; `static/app.css` styles the interface.

## Runtime data and privacy boundaries

The application stores the SQLite database, managed record images, and `settings.json` beneath a per-user application-data directory; they should not be placed in Git. `settings.json` contains configured API credentials in plaintext. The app makes network requests only to configured enrichment services when those features are used (package installation also needs internet access). AI enrichment may send record images and metadata to the selected AI provider. Users must decide whether those transfers fit their privacy needs.

## Typical data flow

1. The browser requests the gallery and API data from the local FastAPI process.
2. During import, the user selects a source folder and grouping/role options. The service copies selected images into managed storage, creates thumbnails, and records progress in a background job.
3. Record metadata and image references are stored in SQLite. Editing and filtering use the local API/database.
4. Optional AI and Discogs jobs retrieve suggestions and confidence/match information. Discogs auto-selection is allowed only when its score reaches 60; lower scores remain for manual review.
5. Exports serialize collection data; a full backup ZIP includes the SQLite database, image tree, and manifest. Treat exports/backups as private data.

## Network exposure

The default listener is `0.0.0.0:8501` to support access from other devices on a trusted LAN. The initial release has no built-in user authentication or TLS. Do not forward the port from a router or expose it directly to the public internet. Local firewall policy and LAN trust remain the operator's responsibility.
