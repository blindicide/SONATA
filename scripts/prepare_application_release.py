"""Select only the four verified application packages and their checksums."""

import hashlib
import json
import shutil
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def prepare(root: Path = ROOT):
    version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    output = root / "release-assets"
    output.mkdir(exist_ok=True)
    names = {
        "windows": [f"SONATA-{version}-windows-x64-setup.exe", f"SONATA-{version}-windows-x64-portable.zip"],
        "linux": [f"SONATA-{version}-linux-x86_64.tar.gz", f"sonata-archiver_{version}_amd64.deb"],
    }
    checksums = {}
    for platform, filenames in names.items():
        folder = root / "release-input" / platform
        expected = json.loads((folder / "SHA256SUMS.json").read_text(encoding="utf-8"))
        for filename in filenames:
            path = folder / filename
            with path.open("rb") as stream:
                actual = hashlib.file_digest(stream, "sha256").hexdigest()
            if actual != expected.get(filename):
                raise RuntimeError(f"Build package checksum mismatch: {filename}")
            shutil.copy2(path, output / filename)
            checksums[filename] = actual
    (output / "SHA256SUMS").write_text(
        "".join(f"{digest}  {name}\n" for name, digest in sorted(checksums.items())), encoding="utf-8"
    )
    if {p.name for p in output.iterdir()} != set(checksums) | {"SHA256SUMS"}:
        raise RuntimeError("The application release directory contains extra files.")
    return version


if __name__ == "__main__":
    print(prepare())
