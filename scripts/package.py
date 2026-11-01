"""Package a PyInstaller onedir build into a portable archive and (Linux) a DEB."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.1.0"


def main():
    folder = ROOT / "dist" / "SONATA"
    if not folder.is_dir():
        raise SystemExit("Build with PyInstaller first.")
    releases = ROOT / "dist" / "packages"
    releases.mkdir(exist_ok=True)
    # The portable marker is intentionally excluded from the installer build.
    marker = folder / "portable.txt"
    marker.write_text("Keep SONATA's settings and library beside the application.\n", encoding="utf-8")
    for name in ("README.md", "LICENSE", "THIRD_PARTY.md", "tools-lock.json"):
        shutil.copy2(ROOT / name, folder / name)
    if sys.platform == "win32":
        target = releases / f"SONATA-{VERSION}-windows-x64-portable.zip"
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
            for path in sorted(folder.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(folder.parent))
    else:
        target = releases / f"SONATA-{VERSION}-linux-x86_64.tar.gz"
        with tarfile.open(target, "w:gz") as archive:
            archive.add(folder, arcname="SONATA")
        package_deb(folder, releases)
    write_checksums(releases)
    print(target)


def write_checksums(releases):
    checksums = {}
    for path in sorted(releases.iterdir()):
        if path.is_file() and path.name not in ("SHA256SUMS", "SHA256SUMS.json"):
            with path.open("rb") as stream:
                checksums[path.name] = hashlib.file_digest(stream, "sha256").hexdigest()
    (releases / "SHA256SUMS.json").write_text(json.dumps(checksums, indent=2) + "\n", encoding="utf-8")
    (releases / "SHA256SUMS").write_text(
        "".join(f"{digest}  {name}\n" for name, digest in checksums.items()), encoding="utf-8"
    )


def package_deb(folder, releases):
    staging = ROOT / "build" / "deb"
    if staging.exists():
        raise RuntimeError("Use a clean build directory before producing a DEB.")
    installed = staging / "opt" / "sonata"
    shutil.copytree(folder, installed)
    (installed / "portable.txt").unlink(missing_ok=True)
    control = staging / "DEBIAN"
    control.mkdir()
    (control / "control").write_text(
        f"Package: sonata-archiver\nVersion: {VERSION}\nSection: video\nPriority: optional\nArchitecture: amd64\nMaintainer: SONATA contributors <noreply@github.com>\nDepends: libc6 (>= 2.35), libgl1, libegl1, libxkbcommon0, libxkbcommon-x11-0, libxcb-cursor0, libxcb-icccm4, libxcb-image0, libxcb-keysyms1, libxcb-render-util0, libxcb-xinerama0, libxcb-randr0, libxcb-shape0, libxcb-xfixes0\nDescription: Local multimedia downloader and archival manager\n A compact Qt desktop application powered by yt-dlp and FFmpeg.\n",
        encoding="utf-8",
    )
    applications = staging / "usr/share/applications"
    applications.mkdir(parents=True)
    (applications / "sonata.desktop").write_text(
        "[Desktop Entry]\nType=Application\nName=SONATA\nComment=Multimedia downloader and archival manager\nExec=/opt/sonata/SONATA\nTerminal=false\nCategories=AudioVideo;Network;\n",
        encoding="utf-8",
    )
    binary = staging / "usr/bin"
    binary.mkdir(parents=True)
    (binary / "sonata").symlink_to("/opt/sonata/SONATA")
    subprocess.run(
        [
            "dpkg-deb",
            "--root-owner-group",
            "--build",
            str(staging),
            str(releases / f"sonata-archiver_{VERSION}_amd64.deb"),
        ],
        check=True,
    )


if __name__ == "__main__":
    if "--checksums" in sys.argv:
        write_checksums(ROOT / "dist" / "packages")
    else:
        main()
