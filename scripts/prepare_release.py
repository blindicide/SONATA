"""Assemble verified Overture packages and preserve upstream source snapshots."""

from __future__ import annotations

import hashlib
import json
import shutil
import tarfile
import tempfile
import urllib.request
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PyInstaller.archive.readers import CArchiveReader

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "release-assets"
APP_COMMIT = "8181345f78359c56e2aa86deace76311484d892d"
BUILD_RUN = 41316533412
FFMPEG_COMMIT = "4811625b5f4e5aed528aed9225d0ca868a8e6e96"
FFMPEG_BUILD_COMMIT = "5031c6f1082414e53688d39e521849905071070d"
HEADERS = {"User-Agent": "SONATA-release/0.1.0"}

SOURCES = [
    (
        "Source-FFmpeg-4811625b5f.tar.gz",
        f"https://github.com/FFmpeg/FFmpeg/archive/{FFMPEG_COMMIT}.tar.gz",
        None,
    ),
    (
        "Source-FFmpeg-build-recipes.tar.gz",
        f"https://github.com/BtbN/FFmpeg-Builds/archive/{FFMPEG_BUILD_COMMIT}.tar.gz",
        None,
    ),
    (
        "Source-Qt-6.8.3.tar.xz",
        "https://download.qt.io/archive/qt/6.8/6.8.3/single/qt-everywhere-src-6.8.3.tar.xz",
        "cdd3a69967208276bb01af7ace7dba0ba53e679f886a4cbe624225c60fb73f2c",
    ),
    (
        "Source-PySide-Shiboken-6.8.3.tar.gz",
        "https://github.com/pyside/pyside-setup/archive/refs/tags/v6.8.3.tar.gz",
        None,
    ),
    (
        "Source-Python-3.12.10.tar.gz",
        "https://github.com/python/cpython/archive/refs/tags/v3.12.10.tar.gz",
        None,
    ),
    (
        "Source-Python-3.12.15.tar.gz",
        "https://github.com/python/cpython/archive/refs/tags/v3.12.15.tar.gz",
        None,
    ),
    (
        "Source-yt-dlp-2026.10.26.tar.gz",
        "https://github.com/yt-dlp/yt-dlp/archive/refs/tags/2026.10.26.tar.gz",
        None,
    ),
    ("Source-Deno-2.9.8.tar.gz", "https://github.com/denoland/deno/archive/refs/tags/v2.9.8.tar.gz", None),
    (
        "Source-PyInstaller-6.22.3.tar.gz",
        "https://github.com/pyinstaller/pyinstaller/archive/refs/tags/v6.22.3.tar.gz",
        None,
    ),
]


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def fetch(name, url, expected=None):
    target = OUT / name
    print(f"Downloading {name}", flush=True)
    with (
        urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=300) as response,
        target.open("wb") as output,
    ):
        shutil.copyfileobj(response, output, length=1024 * 1024)
    actual = digest(target)
    if expected and actual != expected:
        raise RuntimeError(f"Source checksum mismatch: {name}")
    # Validate the downloaded archive's container without executing source code.
    with tarfile.open(target) as archive:
        if archive.next() is None:
            raise RuntimeError(f"Empty source archive: {name}")
    print(f"Preserved {name}: {target.stat().st_size} bytes", flush=True)
    return {"file": name, "url": url, "sha256": actual}


def prepare_packages():
    names = {
        "windows": ["SONATA-0.1.0-windows-x64-portable.zip", "SONATA-0.1.0-windows-x64-setup.exe"],
        "linux": ["SONATA-0.1.0-linux-x86_64.tar.gz", "sonata-archiver_0.1.0_amd64.deb"],
    }
    for platform, packages in names.items():
        folder = ROOT / "release-input" / platform
        checksums = json.loads((folder / "SHA256SUMS.json").read_text())
        for name in packages:
            path = folder / name
            if digest(path) != checksums[name]:
                raise RuntimeError(f"Build artifact checksum mismatch: {name}")
            shutil.copy2(path, OUT / name)


