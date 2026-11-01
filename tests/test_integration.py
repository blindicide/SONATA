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


def test_pause_resume_uses_http_byte_ranges(tmp_path):
    vendor = Path(__file__).resolve().parents[1] / "vendor"
    paths = AppPaths(tmp_path / "profile", vendor)
    media = tmp_path / "fixture.mp4"
    subprocess.run(
        [
            str(paths.tool("ffmpeg")),
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=640x360:rate=25",
            "-t",
            "6",
            "-c:v",
            "mpeg4",
            "-q:v",
            "2",
            str(media),
        ],
        check=True,
        timeout=30,
        **spawn_options(),
    )
    payload = media.read_bytes()
    ranges = []

    class RangeHandler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            header = self.headers.get("Range", "")
            start = int(header.removeprefix("bytes=").partition("-")[0]) if header else 0
            ranges.append(start)
            self.send_response(206 if header else 200)
            self.send_header("Content-Type", "video/mp4")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(len(payload) - start))
            if header:
                self.send_header("Content-Range", f"bytes {start}-{len(payload) - 1}/{len(payload)}")
            self.end_headers()
            try:
                for position in range(start, len(payload), 16 * 1024):
                    self.wfile.write(payload[position : position + 16 * 1024])
            except (ConnectionResetError, BrokenPipeError, ConnectionAbortedError):
                pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), RangeHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    db = Database(paths.data / "library.db")
    engine = Engine(db, paths)
    options = DownloadOptions(str(tmp_path / "downloads"), container="mp4", metadata=False, rate_kib=128)
    job = db.add(f"http://127.0.0.1:{server.server_port}/fixture.mp4", options)

    def wait_for(condition, timeout=60):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            engine.tick()
            assert db.job(job)["state"] != "failed", db.job(job)["error"]
            if condition():
                return
            time.sleep(0.1)
        pytest.fail("Transfer state did not arrive before the deadline")

    try:
        engine.start([job])
        wait_for(lambda: any(p.stat().st_size > 32 * 1024 for p in options.folder.glob("*.part")))
        engine.stop([job])
        wait_for(lambda: job not in engine.running, timeout=15)
        assert db.job(job)["state"] == "paused"
        assert any(p.stat().st_size < len(payload) for p in options.folder.glob("*.part"))
        engine.start([job])
        wait_for(lambda: db.job(job)["state"] == "completed")
        assert any(start > 0 for start in ranges), "Resume must issue a nonzero byte-range request"
        assert Path(json.loads(db.history()[0]["files"])[0]).read_bytes() == payload
    finally:
        engine.shutdown()
        server.shutdown()
        server.server_close()
