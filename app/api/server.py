"""FastAPI server: routes, static, templates and dependency wiring."""
from __future__ import annotations

import json
import logging
import mimetypes
import os
import shutil
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, Request, UploadFile, File
from fastapi.responses import (
    FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response, StreamingResponse,
)
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.config import DEFAULT_HOST, DEFAULT_PORT, Settings, user_data_dir
from app.db.repository import Repo, Record
from app.db.schema import SCHEMA_VERSION
from app.services.exports import (
    make_backup, records_to_csv, records_to_excel, records_to_html, records_to_json,
    restore_backup,
)
from app.services.grouping import (
    IMAGE_EXTS, group_images, grouping_warning, list_images, safe_filename,
)
from app.services.jobs import JobManager
from app.services.thumbnails import make_thumbnail, make_test_image, read_dimensions

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "templates"
STATIC = ROOT / "static"


# ----------------------- App factory -----------------------

def create_app() -> FastAPI:
    data_dir = user_data_dir()
    db_path = data_dir / "vinyl.sqlite3"
    images_dir = data_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    settings = Settings.load()
    repo = Repo(db_path)
    jobs = JobManager(repo)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            yield
        finally:
            repo.close()

    app = FastAPI(title="Vinyl Catalog v3", version=__version__, lifespan=lifespan)

    app.state.repo = repo
    app.state.jobs = jobs
    app.state.settings = settings
    app.state.data_dir = data_dir
    app.state.images_dir = images_dir
    app.state.db_path = db_path

    if STATIC.exists():
        app.mount("/static", StaticFiles(directory=str(STATIC)), name="static")

    @app.get("/", response_class=HTMLResponse)
    def index() -> HTMLResponse:
        return HTMLResponse((TEMPLATES / "index.html").read_text(encoding="utf-8"))

    # ----- folder browser -----
    @app.get("/api/fs/list")
    def fs_list(path: str = Query("")) -> JSONResponse:
        p = Path(path).expanduser().resolve() if path else Path("/").resolve()
        if not p.is_dir():
            raise HTTPException(404, "Not a directory")
        items: List[Dict[str, Any]] = []
        # Always include parent + root at the top
        items.append({"name": "..", "path": str(p.parent), "is_dir": True, "image_count": 0})
        try:
            for child in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower())):
                if child.name.startswith("."):
                    continue
                ic = 0
                if child.is_dir():
                    try:
                        ic = sum(1 for f in child.iterdir()
                                 if f.is_file() and f.suffix.lower() in IMAGE_EXTS)
                    except OSError:
                        ic = 0
                items.append({
                    "name": child.name, "path": str(child),
                    "is_dir": child.is_dir(),
                    "image_count": ic,
                })
        except PermissionError:
            raise HTTPException(403, "Permission denied")
        return JSONResponse({"path": str(p), "items": items})

    # ----- import -----
    @app.post("/api/import/start")
    def import_start(payload: Dict[str, Any]) -> JSONResponse:
        folder = Path(payload.get("folder") or "").expanduser().resolve()
        images_per_record = int(payload.get("images_per_record") or 2)
        roles = payload.get("roles") or ["front", "back", "label_a", "label_b", "inner_sleeve", "other"]
        if not folder.is_dir():
            raise HTTPException(400, "Folder not found")
        files = list_images(folder)
        groups = group_images(files, images_per_record)
        warning = grouping_warning(groups, images_per_record)

        def runner(state, is_cancelled):
            total = len(groups)
            state.total = total
            state.status_text = f"Importing {total} records from {folder}"
            for idx, group in enumerate(groups):
                if is_cancelled():
                    return
                state.current = group.files[0].name if group.files else ""
                rec = Record(id=repo.make_id(repo.conn) if hasattr(repo, "make_id") else _gen_id(repo))
                rec.status = "new"
                repo.insert_record(rec)
                # Copy files and create thumbs
                for pos, (path, role) in enumerate(zip(group.files, group.roles), start=1):
                    if is_cancelled():
                        return
                    target = images_dir / rec.id / safe_filename(path.name)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(path, target)
                    thumb = target.parent / ("thumb_" + safe_filename(path.name))
                    thumb = make_thumbnail(target, thumb)
                    w, h = read_dimensions(target)
                    repo.add_image(
                        record_id=rec.id, role=role, position=pos,
                        original_filename=path.name, stored_path=str(target),
                        thumb_path=str(thumb) if thumb else None,
                        width=w, height=h,
                        size_bytes=target.stat().st_size if target.exists() else None,
                    )
                jobs.progress(state, current=state.current, done=idx + 1, total=total)

        job_id = jobs.start("import", {"folder": str(folder),
                                        "images_per_record": images_per_record},
                            runner)
        return JSONResponse({"job_id": job_id, "record_count": len(groups),
                             "warning": warning})

    # ----- jobs -----
    @app.get("/api/jobs/{job_id}")
    def job_get(job_id: int) -> JSONResponse:
        row = repo.get_job(job_id)
        if not row:
            raise HTTPException(404, "Job not found")
        return JSONResponse({"job": row})

    @app.post("/api/jobs/{job_id}/cancel")
    def job_cancel(job_id: int) -> JSONResponse:
        ok = jobs.cancel(job_id)
        return JSONResponse({"cancelled": ok})

    @app.get("/api/jobs")
    def job_list() -> JSONResponse:
        return JSONResponse({"jobs": repo.list_jobs(limit=50)})

    # ----- records -----
    @app.get("/api/records")
    def records_list(
        search: Optional[str] = None, status: Optional[str] = None,
        confidence: Optional[str] = None, has_ai: Optional[bool] = None,
        has_discogs: Optional[bool] = None, year_from: Optional[int] = None,
        year_to: Optional[int] = None, genre: Optional[str] = None,
        label: Optional[str] = None, sort: str = "updated_desc",
        limit: int = 500,
    ) -> JSONResponse:
        rows = repo.list_records(
            search=search, status=status, confidence=confidence,
            has_ai=has_ai, has_discogs=has_discogs,
            year_from=year_from, year_to=year_to, genre=genre, label=label,
            sort=sort, limit=limit,
        )
        return JSONResponse({"records": rows, "count": len(rows)})

    @app.get("/api/records/{rec_id}")
    def record_get(rec_id: str) -> JSONResponse:
        rec = repo.get_record(rec_id)
        if not rec:
            raise HTTPException(404, "Record not found")
        rec["images"] = repo.get_images(rec_id)
        return JSONResponse({"record": rec})

    @app.patch("/api/records/{rec_id}")
    def record_update(rec_id: str, payload: Dict[str, Any]) -> JSONResponse:
        if not repo.get_record(rec_id):
            raise HTTPException(404, "Record not found")
        repo.update_record(rec_id, payload)
        return JSONResponse({"ok": True})

    @app.delete("/api/records/{rec_id}")
    def record_delete(rec_id: str) -> JSONResponse:
        repo.delete_record(rec_id)
        return JSONResponse({"ok": True})

    @app.post("/api/records/{rec_id}/select_discogs")
    def record_select_discogs(rec_id: str, payload: Dict[str, Any]) -> JSONResponse:
        """Manually pick a Discogs candidate for a record."""
        cand = payload.get("candidate") or {}
        price = (cand.get("price_suggestions") or [])
        from app.discogs.scoring import suggest_price_eur
        ps = suggest_price_eur(price).to_dict()
        rec = repo.get_record(rec_id)
        if not rec:
            raise HTTPException(404, "Record not found")
        repo.update_record(rec_id, {
            "discogs_data_json": cand,
            "discogs_confidence": "high",
            "discogs_reason": "User-selected candidate",
            "price_low_eur": ps["low"],
            "price_high_eur": ps["high"],
            "price_eur": ps["median"] or ps["low"],
            "status": _next_status(rec.get("status"), "discogs_done"),
        })
        return JSONResponse({"ok": True})

    # ----- AI / Discogs settings -----
    @app.get("/api/settings")
    def settings_get() -> JSONResponse:
        s = app.state.settings
        return JSONResponse({
            "ai_provider": s.ai_provider,
            "ai_model": s.ai_model,
            "ai_api_key_masked": _mask(s.ai_api_key),
            "discogs_token_masked": _mask(s.discogs_token),
            "discogs_user_agent": s.discogs_user_agent,
            "host": s.host, "port": s.port,
        })

    @app.post("/api/settings")
    def settings_post(payload: Dict[str, Any]) -> JSONResponse:
        s = app.state.settings
        for k in ("ai_provider", "ai_model", "discogs_user_agent", "host"):
            if k in payload and payload[k] is not None:
                setattr(s, k, payload[k])
        if "port" in payload and payload["port"] is not None:
            try:
                s.port = int(payload["port"])
            except (TypeError, ValueError):
                pass
        # Only overwrite secrets if explicitly provided (and non-empty)
        for k in ("ai_api_key", "discogs_token"):
            if k in payload and payload[k]:
                setattr(s, k, payload[k])
        s.save()
        return JSONResponse({"ok": True})

    @app.post("/api/settings/test_ai")
    def test_ai() -> JSONResponse:
        s = app.state.settings
        if not s.ai_api_key:
            return JSONResponse({"ok": False, "error": "No API key set"}, status_code=400)
        # We cannot live-test; verify settings look sane.
        return JSONResponse({"ok": True, "message": "API key present. Live test requires network."})

    @app.post("/api/settings/test_discogs")
    def test_discogs() -> JSONResponse:
        s = app.state.settings
        if not s.discogs_token:
            return JSONResponse({"ok": False, "error": "No Discogs token set"}, status_code=400)
        return JSONResponse({"ok": True, "message": "Token present. Live test requires network."})

    # ----- enrich with AI -----
    @app.post("/api/enrich/ai/start")
    def enrich_ai_start(payload: Dict[str, Any]) -> JSONResponse:
        scope = payload.get("scope", "only_new")
        ids = payload.get("record_ids") or []
        s = app.state.settings
        records = _select_records_for_scope(repo, scope, ids)
        if scope == "all":
            logger.warning("AI enrichment scope=all on %d records", len(records))

        def runner(state, is_cancelled):
            total = len(records)
            state.total = total
            state.status_text = f"AI enrichment: {total} records"
            from app.ai.providers import call_ai
            for idx, rec in enumerate(records):
                if is_cancelled():
                    return
                images = repo.get_images(rec["id"])
                paths = [Path(im["stored_path"]) for im in images]
                roles = [im["role"] for im in images]
                state.current = rec.get("title") or rec["id"]
                try:
                    result = call_ai(s.ai_provider, s.ai_api_key, s.ai_model, paths, roles)
                    repo.update_record(rec["id"], {
                        "ai_data_json": result,
                        "ai_confidence": result.get("confidence"),
                        "ai_reason": result.get("reason"),
                        "status": _next_status(rec.get("status"), "ai_done"),
                        **{k: result.get(k) for k in (
                            "artist", "title", "label", "catalog_number",
                            "barcode", "year", "genre", "format", "country",
                            "notes",
                        ) if result.get(k) is not None},
                    })
                except Exception as exc:
                    logger.warning("AI call failed for %s: %s", rec["id"], exc)
                    state.error = str(exc)
                jobs.progress(state, current=state.current, done=idx + 1, total=total)

        job_id = jobs.start("ai_enrich", {"scope": scope, "count": len(records)}, runner)
        return JSONResponse({"job_id": job_id, "record_count": len(records)})

    # ----- enrich with Discogs -----
    @app.post("/api/enrich/discogs/start")
    def enrich_discogs_start(payload: Dict[str, Any]) -> JSONResponse:
        scope = payload.get("scope", "only_new")
        ids = payload.get("record_ids") or []
        s = app.state.settings
        records = _select_records_for_scope(repo, scope, ids)

        def runner(state, is_cancelled):
            total = len(records)
            state.total = total
            state.status_text = f"Discogs enrichment: {total} records"
            from app.discogs.client import DiscogsClient
            client = DiscogsClient(s.discogs_token, s.discogs_user_agent,
                                   cache_repo=repo)
            for idx, rec in enumerate(records):
                if is_cancelled():
                    return
                state.current = rec.get("title") or rec["id"]
                try:
                    result = client.enrich(rec.get("ai_data_json") or {
                        "artist": rec.get("artist"),
                        "title": rec.get("title"),
                        "catalog_number": rec.get("catalog_number"),
                        "barcode": rec.get("barcode"),
                    })
                    sel = result.get("selected") or {}
                    prices = result.get("prices") or {}
                    repo.update_record(rec["id"], {
                        "discogs_data_json": {
                            "selected": sel,
                            "candidates": result.get("candidates", []),
                        },
                        "discogs_confidence": result.get("confidence"),
                        "discogs_reason": result.get("reason"),
                        "price_low_eur": prices.get("low"),
                        "price_high_eur": prices.get("high"),
                        "price_eur": prices.get("median"),
                        "status": _next_status(rec.get("status"), "discogs_done"),
                    })
                except Exception as exc:
                    logger.warning("Discogs enrich failed for %s: %s", rec["id"], exc)
                jobs.progress(state, current=state.current, done=idx + 1, total=total)

        job_id = jobs.start("discogs_enrich", {"scope": scope, "count": len(records)}, runner)
        return JSONResponse({"job_id": job_id, "record_count": len(records)})

    # ----- exports -----
    @app.get("/api/export")
    def export(fmt: str = "csv"):
        rows = repo.all_records()
        if fmt == "csv":
            data = records_to_csv(rows)
            return Response(data, media_type="text/csv",
                            headers={"Content-Disposition": "attachment; filename=vinyl.csv"})
        if fmt == "xlsx":
            data = records_to_excel(rows)
            return Response(data,
                            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            headers={"Content-Disposition": "attachment; filename=vinyl.xlsx"})
        if fmt == "json":
            data = records_to_json(rows)
            return Response(data, media_type="application/json",
                            headers={"Content-Disposition": "attachment; filename=vinyl.json"})
        if fmt == "html":
            data = records_to_html(rows)
            return Response(data, media_type="text/html",
                            headers={"Content-Disposition": "attachment; filename=vinyl.html"})
        raise HTTPException(400, "Unknown export format")

    # ----- database backup -----
    @app.get("/api/db/backup")
    def db_backup() -> Response:
        data = make_backup(app.state.db_path, app.state.images_dir)
        return Response(data, media_type="application/zip",
                        headers={"Content-Disposition":
                                 f'attachment; filename="vinyl-catalog-backup-{time.strftime("%Y%m%d-%H%M%S")}.zip"'})

    @app.post("/api/db/restore")
    async def db_restore(file: UploadFile = File(...)) -> JSONResponse:
        nonlocal repo, jobs
        data = await file.read()
        # Close SQLite before replacing the database (required on Windows).
        repo.close()
        try:
            info = restore_backup(data, app.state.db_path, app.state.images_dir)
        except Exception as exc:
            # Keep the running app usable if restore validation fails.
            repo = Repo(app.state.db_path)
            jobs = JobManager(repo)
            app.state.repo = repo
            app.state.jobs = jobs
            raise HTTPException(400, f"Restore failed: {exc}")
        repo = Repo(app.state.db_path)
        jobs = JobManager(repo)
        app.state.repo = repo
        app.state.jobs = jobs
        return JSONResponse({"ok": True, "info": info})

    @app.get("/api/meta")
    def meta() -> JSONResponse:
        m = repo.meta()
        return JSONResponse({**m, "app_version": __version__,
                             "data_dir": str(app.state.data_dir)})

    @app.get("/images/{rec_id}/{path:path}")
    def image_serve(rec_id: str, path: str) -> FileResponse:
        p = (app.state.images_dir / rec_id / path).resolve()
        if not str(p).startswith(str(app.state.images_dir.resolve())):
            raise HTTPException(403, "Forbidden")
        if not p.exists():
            raise HTTPException(404, "Not found")
        return FileResponse(str(p))

    @app.get("/healthz")
    def healthz() -> JSONResponse:
        return JSONResponse({"ok": True, "version": __version__})

    @app.post("/api/test/dummy-import")
    def test_dummy_import() -> JSONResponse:
        """Generate 12 dummy images (2 per record, 6 records) and import them.

        Used by automated verification; harmless in production.
        """
        from app.services.grouping import IMAGE_EXTS
        scratch = app.state.data_dir / "test_dummy"
        scratch.mkdir(parents=True, exist_ok=True)
        # Clean previous
        for p in scratch.iterdir():
            if p.is_file():
                p.unlink()
        labels = [
            ("The Beatles", "Abbey Road"),
            ("Pink Floyd", "The Dark Side of the Moon"),
            ("Led Zeppelin", "IV"),
            ("David Bowie", "Ziggy Stardust"),
            ("Joy Division", "Unknown Pleasures"),
            ("Miles Davis", "Kind of Blue"),
        ]
        files = []
        for i, (artist, title) in enumerate(labels, start=1):
            for j in range(2):
                f = scratch / f"rec{i:02d}_{j+1}.jpg"
                make_test_image(f, label=f"{artist[:14]} - {title[:14]}")
                files.append(str(f))
        payload = {"folder": str(scratch), "images_per_record": 2}
        return import_start(payload)

    return app


