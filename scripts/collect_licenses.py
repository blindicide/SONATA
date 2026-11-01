"""Collect runtime notices from the installed Python/Qt distributions."""

import importlib.metadata
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    target = ROOT / "vendor" / "licenses"
    target.mkdir(parents=True, exist_ok=True)
    if (ROOT / "notices").is_dir():
        shutil.copytree(ROOT / "notices", target, dirs_exist_ok=True)
    runtime_license = Path(sys.base_prefix) / "LICENSE.txt"
    if runtime_license.exists():
        shutil.copy2(runtime_license, target / "Python-LICENSE.txt")
    for name in ("PySide6-Essentials", "shiboken6", "pyinstaller"):
        dist = importlib.metadata.distribution(name)
        for entry in dist.files or []:
            if any(part.lower().startswith(("license", "copying", "copyright")) for part in entry.parts):
                source = Path(dist.locate_file(entry))
                if source.is_file():
                    shutil.copy2(source, target / "_".join(entry.parts))
    print("Python, Qt, Shiboken and PyInstaller notices collected.")


if __name__ == "__main__":
    main()
