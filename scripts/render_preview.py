"""Render actual widgets without network activity or synthetic download progress."""

import argparse
import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from sonata.paths import AppPaths
from sonata.window import MainWindow


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--scan-profile", type=Path, help="Preview an isolated copy of an already-scanned queue"
    )
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = root / "docs" / "screenshots"
    output.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    if sys.platform == "win32":
        for font in ("segoeui.ttf", "segoeuib.ttf"):
            QFontDatabase.addApplicationFont(
                str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / font)
            )
        app.setFont(QFont("Segoe UI", 9))
    with tempfile.TemporaryDirectory() as profile:
        if args.scan_profile:
            shutil.copy2(args.scan_profile / "library.db", Path(profile) / "library.db")
        window = MainWindow(AppPaths(Path(profile), root / "vendor"))
        window.show()
        for theme, language, name in (
            ("light", "en", "light"),
            ("dark", "en", "dark"),
            ("dark", "ru", "russian"),
        ):
            window.db.save_setting("theme", theme)
            window.db.save_setting("language", language)
            window.build_ui()
            window.destination.setText("D:\\Archive" if sys.platform == "win32" else "/home/user/Archive")
            window.refresh()
            app.processEvents()
            if not window.grab().save(str(output / f"sonata-{name}.png")):
                raise RuntimeError("Failed to save widget preview")
        window.db.save_setting("language", "en")
        window.build_ui()
        window.open_media_tools()
        app.processEvents()
        window.media_window.grab().save(str(output / "sonata-ffmpeg.png"))
        window.media_window.close()
        window.close()


if __name__ == "__main__":
    main()