def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 6:
        return "*" * len(value)
    return value[:2] + "*" * (len(value) - 4) + value[-2:]


def _gen_id(repo: Repo) -> str:
    """Wrapper that defers to the repository's id generator."""
    from app.db.repository import make_record_id
    return make_record_id(repo.conn)


def _select_records_for_scope(repo: Repo, scope: str, ids: List[str]) -> List[Dict[str, Any]]:
    if scope == "all":
        return repo.all_records()
    if scope == "only_new":
        rows = []
        for r in repo.all_records():
            has_ai = bool(r.get("ai_data_json"))
            if not has_ai:
                rows.append(r)
        return rows
    if scope == "selected":
        return [r for r in (repo.get_record(i) for i in ids) if r]
    return []


def _next_status(current: Optional[str], kind: str) -> str:
    """Compute new record status string after enrichment step ``kind``."""
    current = current or "new"
    if kind == "ai_done":
        if current in ("discogs_done", "both"):
            return "both"
        return "ai_done"
    if kind == "discogs_done":
        if current in ("ai_done", "both"):
            return "both"
        return "discogs_done"
    return current


app = create_app()


def main() -> None:
    import uvicorn  # type: ignore
    settings = Settings.load()
    uvicorn.run("app.api.server:app", host=settings.host,
                port=settings.port, log_level=settings.log_level.lower())


if __name__ == "__main__":
    main()
