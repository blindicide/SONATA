"""Fetch official x86-64 runtime assets. --refresh creates a reviewed lockfile.

Normal builds use exact URLs and hashes in tools-lock.json; never silently track latest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HEADERS = {"User-Agent": "SONATA-build/0.1.0", "Accept": "application/vnd.github+json"}


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=120) as response:
        return response.read()


def lock_asset(repo, release, name):
    asset = next(a for a in release["assets"] if a["name"] == name)
    digest = asset.get("digest") or ""
    if not digest.startswith("sha256:"):
        # yt-dlp and Deno also ship checksums; compute a first lock from their official HTTPS asset.
        # The resulting hash is committed and required for every subsequent build.
        digest = "sha256:" + hashlib.sha256(fetch(asset["browser_download_url"])).hexdigest()
    return {
        "repo": repo,
        "version": release["tag_name"],
        "name": name,
        "url": asset["browser_download_url"],
        "sha256": digest.removeprefix("sha256:"),
    }


def refresh():
    result = {"schema": 1, "windows": [], "linux": []}
    for repo, names in [
        ("yt-dlp/yt-dlp", {"windows": "yt-dlp.exe", "linux": "yt-dlp_linux"}),
        (
            "denoland/deno",
            {"windows": "deno-x86_64-pc-windows-msvc.zip", "linux": "deno-x86_64-unknown-linux-gnu.zip"},
        ),
        (
            "BtbN/FFmpeg-Builds",
            {
                "windows": "ffmpeg-master-latest-win64-gpl.zip",
                "linux": "ffmpeg-master-latest-linux64-gpl.tar.xz",
            },
        ),
    ]:
        if repo == "BtbN/FFmpeg-Builds":
            releases = json.loads(fetch(f"https://api.github.com/repos/{repo}/releases?per_page=5"))
            release = next(r for r in releases if r["tag_name"].startswith("autobuild-"))
            names = {
                target: next(
                    a["name"]
                    for a in release["assets"]
                    if a["name"].startswith("ffmpeg-N-") and a["name"].endswith(suffix)
                )
                for target, suffix in (("windows", "-win64-gpl.zip"), ("linux", "-linux64-gpl.tar.xz"))
            }
        else:
            release = json.loads(fetch(f"https://api.github.com/repos/{repo}/releases/latest"))
        for target, name in names.items():
            result[target].append(lock_asset(repo, release, name))
            print(f"Locked {target}: {name}", flush=True)
    (ROOT / "tools-lock.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


def install(target):
    lock = json.loads((ROOT / "tools-lock.json").read_text(encoding="utf-8"))
    vendor = ROOT / "vendor"
    vendor.mkdir(exist_ok=True)
    licenses = vendor / "licenses"
    licenses.mkdir(exist_ok=True)
    suffix = ".exe" if target == "windows" else ""
    wanted = {"ffmpeg" + suffix, "ffprobe" + suffix, "deno" + suffix}
    with tempfile.TemporaryDirectory() as temporary:
        for asset in lock[target]:
            print(f"Fetching {asset['name']} ({asset['version']})", flush=True)
            payload = fetch(asset["url"])
            if hashlib.sha256(payload).hexdigest() != asset["sha256"]:
                raise RuntimeError(
                    f"Checksum mismatch for {asset['name']}; refresh and review the lock explicitly."
                )
            if asset["repo"] == "yt-dlp/yt-dlp":
                (vendor / ("yt-dlp" + suffix)).write_bytes(payload)
                continue
            archive = Path(temporary) / asset["name"]
            archive.write_bytes(payload)
            if archive.name.endswith(".zip"):
                with zipfile.ZipFile(archive) as source:
                    for member in source.infolist():
                        name = Path(member.filename).name
                        if name in wanted:
                            (vendor / name).write_bytes(source.read(member))
                        elif (
                            "license" in name.lower() or name.lower() in ("readme.txt", "readme.md")
                        ) and member.file_size < 2_000_000:
                            (licenses / (asset["repo"].replace("/", "-") + "-" + name)).write_bytes(
                                source.read(member)
                            )
            else:
                with tarfile.open(archive) as source:
                    for member in source:
                        name = Path(member.name).name
                        if member.isfile() and (
                            name in wanted or "license" in name.lower() or name.lower().startswith("readme")
                        ):
                            if name not in wanted and member.size > 2_000_000:
                                continue
                            with source.extractfile(member) as stream:
                                destination = (
                                    vendor / name if name in wanted else licenses / ("ffmpeg-" + name)
                                )
                                with destination.open("wb") as output:
                                    shutil.copyfileobj(stream, output)
    for name in ("yt-dlp", "ffmpeg", "ffprobe", "deno"):
        path = vendor / (name + suffix)
        if not path.is_file():
            raise RuntimeError(f"Missing runtime tool: {name}")
        os.chmod(path, 0o755)
    shutil.copy2(ROOT / "THIRD_PARTY.md", licenses / "THIRD_PARTY.md")
    shutil.copy2(ROOT / "tools-lock.json", licenses / "tools-lock.json")
    print("Bundled tools verified.", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument(
        "--target", choices=["windows", "linux"], default="windows" if sys.platform == "win32" else "linux"
    )
    args = parser.parse_args()
    if platform.machine().lower() not in ("amd64", "x86_64"):
        parser.error("The v0.1.0 release toolchain targets x86-64.")
    if args.refresh:
        refresh()
    install(args.target)
