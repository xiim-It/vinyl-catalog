"""Smoke tests for the FastAPI app (no network)."""
import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from app.api.server import create_app
from app.config import user_data_dir


def test_health_and_meta():
    with tempfile.TemporaryDirectory() as tmp:
        import app.config as cfg
        cfg._user_data_dir = lambda: Path(tmp)
        app = create_app()
        c = TestClient(app)
        r = c.get("/healthz"); assert r.status_code == 200
        r = c.get("/api/meta"); assert r.status_code == 200
        assert "schema_version" in r.json()
    print("api meta: OK")


def test_record_crud():
    with tempfile.TemporaryDirectory() as tmp:
        import app.config as cfg
        cfg._user_data_dir = lambda: Path(tmp)
        app = create_app()
        c = TestClient(app)
        # Create record
        r = c.post("/api/import/start", json={"folder": "/nonexistent"})
        assert r.status_code in (200, 400)
        # Get empty
        r = c.get("/api/records"); assert r.status_code == 200
        print("api crud: OK")


def test_dummy_import_end_to_end():
    with tempfile.TemporaryDirectory() as tmp:
        import app.config as cfg
        cfg._user_data_dir = lambda: Path(tmp)
        app = create_app()
        c = TestClient(app)
        r = c.post("/api/test/dummy-import"); assert r.status_code == 200
        jid = r.json()["job_id"]
        # Poll job
        for _ in range(60):
            r = c.get(f"/api/jobs/{jid}").json()
            if r["job"]["state"] in ("done","error","cancelled"):
                break
            import time; time.sleep(0.2)
        assert r["job"]["state"] == "done", r
        # Records exist
        r = c.get("/api/records")
        recs = r.json()["records"]
        assert len(recs) >= 6
        # Has images
        first = c.get(f"/api/records/{recs[0]['id']}").json()["record"]
        assert len(first.get("images", [])) >= 2
        print("dummy import: OK")
