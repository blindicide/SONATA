import json
import threading
import time
from dataclasses import replace

import pytest

from sonata.database import Database
from sonata.engine import Engine
from sonata.models import DownloadOptions, format_selector, scan_summary
from sonata.paths import AppPaths


def test_default_is_highest_resolution_and_mp4(tmp_path):
    options = DownloadOptions(str(tmp_path))
    assert options.height == 0
    assert options.container == "mp4"
    assert options.metadata
    options = replace(options, height=262).validate()
    assert "[height=262]" in format_selector(options)
    assert "bestaudio[acodec^=mp4a]" in format_selector(options)


def test_scan_uses_real_resolutions_and_omits_signed_urls():
    info = {
        "id": "test",
        "title": "Test",
        "extractor_key": "Youtube",
        "formats": [
            {"height": 1080, "width": 1920, "fps": 30, "vcodec": "avc1", "url": "https://private/signed"},
            {"height": 262, "width": 352, "vcodec": "avc1"},
            {"height": 1080, "width": 1920, "fps": 60, "vcodec": "av01"},
            {"height": 4320, "vcodec": "av01", "has_drm": True},
            {"height": 2160, "protocol": "mhtml", "vcodec": "none"},
            {"height": None, "vcodec": "none", "acodec": "mp4a"},
        ],
    }
    result = scan_summary(info)
    assert [r["height"] for r in result["resolutions"]] == [1080, 262]
    assert result["resolutions"][0]["fps"] == 60
    assert "private" not in json.dumps(result)


def wait_for(engine, predicate):
    deadline = time.monotonic() + 6
    while time.monotonic() < deadline:
        engine.tick()
        if predicate():
            return
        time.sleep(0.02)
    pytest.fail("Engine state did not arrive")


def test_each_video_scans_without_downloading_and_has_its_own_selection(tmp_path, monkeypatch):
    db = Database(tmp_path / "library.db")
    options = DownloadOptions(str(tmp_path / "downloads"))
    first = db.add("https://example.org/one", options)
    second = db.add("https://example.org/two", options)
    engine = Engine(db, AppPaths(tmp_path, tmp_path))
    monkeypatch.setattr("sonata.engine.base_command", lambda _paths: ["mock-downloader"])

    def stream(job_id, command, callback):
        height = 1080 if job_id == first else 2160
        callback(
            json.dumps(
                {
                    "id": str(job_id),
                    "title": str(job_id),
                    "formats": [{"height": h, "width": h * 2, "vcodec": "avc1"} for h in (height, 262)],
                }
            )
        )

    monkeypatch.setattr(engine, "_stream", stream)
    downloads = []

    def download(job):
        downloads.append(job["id"])
        db.update(job["id"], state="completed")
        engine._finish(job["id"])

    monkeypatch.setattr(engine, "_download", download)
    try:
        wait_for(
            engine,
            lambda: all(
                db.job(j)["scan_state"] == "ready" and j not in engine.running for j in (first, second)
            ),
        )
        assert not downloads
        assert json.loads(db.job(first)["options"])["height"] == 1080
        assert json.loads(db.job(second)["options"])["height"] == 2160
        engine.set_resolution(first, 262)
        assert json.loads(db.job(first)["options"])["height"] == 262
        assert json.loads(db.job(second)["options"])["height"] == 2160
        with pytest.raises(ValueError):
            engine.set_resolution(first, 720)
        engine.start([first])
        wait_for(engine, lambda: db.job(first)["state"] == "completed")
        assert downloads == [first]
        assert db.job(second)["auto_start"] == 0
    finally:
        engine.shutdown()


def test_playlist_start_and_pause_include_child_jobs(tmp_path):
    db = Database(tmp_path / "library.db")
    options = DownloadOptions(str(tmp_path))
    parent = db.add("https://example.org/list", options, auto_start=True)
    engine = Engine(db, AppPaths(tmp_path, tmp_path))
    engine.running[parent] = threading.Event()
    engine._expand(
        parent, {"entries": [{"url": "https://example.org/item"}]}, options, "https://example.org/list"
    )
    child = next(j for j in db.jobs() if j["parent_id"] == parent)
    assert child["auto_start"] == 1
    engine.stop([parent])
    assert db.job(child["id"])["state"] == "paused"
    assert db.job(child["id"])["auto_start"] == 0
    engine.running.clear()
    engine.shutdown()


def test_database_upgrade_preserves_jobs_and_adds_scan_fields(tmp_path):
    import sqlite3

    path = tmp_path / "old.db"
    db = Database(path)
    job = db.add("https://example.org/video", DownloadOptions(str(tmp_path), container="mkv"))
    with sqlite3.connect(path) as connection:
        for column in ("scan_state", "scan", "auto_start"):
            connection.execute(f"ALTER TABLE jobs DROP COLUMN {column}")
        connection.execute("PRAGMA user_version=1")
    upgraded = Database(path)
    assert upgraded.job(job)["scan_state"] == "pending"
    assert json.loads(upgraded.job(job)["options"])["container"] == "mkv"
    with upgraded.connect() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 2
