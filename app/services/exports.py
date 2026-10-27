"""Export utilities: CSV, Excel (openpyxl), JSON, printable HTML."""
from __future__ import annotations

import csv
import io
import json
import logging
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from app.services.cleaning import clean_price_eur, clean_str

logger = logging.getLogger(__name__)

CSV_COLUMNS = [
    ("id", "ID"),
    ("artist", "Artist"),
    ("title", "Title"),
    ("label", "Label"),
    ("catalog_number", "Catalog Number"),
    ("barcode", "Barcode"),
    ("year", "Year"),
    ("genre", "Genre"),
    ("format", "Format"),
    ("country", "Country"),
    ("price_eur", "Price (EUR)"),
    ("price_low_eur", "Price Low (EUR)"),
    ("price_high_eur", "Price High (EUR)"),
    ("ai_confidence", "AI Confidence"),
    ("discogs_confidence", "Discogs Confidence"),
    ("status", "Status"),
    ("notes", "Notes"),
    ("updated_at", "Updated At"),
]


def _flatten(rec: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, _ in CSV_COLUMNS:
        out[k] = rec.get(k)
    return out


def records_to_csv(records: Iterable[Dict[str, Any]]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([h for _, h in CSV_COLUMNS])
    for r in records:
        row = []
        for k, _ in CSV_COLUMNS:
            v = r.get(k)
            if isinstance(v, (dict, list)):
                v = json.dumps(v, ensure_ascii=False)
            row.append("" if v is None else v)
        writer.writerow(row)
    return buf.getvalue().encode("utf-8")


def records_to_excel(records: Iterable[Dict[str, Any]]) -> bytes:
    """Build an XLSX using openpyxl (pure-Python, works on ARM)."""
    try:
        from openpyxl import Workbook  # type: ignore
    except Exception as exc:
        raise RuntimeError("openpyxl is required for Excel export") from exc
    wb = Workbook()
    ws = wb.active
    ws.title = "Records"
    ws.append([h for _, h in CSV_COLUMNS])
    for r in records:
        ws.append([r.get(k) for k, _ in CSV_COLUMNS])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def records_to_json(records: Iterable[Dict[str, Any]]) -> bytes:
    return json.dumps(list(records), ensure_ascii=False, indent=2).encode("utf-8")


HTML_ROW_TPL = "<tr><td>{artist}</td><td>{title}</td><td>{label}</td><td>{year}</td><td>{price}</td></tr>"


def records_to_html(records: Iterable[Dict[str, Any]]) -> bytes:
    rows = []
    for r in records:
        rows.append(HTML_ROW_TPL.format(
            artist=clean_str(r.get("artist")) or "",
            title=clean_str(r.get("title")) or "",
            label=clean_str(r.get("label")) or "",
            year=r.get("year") or "",
            price=(f"{r['price_eur']:.2f} EUR" if r.get("price_eur") else ""),
        ))
    body = "\n".join(rows) if rows else "<tr><td colspan=5>No records</td></tr>"
    html = f"""<!doctype html><html><head><meta charset='utf-8'><title>Vinyl Catalog</title>
<style>body{{font-family:sans-serif}}table{{border-collapse:collapse;width:100%}}
td,th{{border:1px solid #ccc;padding:6px;text-align:left}}</style></head>
<body><h1>Vinyl Catalog</h1><table>
<thead><tr><th>Artist</th><th>Title</th><th>Label</th><th>Year</th><th>Price</th></tr></thead>
<tbody>{body}</tbody></table></body></html>"""
    return html.encode("utf-8")


# ----------------- Database backup / restore -----------------


def make_backup(db_path: Path, images_dir: Path, manifest_path: Optional[Path] = None) -> bytes:
    """Build a ZIP backup containing sqlite, images and a manifest."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if db_path.exists():
            zf.write(str(db_path), "data/vinyl.sqlite3")
        if images_dir.exists():
            for p in images_dir.rglob("*"):
                if p.is_file():
                    zf.write(str(p), f"images/{p.relative_to(images_dir)}")
        manifest = {
            "type": "vinyl-catalog-backup",
            "schema_version": 3,
            "created_at": __import__("time").strftime("%Y-%m-%dT%H:%M:%S"),
            "files": {
                "sqlite": "data/vinyl.sqlite3",
                "images_dir": "images",
            },
        }
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
    return buf.getvalue()


def restore_backup(zip_bytes: bytes, target_db: Path, target_images: Path) -> Dict[str, Any]:
    """Restore a backup ZIP into the given locations."""
    target_db.parent.mkdir(parents=True, exist_ok=True)
    target_images.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO(zip_bytes)
    manifest: Dict[str, Any] = {}
    with zipfile.ZipFile(buf) as zf:
        try:
            manifest = json.loads(zf.read("manifest.json"))
        except KeyError:
            manifest = {}
        # Validate manifest
        if manifest.get("type") != "vinyl-catalog-backup":
            raise ValueError("Not a Vinyl Catalog backup")
        # Restore sqlite
        sqlite_member = manifest.get("files", {}).get("sqlite", "data/vinyl.sqlite3")
        try:
            data = zf.read(sqlite_member)
            target_db.write_bytes(data)
        except KeyError:
            raise ValueError("Backup is missing sqlite file")
        # Restore images (skip files outside ``images/``)
        images_prefix = manifest.get("files", {}).get("images_dir", "images")
        for member in zf.namelist():
            if not member.startswith(images_prefix + "/"):
                continue
            rel = member[len(images_prefix) + 1 :]
            target = target_images / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "wb") as fh:
                fh.write(zf.read(member))
    return {
        "schema_version": manifest.get("schema_version"),
        "restored_to": str(target_db),
        "images_dir": str(target_images),
    }