def preserve_ytdlp_notices_and_mutagen():
    portable = OUT / "SONATA-0.1.0-windows-x64-portable.zip"
    with tempfile.TemporaryDirectory() as temp, zipfile.ZipFile(portable) as package:
        binary = Path(temp) / "yt-dlp.exe"
        with package.open("SONATA/_internal/vendor/yt-dlp.exe") as source, binary.open("wb") as target:
            shutil.copyfileobj(source, target)
        executable = CArchiveReader(str(binary))
        (OUT / "yt-dlp-THIRD-PARTY-LICENSES.txt").write_bytes(executable.extract("THIRD_PARTY_LICENSES.txt"))
        pyz = executable.open_embedded_archive("PYZ.pyz")
        version_tuple = next(
            c
            for c in pyz.extract("mutagen").co_consts
            if isinstance(c, tuple) and len(c) == 3 and all(isinstance(v, int) for v in c)
        )
        version = ".".join(map(str, version_tuple))
    with urllib.request.urlopen(
        urllib.request.Request(f"https://pypi.org/pypi/mutagen/{version}/json", headers=HEADERS), timeout=60
    ) as response:
        package = json.load(response)
    source = next(asset for asset in package["urls"] if asset["packagetype"] == "sdist")
    return fetch(f"Source-mutagen-{version}.tar.gz", source["url"], source["digests"]["sha256"])


def split_dependency_cache():
    candidates = list((ROOT / "upstream-source-cache").rglob("cache.tar.gz"))
    if len(candidates) != 1:
        raise RuntimeError("Expected the pinned upstream dependency source cache.")
    source = candidates[0]
    parts = []
    with source.open("rb") as stream:
        for index in range(100):
            block = stream.read(1_000_000_000)
            if not block:
                break
            name = f"Source-FFmpeg-dependencies.tar.gz.part-{index:02d}"
            (OUT / name).write_bytes(block)
            parts.append(name)
    return {
        "upstream_repository": "BtbN/FFmpeg-Builds",
        "workflow_run": 41199749965,
        "artifact_id": 13042311561,
        "upstream_artifact_sha256": "3de9f854a07aef24a0029b206e9ef43d674cbd957249575342e9a728d59c2c4d",
        "archive_sha256": digest(source),
        "parts": parts,
    }


def main():
    OUT.mkdir(exist_ok=True)
    prepare_packages()
    with ThreadPoolExecutor(max_workers=5) as executor:
        sources = list(executor.map(lambda source: fetch(*source), SOURCES))
    sources.append(preserve_ytdlp_notices_and_mutagen())
    dependencies = split_dependency_cache()
    manifest = {
        "application": "SONATA",
        "version": "0.1.0",
        "application_commit": APP_COMMIT,
        "verified_build_run": BUILD_RUN,
        "ffmpeg_commit": FFMPEG_COMMIT,
        "ffmpeg_build_recipes_commit": FFMPEG_BUILD_COMMIT,
        "source_snapshots": sources,
        "ffmpeg_dependency_sources": dependencies,
    }
    (OUT / "SOURCE-MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
    shutil.copy2(ROOT / "release-notes" / "SOURCE-README.txt", OUT / "SOURCE-README.txt")
    shutil.copy2(ROOT / "THIRD_PARTY.md", OUT / "THIRD_PARTY.md")
    shutil.copy2(ROOT / "LICENSE", OUT / "LICENSE.txt")
    shutil.copy2(ROOT / "tools-lock.json", OUT / "tools-lock.json")
    sums = {
        path.name: digest(path)
        for path in sorted(OUT.iterdir())
        if path.is_file() and path.name != "SHA256SUMS"
    }
    (OUT / "SHA256SUMS").write_text("".join(f"{value}  {name}\n" for name, value in sums.items()))
    print(f"Prepared {len(sums)} verified release assets.", flush=True)


if __name__ == "__main__":
    main()
