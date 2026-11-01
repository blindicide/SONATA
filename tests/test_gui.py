import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from sonata.paths import AppPaths
from sonata.preferences import Preferences
from sonata.window import MainWindow


def test_window_themes_localization_and_queue(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(AppPaths(tmp_path / "profile", tmp_path / "vendor"))
    window.destination.setText(str(tmp_path / "downloads"))
    window.add_sources(["https://example.org/video"])
    assert window.queue.rowCount() == 1
    assert not window.engine.running
    for theme in ("dark", "light"):
        for language in ("ru", "en"):
            window.db.save_setting("theme", theme)
            window.db.save_setting("language", language)
            window.build_ui()
            window.refresh()
            app.processEvents()
            assert window.tabs.count() == 3
            assert window.queue.rowCount() == 1
            dialog = Preferences(window, window.current_options())
            assert dialog.language.currentData() == language
            dialog.close()
    window.close()
    app.processEvents()
