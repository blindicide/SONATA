from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PySide6.QtCore import QLockFile
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QMessageBox

from sonata import __version__
from sonata.paths import AppPaths
from sonata.window import MainWindow


def main() -> int:
    parser = argparse.ArgumentParser(description="SONATA — Overture")
    parser.add_argument("--portable", action="store_true", help="Store the library beside the application")
    parser.add_argument("--data-dir", type=Path, help="Use a separate local profile")
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    app.setApplicationName("SONATA")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("SONATA")
    app.setFont(QFont("Segoe UI" if sys.platform == "win32" else "DejaVu Sans", 9))
    paths = AppPaths.discover(args.portable, args.data_dir)
    lock = QLockFile(str(paths.data / "instance.lock"))
    lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QMessageBox.information(
            None, "SONATA", "SONATA is already using this library. / Эта библиотека уже открыта в SONATA."
        )
        return 1
    window = MainWindow(paths)
    window.show()
    result = app.exec()
    lock.unlock()
    return result
