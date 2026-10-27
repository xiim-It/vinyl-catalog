"""Unit tests for grouping, cleaning, scoring and backup roundtrip."""
import json, sys, tempfile, zipfile, io
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.cleaning import clean_str, clean_int, clean_float, clean_price_eur, merge_keep_existing
from app.services.grouping import group_images, grouping_warning, list_images
from app.discogs.scoring import similarity, score_candidate, rank_candidates, auto_select, suggest_price_eur, AUTO_THRESHOLD


def test_cleaning_strings():
    for v in ["", "null", "None", "N/A", "?", "unknown", "  -  ", "   "]:
        assert clean_str(v) is None, f"{v!r}"
    assert clean_str("Hello") == "Hello"
    assert clean_str(42) == "42"
    assert clean_str(None) is None
    print("clean_str: OK")


def test_cleaning_int_float():
    assert clean_int("1979") == 1979
    assert clean_int("Track 12") == 12
    assert clean_int("n/a") is None
    assert clean_int(None) is None
    assert clean_float("12.50") == 12.5
    assert clean_float("12,50") == 12.5
    assert clean_price_eur("€12,50") == 12.5
    assert clean_price_eur("-") is None
    assert clean_price_eur(0) == 0  # explicit zero is preserved
    print("clean_int/float/price: OK")


def test_merge_keep_existing():
    assert merge_keep_existing("a", None) == "a"
    assert merge_keep_existing("a", "") == "a"
    assert merge_keep_existing("a", "B") == "B"
    assert merge_keep_existing(0, None) == 0
    assert merge_keep_existing(None, 7) == 7
    print("merge_keep_existing: OK")


def test_grouping():
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        for i in range(7):
            (d / f"img_{i:02d}.jpg").write_bytes(b"x")
        files = list_images(d)
        groups = group_images(files, images_per_record=2)
        assert len(groups) == 4  # 2,2,2,1
        assert len(groups[-1].files) == 1
        warn = grouping_warning(groups, expected=2)
        assert warn is not None and "Trailing group" in warn
        roles = [g.roles for g in groups]
        # First image gets "front" by default position
        assert roles[0][0] == "front"
    print("grouping: OK")


def test_similarity():
    assert similarity("The Beatles", "Beatles, The") > 50
    assert similarity("Pink Floyd", "ABBA") < 30
    assert similarity(None, "x") == 0.0
    print("similarity: OK")


def test_scoring_and_auto_select():
    ai = {"artist": "Pink Floyd", "title": "The Dark Side of the Moon", "catalog_number": "SHVL 804"}
    candidates = [
        {"id": 1, "artist": "Pink Floyd", "title": "The Dark Side of the Moon", "label": "Harvest", "catalog_number": "SHVL 804", "format": "LP, Album"},
        {"id": 2, "artist": "ABBA", "title": "Greatest Hits", "label": "Polar", "catalog_number": "POLS 302", "format": "LP"},
    ]
    ranked = rank_candidates(ai, candidates)
    assert ranked[0]["id"] == 1
    assert ranked[0]["score"] >= AUTO_THRESHOLD
    selected, conf, score = auto_select(ai, candidates)
    assert selected is not None and conf == "high"
    # Low confidence case
    ai2 = {"artist": "ZZZZ", "title": "QQQQ"}
    selected2, conf2, score2 = auto_select(ai2, candidates)
    assert conf2 in ("unknown", "low")
    print("scoring: OK")


def test_price_suggestion():
    ps = [{"currency": "EUR", "value": 10.0}, {"currency": "EUR", "value": 20.0}]
    out = suggest_price_eur(ps)
    assert out.low_eur == 10.0 and out.high_eur == 30.0 and out.median_eur == 15.0
    out2 = suggest_price_eur([])
    assert out2.low_eur is None and out2.high_eur is None
    out3 = suggest_price_eur([{"currency": "USD", "value": 10.0}])
    assert out3.low_eur is not None
    print("price: OK")


def test_backup_roundtrip():
    from app.db.repository import Repo, Record
    from app.services.exports import make_backup, restore_backup
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        db = d / "v.sqlite3"
        imgs = d / "img"
        imgs.mkdir()
        # Create a tiny repo, write data, and close it before backup/cleanup.
        with Repo(db) as repo:
            repo.insert_record(Record(id="VC-BACKUP-TEST", artist="Test Artist"))
        # add a test image
        (imgs / "a.jpg").write_bytes(b"test")
        # add a file inside a record dir
        rec = imgs / "VC-000001"
        rec.mkdir()
        (rec / "x.jpg").write_bytes(b"data")
        z = make_backup(db, imgs)
        # restore to a new dir
        target = d / "restore"
        target.mkdir()
        info = restore_backup(z, target / "v2.sqlite3", target / "img2")
        assert info["schema_version"] == 3
        assert (target / "v2.sqlite3").exists()
        with Repo(target / "v2.sqlite3") as restored_repo:
            assert restored_repo.get_record("VC-BACKUP-TEST")["artist"] == "Test Artist"
        assert (target / "img2" / "a.jpg").exists()
        assert (target / "img2" / "VC-000001" / "x.jpg").exists()
    print("backup: OK")
