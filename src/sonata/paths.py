from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path


def bundle_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))


@dataclass(frozen=True)
class AppPaths:
    data: Path
    vendor: Path

    @classmethod
    def discover(cls, portable: bool = False, data_dir: Path | None = None) -> AppPaths:
        executable_dir = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path.cwd()
        if data_dir:
            data = data_dir.resolve()
        elif portable or (executable_dir / "portable.txt").exists():
            data = executable_dir / ".sonata"
        elif sys.platform == "win32":
            data = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "SONATA"
        else:
            data = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "sonata"
        data.mkdir(parents=True, exist_ok=True)
        return cls(data, bundle_root() / "vendor")

    def tool(self, name: str) -> Path:
        suffix = ".exe" if sys.platform == "win32" else ""
        if name == "yt-dlp":
            updated = self.data / "tools" / (name + suffix)
            if updated.is_file():
                return updated
        candidate = self.vendor / (name + suffix)
        if not candidate.is_file():
            raise FileNotFoundError(
                f"Bundled {name} is missing. Run scripts/fetch_tools.py before launching from source."
            )
        return candidate
