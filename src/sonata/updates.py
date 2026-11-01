from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from sonata.engine import spawn_options
from sonata.paths import AppPaths

HEADERS = {"User-Agent": "SONATA/0.1.0", "Accept": "application/vnd.github+json"}


def request(url: str):
    return urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=45)


def asset_name() -> str:
    if platform.machine().lower() not in ("amd64", "x86_64"):
        raise RuntimeError("The bundled release currently supports x86-64 systems.")
    return "yt-dlp.exe" if sys.platform == "win32" else "yt-dlp_linux"


def update_downloader(paths: AppPaths, progress=lambda *_: None) -> str:
    """Explicit user action only. Verify official checksums before atomic activation."""
    with request("https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest") as response:
        release = json.load(response)
    tag = release["tag_name"]
    name = asset_name()
    assets = {a["name"]: a["browser_download_url"] for a in release["assets"]}
    with request(assets["SHA2-256SUMS"]) as response:
        sums = response.read(1024 * 1024).decode("utf-8")
    expected = next(
        (
            parts[0]
            for line in sums.splitlines()
            if len(parts := line.split()) >= 2 and parts[-1].lstrip("*") == name
        ),
        None,
    )
    if not expected or len(expected) != 64:
        raise RuntimeError("The official release has no matching SHA-256 checksum.")
    tools = paths.data / "tools"
    tools.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(
        prefix="yt-dlp-", suffix=".exe" if sys.platform == "win32" else "", dir=tools
    )
    digest = hashlib.sha256()
    try:
        with os.fdopen(handle, "wb") as stream, request(assets[name]) as response:
            total = int(response.headers.get("Content-Length", 0))
            downloaded = 0
            while block := response.read(1024 * 1024):
                downloaded += len(block)
                if downloaded > 250 * 1024 * 1024:
                    raise RuntimeError("The update exceeds the maximum expected size.")
                digest.update(block)
                stream.write(block)
                progress(downloaded, total)
        if digest.hexdigest() != expected:
            raise RuntimeError("Checksum verification failed; the installed downloader was preserved.")
        os.chmod(temporary, 0o755)
        result = subprocess.run(
            [temporary, "--version"], capture_output=True, text=True, timeout=30, **spawn_options()
        )
        if result.returncode or result.stdout.strip() != tag:
            raise RuntimeError("The new downloader did not pass its version check.")
        destination = tools / ("yt-dlp.exe" if sys.platform == "win32" else "yt-dlp")
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return tag
