"""Repository layer: typed access over the SQLite database."""
from __future__ import annotations

import json
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .schema import SCHEMA_VERSION, connect, init_db, tx


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def make_record_id(conn: sqlite3.Connection) -> str:
    """Generate a generic unique record id like ``VC-000123``."""
    row = conn.execute("SELECT COUNT(*) AS c FROM records").fetchone()
    n = (row["c"] or 0) + 1
    return f"VC-{n:06d}-{uuid.uuid4().hex[:4]}"


@dataclass
class Record:
    id: str
    artist: Optional[str] = None
    title: Optional[str] = None
    label: Optional[str] = None
    catalog_number: Optional[str] = None
    barcode: Optional[str] = None
    year: Optional[int] = None
    genre: Optional[str] = None
    format: Optional[str] = None
    country: Optional[str] = None
    notes: Optional[str] = None
    price_eur: Optional[float] = None
    price_low_eur: Optional[float] = None
    price_high_eur: Optional[float] = None
    ai_data_json: Optional[Dict[str, Any]] = None
    ai_confidence: Optional[str] = None
    ai_reason: Optional[str] = None
    discogs_data_json: Optional[Dict[str, Any]] = None
    discogs_confidence: Optional[str] = None
    discogs_reason: Optional[str] = None
    status: str = "new"
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def to_row_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["ai_data_json"] = json.dumps(self.ai_data_json or {}, ensure_ascii=False)
        d["discogs_data_json"] = json.dumps(self.discogs_data_json or {}, ensure_ascii=False)
        return d


