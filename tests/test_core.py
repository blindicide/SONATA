import hashlib
import json
import tarfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pytest

from sonata.archive import export_collection
from sonata.database import Database
from sonata.engine import Engine, download_command
from sonata.models import (
    DownloadOptions,
    format_selector,
    validate_collection,
    validate_template,
    validate_url,
)
from sonata.paths import AppPaths


@pytest.fixture
def db(tmp_path):
    return Database(tmp_path / "library.db")


@pytest.fixture
def options(tmp_path):
    return DownloadOptions(str(tmp_path / "media"), collection="Музыка")


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "javascript:alert(1)",
        "https://user:pass@host/a",
        "--exec=bad",
        "https://host/a\nb",
    ],
)
def test_reject_non_media_inputs(url):
    with pytest.raises(ValueError):
        validate_url(url)


@pytest.mark.parametrize("name", ["../outside", "..", "C:\\media", "CON", "name.", "hello/world"])
def test_collection_stays_in_destination(name):
    with pytest.raises(ValueError):
        validate_collection(name)


@pytest.mark.parametrize(
    "template", ["../%(id)s.%(ext)s", "%(title)s.%(ext)s", "%(id)s.txt", "%(id)s\n.%(ext)s"]
)
def test_template_cannot_escape_or_collide(template):
    with pytest.raises(ValueError):
        validate_template(template)


def test_constraints_apply_to_fallback(options):
    selector = format_selector(replace(options, height=4320, video_codec="av1"))
    assert all("height<=?4320" in branch and "vcodec^=av01" in branch for branch in selector.split("/"))
    assert format_selector(replace(options, mode="audio")) == "bestaudio/best"


def test_arguments_are_not_shell_commands(tmp_path, options):
    paths = AppPaths(tmp_path, tmp_path / "vendor")
    paths.vendor.mkdir()
    import sys

    for name in ("yt-dlp", "ffmpeg", "deno"):
        (paths.vendor / (name + (".exe" if sys.platform == "win32" else ""))).touch()
    url = "https://example.org/video?x=$(bad)&a=b"
    command = download_command(paths, url, replace(options, mode="audio", rate_kib=100))
    assert command[-2:] == ["--", url]
    assert command[command.index("--limit-rate") + 1] == "102400"
    assert "--extract-audio" in command


def test_recovery_never_starts_transfers(db, options):
    jobs = [db.add(f"https://example.org/{i}", options) for i in range(5)]
    for job, state in zip(jobs, ("resolving", "downloading", "processing", "queued", "completed")):
        db.update(job, state=state)
    db.recover()
    assert [db.job(job)["state"] for job in jobs] == ["paused"] * 4 + ["completed"]


def test_only_one_worker_can_reserve_media(db, options):
    jobs = [db.add(f"https://example.org/{i}", options) for i in range(8)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        claims = list(pool.map(lambda job: db.claim("youtube:test", job), jobs))
    assert claims.count(True) == 1


def completed_record(db, options):
    options.folder.mkdir(parents=True)
    path = options.folder / "Тест [id].mp4"
    path.write_bytes(b"test media\x00" * 100)
    job = db.add("https://example.org/media", options)
    assert db.claim("generic:id", job)
    db.complete(job, "generic:id", "Тест", [path], options.folder, options.collection)
    return path, db.history()[0]


def test_duplicate_skip_and_missing_file_redownload(db, options):
    path, record = completed_record(db, options)
    assert not db.claim(record["media_key"], 99)
    path.unlink()
    assert db.claim(record["media_key"], 99)


def test_archive_contains_manifest_and_verified_media(db, options, tmp_path):
    path, record = completed_record(db, options)
    target = tmp_path / "collection.tar.gz"
    assert export_collection([record], target) == 1
    with tarfile.open(target) as archive:
        manifest = json.load(archive.extractfile("manifest.json"))
        for name, checksum in manifest["sha256"].items():
            assert hashlib.sha256(archive.extractfile(name).read()).hexdigest() == checksum
        assert all(
            not Path(name).is_absolute() and ".." not in Path(name).parts for name in archive.getnames()
        )
    assert path.exists()


def test_archive_failure_preserves_previous_export(db, options, tmp_path):
    path, record = completed_record(db, options)
    target = tmp_path / "saved.tar"
    target.write_bytes(b"previous export")
    path.unlink()
    with pytest.raises(ValueError):
        export_collection([record], target)
    assert target.read_bytes() == b"previous export"


def test_archive_rejects_path_outside_collection(db, options, tmp_path):
    _, record = completed_record(db, options)
    outside = tmp_path / "private.txt"
    outside.write_text("outside")
    record["files"] = json.dumps([str(outside)])
    with pytest.raises(ValueError):
        export_collection([record], tmp_path / "out.tar")


def test_playlist_expansion_is_repeatable_and_flattens_nested_entries(db, options, tmp_path):
    job = db.add("https://example.org/channel", options)
    engine = Engine(db, AppPaths(tmp_path, tmp_path))
    import threading

    engine.running[job] = threading.Event()
    info = {
        "entries": [
            {"entries": [{"url": "https://example.org/1", "title": "One"}, {"url": "https://example.org/2"}]},
            None,
            {"url": "https://example.org/1"},
        ]
    }
    assert engine._expand(job, info, options, "https://example.org/channel") == 2
    assert engine._expand(job, info, options, "https://example.org/channel") == 2
    assert len(db.jobs()) == 3
    engine.running.clear()
    engine.shutdown()


def test_history_search_treats_wildcards_literally(db, options):
    completed_record(db, options)
    assert len(db.history("Тест")) == 1
    assert db.history("%") == []
