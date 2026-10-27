"""SQLite schema, migrations and connection helpers (stdlib only)."""
from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 3

# Initial schema (version 1)
_BASE_SCHEMA = """
CREATE TABLE IF NOT EXISTS app_meta (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS records (
    id              TEXT PRIMARY KEY,
    artist          TEXT,
    title           TEXT,
    label           TEXT,
    catalog_number  TEXT,
    barcode         TEXT,
    year            INTEGER,
    genre           TEXT,
    format          TEXT,
    country         TEXT,
    notes           TEXT,
    price_eur       REAL,
    price_low_eur   REAL,
    price_high_eur  REAL,
    ai_data_json    TEXT,            -- raw JSON from AI provider
    ai_confidence   TEXT,            -- high | low | unknown
    ai_reason       TEXT,
    discogs_data_json TEXT,          -- selected candidate JSON
    discogs_confidence TEXT,         -- high | low | unknown
    discogs_reason  TEXT,
    status          TEXT DEFAULT 'new',  -- new | ai_done | discogs_done | both | exported
    created_at      TEXT,
    updated_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_records_status      ON records(status);
CREATE INDEX IF NOT EXISTS idx_records_ai_conf     ON records(ai_confidence);
CREATE INDEX IF NOT EXISTS idx_records_dc_conf     ON records(discogs_confidence);

CREATE TABLE IF NOT EXISTS images (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    record_id    TEXT NOT NULL,
    role         TEXT NOT NULL,    -- front | back | label_a | label_b | inner_sleeve | other
    position     INTEGER NOT NULL, -- 1..6 within the record's image set
    original_filename TEXT,
    stored_path  TEXT NOT NULL,
    thumb_path   TEXT,
    width        INTEGER,
    height       INTEGER,
    size_bytes   INTEGER,
    FOREIGN KEY(record_id) REFERENCES records(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_images_record ON images(record_id);

CREATE TABLE IF NOT EXISTS jobs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL,         -- import | ai_enrich | discogs_enrich
    state       TEXT NOT NULL,         -- queued | running | done | error | cancelled
    total       INTEGER DEFAULT 0,
    done        INTEGER DEFAULT 0,
    current     TEXT,
    percent     REAL DEFAULT 0.0,
    eta_seconds INTEGER DEFAULT 0,
    status_text TEXT,
    error       TEXT,
    started_at  TEXT,
    finished_at TEXT,
    params_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs(state);

CREATE TABLE IF NOT EXISTS job_events (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id  INTEGER NOT NULL,
    ts      TEXT,
    level   TEXT,
    message TEXT,
    FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ki_cache (
    cache_key   TEXT PRIMARY KEY,
    provider    TEXT,
    model       TEXT,
    payload     TEXT,                 -- full AI JSON
    created_at  TEXT
);

CREATE TABLE IF NOT EXISTS discogs_cache (
    cache_key   TEXT PRIMARY KEY,
    query       TEXT,
    payload     TEXT,                 -- raw search results
    created_at  TEXT
);
"""

# Migration snippets keyed by version -> list of SQL statements.
# (Base schema already targets SCHEMA_VERSION = 3; new versions append here.)
_MIGRATIONS: dict = {}


def connect(db_path: Path) -> sqlite3.Connection:
    """Open a SQLite connection with sensible defaults."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def get_schema_version(conn: sqlite3.Connection) -> int:
    """Return the current schema version stored in app_meta."""
    row = conn.execute(
        "SELECT value FROM app_meta WHERE key='schema_version'"
    ).fetchone()
    if not row:
        return 0
    try:
        return int(row["value"])
    except (TypeError, ValueError):
        return 0


def set_schema_version(conn: sqlite3.Connection, version: int) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO app_meta(key,value) VALUES('schema_version', ?)",
        (str(version),),
    )


def init_db(db_path: Path) -> sqlite3.Connection:
    """Initialise the database, creating tables and applying migrations."""
    conn = connect(db_path)
    conn.executescript(_BASE_SCHEMA)
    current = get_schema_version(conn)
    if current < 1:
        current = 1
        set_schema_version(conn, 1)
    for v in sorted(_MIGRATIONS):
        if current < v:
            logger.info("Applying migration to schema version %s", v)
            for stmt in _MIGRATIONS[v]:
                try:
                    conn.execute(stmt)
                except sqlite3.OperationalError as exc:
                    logger.warning("Migration step skipped: %s (%s)", stmt, exc)
            set_schema_version(conn, v)
            current = v
    return conn


@contextmanager
def tx(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Lightweight transaction context manager (commits on success)."""
    try:
        conn.execute("BEGIN")
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
