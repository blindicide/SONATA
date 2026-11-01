import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "prepare_application_release",
    Path(__file__).resolve().parents[1] / "scripts/prepare_application_release.py",
)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def build_artifacts(root):
    (root / "pyproject.toml").write_text('[project]\nversion = "0.1.1"\n', encoding="utf-8")
    for platform, names in {
        "windows": ["SONATA-0.1.1-windows-x64-setup.exe", "SONATA-0.1.1-windows-x64-portable.zip"],
        "linux": ["SONATA-0.1.1-linux-x86_64.tar.gz", "sonata-archiver_0.1.1_amd64.deb"],
    }.items():
        folder = root / "release-input" / platform
        folder.mkdir(parents=True)
        checksums = {}
        for name in names:
            data = name.encode("utf-8")
            (folder / name).write_bytes(data)
            checksums[name] = hashlib.sha256(data).hexdigest()
        (folder / "SHA256SUMS.json").write_text(json.dumps(checksums), encoding="utf-8")
        (folder / "developer-materials.tar.gz").write_bytes(b"not a download asset")


def test_release_contains_only_application_downloads_and_checksums(tmp_path):
    build_artifacts(tmp_path)
    assert release.prepare(tmp_path) == "0.1.1"
    output = tmp_path / "release-assets"
    assert len(list(output.iterdir())) == 5
    assert not (output / "developer-materials.tar.gz").exists()
    for line in (output / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, name = line.split("  ")
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == digest
    (output / "extra.txt").write_text("extra", encoding="utf-8")
    with pytest.raises(RuntimeError, match="extra"):
        release.prepare(tmp_path)


def test_release_rejects_changed_build_package(tmp_path):
    build_artifacts(tmp_path)
    (tmp_path / "release-input/windows/SONATA-0.1.1-windows-x64-setup.exe").write_bytes(b"changed")
    with pytest.raises(RuntimeError, match="checksum mismatch"):
        release.prepare(tmp_path)
