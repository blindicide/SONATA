import hashlib
import io
import json
from types import SimpleNamespace

import pytest

from sonata import updates
from sonata.paths import AppPaths


def responses(monkeypatch, payload, checksum):
    name = updates.asset_name()
    release = {
        "tag_name": "2026.10.26",
        "assets": [
            {"name": name, "browser_download_url": "https://example.org/binary"},
            {"name": "SHA2-256SUMS", "browser_download_url": "https://example.org/sums"},
        ],
    }

    def request(url):
        data = (
            payload
            if url.endswith("binary")
            else (
                f"\n{checksum}  {name}\n".encode() if url.endswith("sums") else json.dumps(release).encode()
            )
        )
        stream = io.BytesIO(data)
        stream.headers = {"Content-Length": str(len(data))}
        return stream

    monkeypatch.setattr(updates, "request", request)


def test_bad_update_preserves_existing_tool(tmp_path, monkeypatch):
    paths = AppPaths(tmp_path, tmp_path)
    tools = paths.data / "tools"
    tools.mkdir()
    name = "yt-dlp.exe" if updates.sys.platform == "win32" else "yt-dlp"
    installed = tools / name
    installed.write_bytes(b"previous version")
    responses(monkeypatch, b"corrupt download", "0" * 64)
    with pytest.raises(RuntimeError, match="Checksum verification failed"):
        updates.update_downloader(paths)
    assert installed.read_bytes() == b"previous version"
    assert list(tools.iterdir()) == [installed]


def test_verified_update_activates_only_after_version_check(tmp_path, monkeypatch):
    paths = AppPaths(tmp_path, tmp_path)
    payload = b"verified executable"
    responses(monkeypatch, payload, hashlib.sha256(payload).hexdigest())
    monkeypatch.setattr(
        updates.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout="2026.10.26\n"),
    )
    assert updates.update_downloader(paths) == "2026.10.26"
    assert paths.tool("yt-dlp").read_bytes() == payload
