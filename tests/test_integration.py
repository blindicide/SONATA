"""Real bundled-tool integration. Enable with SONATA_INTEGRATION=1."""

import functools
import http.server
import json
import os
import subprocess
import threading
import time
from pathlib import Path

import pytest

from sonata.database import Database
from sonata.engine import Engine, spawn_options
from sonata.models import DownloadOptions
from sonata.paths import AppPaths

pytestmark = pytest.mark.skipif(
    os.environ.get("SONATA_INTEGRATION") != "1", reason="requires bundled media tools"
)


def test_real_download_audio_duplicate_and_export(tmp_path):
    vendor = Path(__file__).resolve().parents[1] / "vendor"
    paths = AppPaths(tmp_path / "profile", vendor)
    root = tmp_path / "server"
    root.mkdir()
    subprocess.run(
        [
            str(paths.tool("ffmpeg")),
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=320x180:r=25",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=44100",
            "-t",
            "2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            str(root / "fixture.mp4"),
        ],
        check=True,
        timeout=30,
        **spawn_options(),
    )
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    db = Database(paths.data / "library.db")
    events = []
    engine = Engine(db, paths, lambda kind, value: events.append((kind, value)))

    def download(options):
        job = db.add(f"http://127.0.0.1:{server.server_port}/fixture.mp4", options)
        engine.start([job])
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            engine.tick()
            state = db.job(job)["state"]
            if state in ("completed", "failed", "skipped"):
                assert state != "failed", (db.job(job)["error"], events)
                return state
            time.sleep(0.1)
        pytest.fail("Download timed out")

    try:
        options = DownloadOptions(str(tmp_path / "downloads"), collection="Integration")
        assert download(options) == "completed"
        record = db.history()[0]
        files = json.loads(record["files"])
        assert any(Path(p).suffix == ".mkv" for p in files)
        assert download(options) == "skipped"
        # Remove the original to exercise an actual audio extraction on the same media ID.
        for filename in files:
            Path(filename).unlink()
        from dataclasses import replace

        assert download(replace(options, mode="audio", audio_codec="mp3")) == "completed"
        assert any(Path(p).suffix == ".mp3" for p in json.loads(db.history()[0]["files"]))
        from sonata.archive import export_collection

        assert export_collection(db.history(), tmp_path / "integration.tar.gz") >= 1
    finally:
        engine.shutdown()
        server.shutdown()
        server.server_close()
