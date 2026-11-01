import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QStyleOptionViewItem

from sonata.database import Database
from sonata.engine import Engine
from sonata.models import DownloadOptions, scan_summary
from sonata.paths import AppPaths
from sonata.preferences import Preferences
from sonata.window import MainWindow


def test_upgrade_sets_new_defaults_and_preserves_queued_options(tmp_path, monkeypatch):
    monkeypatch.setattr(Engine, "tick", lambda self: None)
    app = QApplication.instance() or QApplication([])
    profile = tmp_path / "profile"
    profile.mkdir()
    db = Database(profile / "library.db")
    old_options = DownloadOptions(str(tmp_path), container="mkv", height=1080, rate_kib=256)
    db.save_setting("download_options", old_options.to_dict())
    job = db.add("https://example.org/old", old_options)
    window = MainWindow(AppPaths(profile, tmp_path / "vendor"))
    assert window.current_options().container == "mp4"
    assert window.current_options().height == 0
    assert window.current_options().rate_kib == 256
    assert json.loads(window.db.job(job)["options"])["container"] == "mkv"
    assert json.loads(window.db.job(job)["options"])["height"] == 1080
    window.close()
    app.processEvents()


def test_window_themes_localization_and_queue(tmp_path, monkeypatch):
    monkeypatch.setattr(Engine, "tick", lambda self: None)
    app = QApplication.instance() or QApplication([])
    window = MainWindow(AppPaths(tmp_path / "profile", tmp_path / "vendor"))
    window.destination.setText(str(tmp_path / "downloads"))
    window.add_sources(["https://example.org/video"])
    assert window.queue.rowCount() == 1
    assert not window.engine.running
    assert window.container.currentData() == "mp4"
    assert window.queue.columnCount() == 8
    window.open_media_tools()
    assert window.media_window.tabs.count() == 6
    assert not window.media_window.isModal()
    window.media_window.close()
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


def test_resolution_dropdown_opens_with_a_click_and_commits(tmp_path, monkeypatch):
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QComboBox

    monkeypatch.setattr(Engine, "tick", lambda self: None)
    app = QApplication.instance() or QApplication([])
    window = MainWindow(AppPaths(tmp_path / "profile", tmp_path / "vendor"))
    job = window.db.add("https://example.org/video", DownloadOptions(str(tmp_path), height=720))
    scan = scan_summary({"formats": [{"height": h, "width": h * 2, "vcodec": "avc1"} for h in (720, 360)]})
    window.db.update(job, scan_state="ready", scan=json.dumps(scan))
    window.refresh()
    window.show()
    app.processEvents()
    rect = window.queue.visualItemRect(window.queue.item(0, 2))
    QTest.mouseClick(
        window.queue.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, rect.center()
    )
    app.processEvents()
    editors = [editor for editor in window.queue.findChildren(QComboBox) if editor.isVisible()]
    assert editors
    editor = editors[0]
    editor.setCurrentIndex(editor.findData(360))
    editor.activated.emit(editor.currentIndex())
    app.processEvents()
    assert json.loads(window.db.job(job)["options"])["height"] == 360
    window.close()
    app.processEvents()


def test_resolution_dropdown_changes_only_its_video(tmp_path, monkeypatch):
    monkeypatch.setattr(Engine, "tick", lambda self: None)
    app = QApplication.instance() or QApplication([])
    window = MainWindow(AppPaths(tmp_path / "profile", tmp_path / "vendor"))
    options = DownloadOptions(str(tmp_path), height=262)
    job = window.db.add("https://example.org/video", options)
    scan = scan_summary(
        {"formats": [{"height": h, "width": w, "vcodec": "avc1"} for h, w in ((262, 352), (144, 194))]}
    )
    window.db.update(job, scan_state="ready", scan=json.dumps(scan))
    window.refresh()
    item = window.queue.item(0, 2)
    assert "262p" in item.text()
    assert item.flags() & Qt.ItemFlag.ItemIsEditable
    delegate = window.queue.itemDelegateForColumn(2)
    index = window.queue.model().index(0, 2)
    editor = delegate.createEditor(window.queue.viewport(), QStyleOptionViewItem(), index)
    delegate.setEditorData(editor, index)
    app.processEvents()
    assert [editor.itemData(i) for i in range(editor.count())] == [262, 144]
    editor.setCurrentIndex(1)
    delegate.setModelData(editor, window.queue.model(), index)
    assert json.loads(window.db.job(job)["options"])["height"] == 144
    editor.hide()
    window.close()
    app.processEvents()