class Repo:
    """Thin wrapper around sqlite3 with typed CRUD."""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.conn = init_db(self.db_path)

    def close(self) -> None:
        """Close the underlying SQLite connection and release database files."""
        self.conn.close()

    def __enter__(self) -> "Repo":
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        self.close()

    # ---------- records ----------
    def insert_record(self, rec: Record) -> Record:
        rec.created_at = rec.created_at or _now()
        rec.updated_at = _now()
        d = rec.to_row_dict()
        cols = ", ".join(d.keys())
        placeholders = ", ".join("?" * len(d))
        with tx(self.conn):
            self.conn.execute(
                f"INSERT INTO records ({cols}) VALUES ({placeholders})",
                list(d.values()),
            )
        return rec

    def update_record(self, rec_id: str, fields: Dict[str, Any]) -> None:
        if not fields:
            return
        fields = dict(fields)
        fields["updated_at"] = _now()
        if "ai_data_json" in fields and not isinstance(fields["ai_data_json"], str):
            fields["ai_data_json"] = json.dumps(fields["ai_data_json"] or {}, ensure_ascii=False)
        if "discogs_data_json" in fields and not isinstance(fields["discogs_data_json"], str):
            fields["discogs_data_json"] = json.dumps(fields["discogs_data_json"] or {}, ensure_ascii=False)
        cols = ", ".join(f"{k}=?" for k in fields.keys())
        params = list(fields.values()) + [rec_id]
        with tx(self.conn):
            self.conn.execute(f"UPDATE records SET {cols} WHERE id=?", params)

    def delete_record(self, rec_id: str) -> None:
        with tx(self.conn):
            self.conn.execute("DELETE FROM records WHERE id=?", (rec_id,))

    def get_record(self, rec_id: str) -> Optional[Dict[str, Any]]:
        row = self.conn.execute("SELECT * FROM records WHERE id=?", (rec_id,)).fetchone()
        return _row_to_dict(row)

    def list_records(
        self,
        search: Optional[str] = None,
        status: Optional[str] = None,
        confidence: Optional[str] = None,
        has_ai: Optional[bool] = None,
        has_discogs: Optional[bool] = None,
        year_from: Optional[int] = None,
        year_to: Optional[int] = None,
        genre: Optional[str] = None,
        label: Optional[str] = None,
        sort: str = "updated_desc",
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM records WHERE 1=1"
        params: List[Any] = []
        if search:
            sql += " AND (artist LIKE ? OR title LIKE ? OR label LIKE ? OR catalog_number LIKE ?)"
            like = f"%{search}%"
            params.extend([like, like, like, like])
        if status:
            sql += " AND status=?"
            params.append(status)
        if confidence in ("high", "low", "unknown"):
            sql += " AND (ai_confidence=? OR discogs_confidence=?)"
            params.extend([confidence, confidence])
        if has_ai is True:
            sql += " AND ai_data_json IS NOT NULL AND ai_data_json != '{}'"
        elif has_ai is False:
            sql += " AND (ai_data_json IS NULL OR ai_data_json = '{}')"
        if has_discogs is True:
            sql += " AND discogs_data_json IS NOT NULL AND discogs_data_json != '{}'"
        elif has_discogs is False:
            sql += " AND (discogs_data_json IS NULL OR discogs_data_json = '{}')"
        if year_from is not None:
            sql += " AND year >= ?"
            params.append(year_from)
        if year_to is not None:
            sql += " AND year <= ?"
            params.append(year_to)
        if genre:
            sql += " AND genre LIKE ?"
            params.append(f"%{genre}%")
        if label:
            sql += " AND label LIKE ?"
            params.append(f"%{label}%")

        sort_map = {
            "updated_desc": "updated_at DESC",
            "updated_asc":  "updated_at ASC",
            "artist_asc":   "artist ASC",
            "artist_desc":  "artist DESC",
            "title_asc":    "title ASC",
            "title_desc":   "title DESC",
            "year_desc":    "year DESC",
            "year_asc":     "year ASC",
            "created_desc": "created_at DESC",
        }
        sql += " ORDER BY " + sort_map.get(sort, "updated_at DESC")
        sql += " LIMIT ?"
        params.append(int(limit))
        rows = self.conn.execute(sql, params).fetchall()
        return [_row_to_dict(r) for r in rows]

    def all_records(self) -> List[Dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM records").fetchall()
        return [_row_to_dict(r) for r in rows]

    # ---------- images ----------
    def add_image(
        self,
        record_id: str,
        role: str,
        position: int,
        original_filename: str,
        stored_path: str,
        thumb_path: Optional[str],
        width: Optional[int],
        height: Optional[int],
        size_bytes: Optional[int],
    ) -> int:
        cur = self.conn.execute(
            """INSERT INTO images
               (record_id, role, position, original_filename, stored_path, thumb_path,
                width, height, size_bytes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (record_id, role, position, original_filename, stored_path, thumb_path,
             width, height, size_bytes),
        )
        return int(cur.lastrowid or 0)

    def get_images(self, record_id: str) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM images WHERE record_id=? ORDER BY position ASC",
            (record_id,),
        ).fetchall()
        return [dict(r) for r in rows]

    # ---------- jobs ----------
    def create_job(self, kind: str, params: Optional[Dict[str, Any]] = None) -> int:
        cur = self.conn.execute(
            """INSERT INTO jobs(kind, state, status_text, started_at, params_json)
               VALUES (?, 'queued', 'Queued', ?, ?)""",
            (kind, _now(), json.dumps(params or {})),
        )
        return int(cur.lastrowid or 0)

    def update_job(self, job_id: int, fields: Dict[str, Any]) -> None:
        if not fields:
            return
        cols = ", ".join(f"{k}=?" for k in fields.keys())
        params = list(fields.values()) + [job_id]
        self.conn.execute(f"UPDATE jobs SET {cols} WHERE id=?", params)

    def append_job_event(self, job_id: int, level: str, message: str) -> None:
        self.conn.execute(
            "INSERT INTO job_events(job_id, ts, level, message) VALUES (?, ?, ?, ?)",
            (job_id, _now(), level, message),
        )

    def get_job(self, job_id: int) -> Optional[Dict[str, Any]]:
        row = self.conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return dict(row) if row else None

    def list_jobs(self, limit: int = 50) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def cancel_job(self, job_id: int) -> None:
        self.update_job(job_id, {"state": "cancelled", "status_text": "Cancelled"})

    # ---------- caches ----------
    def cache_get(self, table: str, key: str) -> Optional[Dict[str, Any]]:
        if table not in ("ki_cache", "discogs_cache"):
            raise ValueError("invalid cache table")
        row = self.conn.execute(
            f"SELECT * FROM {table} WHERE cache_key=?", (key,)
        ).fetchone()
        return dict(row) if row else None

    def cache_set(self, table: str, key: str, payload: Dict[str, Any], **extra: Any) -> None:
        if table not in ("ki_cache", "discogs_cache"):
            raise ValueError("invalid cache table")
        payload_json = json.dumps(payload, ensure_ascii=False)
        if table == "ki_cache":
            self.conn.execute(
                """INSERT OR REPLACE INTO ki_cache(cache_key, provider, model, payload, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                (key, extra.get("provider", ""), extra.get("model", ""),
                 payload_json, _now()),
            )
        else:
            self.conn.execute(
                """INSERT OR REPLACE INTO discogs_cache(cache_key, query, payload, created_at)
                   VALUES (?, ?, ?, ?)""",
                (key, extra.get("query", ""), payload_json, _now()),
            )

    # ---------- meta ----------
    def meta(self) -> Dict[str, Any]:
        row = self.conn.execute(
            "SELECT value FROM app_meta WHERE key='schema_version'"
        ).fetchone()
        ver = int(row["value"]) if row else 0
        return {
            "schema_version": ver,
            "record_count": self.conn.execute("SELECT COUNT(*) AS c FROM records").fetchone()["c"],
            "image_count": self.conn.execute("SELECT COUNT(*) AS c FROM images").fetchone()["c"],
        }


def _row_to_dict(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    d = dict(row)
    for k in ("ai_data_json", "discogs_data_json"):
        v = d.get(k)
        if isinstance(v, str) and v:
            try:
                d[k] = json.loads(v)
            except (ValueError, TypeError):
                d[k] = {}
        else:
            d[k] = {}
    return d
