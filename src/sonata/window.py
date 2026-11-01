from __future__ import annotations

import json
import threading
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QColor, QDesktopServices, QFont, QIcon, QPainter, QPixmap, QPolygon
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStyle,
    QTableWidgetItem,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from sonata import CODENAME, __version__
from sonata.archive import export_collection
from sonata.database import Database
from sonata.engine import Engine
from sonata.i18n import translator
from sonata.models import ACTIVE_STATES, DownloadOptions, validate_url
from sonata.paths import AppPaths
from sonata.preferences import Preferences, combo
from sonata.theme import apply_theme
from sonata.updates import update_downloader
from sonata.widgets import ProgressDelegate, eta_text, size_text, table


class Bridge(QObject):
    event = Signal(str, object)
    result = Signal(bool, str)


def app_icon() -> QIcon:
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.fillRect(4, 4, 56, 56, QColor("#27649a"))
    painter.fillRect(14, 15, 36, 8, QColor("#f3f6fa"))
    painter.fillRect(14, 28, 36, 8, QColor("#f3f6fa"))
    painter.fillRect(14, 41, 23, 8, QColor("#f3f6fa"))
    painter.end()
    return QIcon(pixmap)


def transfer_icon(kind, color):
    pixmap = QPixmap(16, 16)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(color)
    if kind == "SP_MediaPlay":
        painter.drawPolygon(QPolygon([QPoint(4, 2), QPoint(14, 8), QPoint(4, 14)]))
    elif kind == "SP_MediaPause":
        painter.drawRect(3, 2, 4, 12)
        painter.drawRect(10, 2, 4, 12)
    else:
        painter.drawRect(3, 3, 11, 11)
    painter.end()
    return QIcon(pixmap)


class MainWindow(QMainWindow):
    def __init__(self, paths: AppPaths):
        super().__init__()
        self.paths = paths
        self.db = Database(paths.data / "library.db")
        self.db.recover()
        self.options = DownloadOptions(
            **self.db.setting("download_options", {"destination": str(Path.home() / "Downloads/SONATA")})
        )
        self.bridge = Bridge(self)
        self.bridge.event.connect(self.on_event)
        self.bridge.result.connect(self.on_result)
        self.engine = Engine(self.db, paths, self.bridge.event.emit)
        self.busy = False
        self.maintenance = None
        self.log_lines = []
        self.last_library = None
        self.setWindowIcon(app_icon())
        self.setWindowTitle(f"SONATA {__version__} — {CODENAME}")
        self.resize(1160, 760)
        self.setMinimumSize(940, 620)
        self.build_ui()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(600)
        self.refresh()

    def build_ui(self):
        self.tr = translator(self.db.setting("language", "en"))
        tr = self.tr
        apply_theme(QApplication.instance(), self.db.setting("theme", "light") == "dark")
        for toolbar in self.findChildren(QToolBar):
            self.removeToolBar(toolbar)
            toolbar.deleteLater()
        self.menuBar().clear()
        menus = {
            name: self.menuBar().addMenu(tr(name)) for name in ("File", "Transfers", "Tools", "View", "Help")
        }
        toolbar = QToolBar("SONATA", self)
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(toolbar)
        self.start_action = None
        specs = [
            ("Add URLs", self.add_dialog, "Ctrl+N", "SP_FileDialogNewFolder", "File"),
            ("Start / Resume", self.start, "F5", "SP_MediaPlay", "Transfers"),
            (
                "Pause",
                lambda: self.engine.stop(self.selected_jobs() or None),
                "F6",
                "SP_MediaPause",
                "Transfers",
            ),
            (
                "Cancel",
                lambda: self.engine.stop(self.selected_jobs() or None, "cancelled"),
                "Ctrl+Delete",
                "SP_MediaStop",
                "Transfers",
            ),
            ("Retry", self.start, "Ctrl+R", "SP_BrowserReload", "Transfers"),
            ("Clear finished", self.clear_finished, None, "SP_DialogResetButton", "Transfers"),
            ("Open folder", self.open_folder, "Ctrl+O", "SP_DirOpenIcon", "File"),
            ("Preferences", self.preferences, "Ctrl+P", "SP_FileDialogDetailedView", "Tools"),
        ]
        for name, callback, shortcut, icon, menu in specs:
            artwork = (
                transfer_icon(icon, self.palette().windowText().color())
                if icon in ("SP_MediaPlay", "SP_MediaPause", "SP_MediaStop")
                else self.style().standardIcon(getattr(QStyle.StandardPixmap, icon))
            )
            action = QAction(artwork, tr(name), self)
            if shortcut:
                action.setShortcut(shortcut)
            action.triggered.connect(callback)
            menus[menu].addAction(action)
            toolbar.addAction(action)
            if name == "Start / Resume":
                self.start_action = action
        menus["File"].addSeparator()
        menus["File"].addAction(tr("Exit"), self.close, "Alt+F4")
        menus["Tools"].addSeparator()
        menus["Tools"].addAction(tr("Update yt-dlp"), self.update_tool)
        menus["Tools"].addAction(tr("Reset yt-dlp update"), self.reset_tool)
        menus["File"].addAction(tr("Save activity log…"), self.save_log)
        menus["Help"].addAction(tr("About SONATA"), self.about)
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(7)
        source = QHBoxLayout()
        source.addWidget(QLabel(tr("Source URL")))
        self.url = QLineEdit()
        self.url.setPlaceholderText(tr("Paste a video, playlist or channel URL…"))
        self.url.setClearButtonEnabled(True)
        self.url.returnPressed.connect(self.add_url)
        self.url.setAccessibleName(tr("Source URL"))
        source.addWidget(self.url, 1)
        self.add_button = QPushButton(tr("Add to queue"))
        self.add_button.clicked.connect(self.add_url)
        source.addWidget(self.add_button)
        root.addLayout(source)
        formats = QHBoxLayout()
        self.mode = combo([(tr("Video"), "video"), (tr("Audio only"), "audio")], self.options.mode)
        self.resolution = combo(
            [(tr("Best available"), 0)]
            + [
                (f"{h}p" + (" / 8K" if h == 4320 else ""), h) for h in (4320, 2160, 1440, 1080, 720, 480, 360)
            ],
            self.options.height,
        )
        self.container = combo([(x.upper(), x) for x in ("mkv", "mp4", "webm")], self.options.container)
        self.collection = QLineEdit(self.options.collection)
        self.collection.setPlaceholderText(tr("Unsorted"))
        for label, control in [
            ("Mode", self.mode),
            ("Resolution", self.resolution),
            ("Container", self.container),
            ("Collection", self.collection),
        ]:
            formats.addWidget(QLabel(tr(label)))
            formats.addWidget(control, 1 if label == "Collection" else 0)
        self.mode.currentIndexChanged.connect(self.mode_changed)
        self.mode_changed()
        root.addLayout(formats)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        queue_page = QWidget()
        queue_layout = QVBoxLayout(queue_page)
        queue_layout.setContentsMargins(0, 5, 0, 0)
        self.queue = table(
            [tr(x) for x in ("Title / Source", "State", "Progress", "Speed", "ETA", "Collection", "Added")]
        )
        self.queue.setItemDelegateForColumn(2, ProgressDelegate(self.queue))
        for col, width in enumerate((350, 105, 150, 100, 75, 115, 145)):
            self.queue.setColumnWidth(col, width)
        self.queue.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.queue.itemSelectionChanged.connect(self.details)
        self.queue.sortItems(6, Qt.SortOrder.DescendingOrder)
        self.detail = QPlainTextEdit()
        self.detail.setReadOnly(True)
        self.detail.setMaximumBlockCount(300)
        self.detail.setMinimumHeight(65)
        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self.queue)
        splitter.addWidget(self.detail)
        splitter.setSizes([440, 90])
        queue_layout.addWidget(splitter)
        self.tabs.addTab(queue_page, tr("Queue"))
        library_page = QWidget()
        library_layout = QVBoxLayout(library_page)
        library_layout.setContentsMargins(0, 5, 0, 0)
        search = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Search titles and URLs…"))
        self.search.textChanged.connect(self.refresh_library)
        self.collection_filter = QComboBox()
        self.collection_filter.addItem(tr("All collections"), None)
        self.collection_filter.currentIndexChanged.connect(self.refresh_library)
        export = QPushButton(tr("Export collection…"))
        export.clicked.connect(self.export)
        search.addWidget(self.search, 1)
        search.addWidget(self.collection_filter)
        search.addWidget(export)
        library_layout.addLayout(search)
        self.library = table(
            [tr(x) for x in ("Title", "Source", "Collection", "Completed", "Size", "Location")]
        )
        self.library.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.library.setColumnWidth(1, 140)
        self.library.setColumnWidth(3, 150)
        self.library.setColumnWidth(5, 180)
        self.library.itemDoubleClicked.connect(self.open_library_file)
        library_layout.addWidget(self.library)
        self.tabs.addTab(library_page, tr("Library"))
        self.activity = QPlainTextEdit()
        self.activity.setReadOnly(True)
        self.activity.setMaximumBlockCount(3000)
        self.activity.setFont(QFont("Consolas" if __import__("sys").platform == "win32" else "monospace", 9))
        self.activity.setPlainText("\n".join(self.log_lines))
        self.tabs.addTab(self.activity, tr("Activity"))
        for index, name in enumerate(("Queue", "Library", "Activity")):
            menus["View"].addAction(tr(name), lambda checked=False, n=index: self.tabs.setCurrentIndex(n))
        destination = QHBoxLayout()
        destination.addWidget(QLabel(tr("Destination")))
        self.destination = QLineEdit(self.options.destination)
        destination.addWidget(self.destination, 1)
        browse = QPushButton(tr("Browse…"))
        browse.clicked.connect(self.browse)
        destination.addWidget(browse)
        root.addLayout(destination)
        previous = self.takeCentralWidget()
        self.setCentralWidget(central)
        if previous:
            previous.deleteLater()
        if not hasattr(self, "status_label"):
            self.status_label = QLabel()
            self.rate_label = QLabel()
            self.statusBar().addWidget(self.status_label, 1)
            self.statusBar().addPermanentWidget(self.rate_label)
        self.last_library = None
        self.refresh_library()
        self.url.setFocus()

    def mode_changed(self):
        video = self.mode.currentData() == "video"
        self.resolution.setEnabled(video)
        self.container.setEnabled(video)

    def current_options(self):
        return replace(
            self.options,
            destination=self.destination.text().strip(),
            collection=self.collection.text().strip(),
            mode=self.mode.currentData(),
            height=self.resolution.currentData(),
            container=self.container.currentData(),
        ).validate()

    def add_url(self):
        self.add_sources(self.url.text().split())

    def add_dialog(self):
        text, accepted = QInputDialog.getMultiLineText(
            self, self.tr("Add URLs"), self.tr("Enter URLs, one per line")
        )
        if accepted:
            self.add_sources(text.split())

    def add_sources(self, sources):
        if not sources or self.busy:
            return
        try:
            options = self.current_options()
            urls = list(dict.fromkeys(validate_url(url) for url in sources))
            for url in urls:
                self.db.add(url, options)
            self.options = options
            self.db.save_setting("download_options", options.to_dict())
            self.url.clear()
            self.refresh()
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, self.tr("Error"), str(exc))

    def selected_jobs(self):
        if not hasattr(self, "queue"):
            return []
        return [
            self.queue.item(index.row(), 0).data(Qt.ItemDataRole.UserRole)
            for index in self.queue.selectionModel().selectedRows()
        ]

    def start(self):
        if not self.busy:
            self.engine.start(self.selected_jobs() or None)
            self.refresh()

    def clear_finished(self):
        self.db.clear_finished()
        self.refresh()

    def browse(self):
        folder = QFileDialog.getExistingDirectory(
            self, self.tr("Choose destination"), self.destination.text()
        )
        if folder:
            self.destination.setText(folder)

    def open_folder(self):
        ids = self.selected_jobs()
        folder = (
            DownloadOptions(**json.loads(self.db.job(ids[0])["options"])).folder
            if ids
            else Path(self.destination.text())
        )
        if folder.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder.resolve())))

    def open_library_file(self, item):
        filename = self.library.item(item.row(), 0).data(Qt.ItemDataRole.UserRole)
        if filename and Path(filename).is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(filename))

    def details(self):
        ids = self.selected_jobs()
        if not ids:
            self.detail.setPlainText(
                self.tr("No downloads yet. Add a source URL above.")
                if not self.queue.rowCount()
                else self.tr("No selection")
            )
            return
        try:
            job = self.db.job(ids[0])
        except KeyError:
            return
        self.detail.setPlainText(
            f"{job['title']}\n{job['url']}\n{self.tr(job['state'])}"
            + (f"\n{job['error']}" if job["error"] else "")
        )

    def refresh(self):
        self.engine.tick()
        jobs = self.db.jobs()
        selected = set(self.selected_jobs())
        self.queue.blockSignals(True)
        self.queue.setSortingEnabled(False)
        self.queue.setRowCount(len(jobs))
        for row, job in enumerate(jobs):
            options = json.loads(job["options"])
            values = [
                job["title"],
                self.tr(job["state"]),
                f"{job['progress']:.1f}%",
                size_text(job["speed"]) + "/s" if job["speed"] else "—",
                eta_text(job["eta"]),
                options["collection"] or self.tr("Unsorted"),
                job["created"].replace("T", " ")[:19],
            ]
            for column, value in enumerate(values):
                item = self.queue.item(row, column)
                if item is None:
                    item = SortItem(value)
                    self.queue.setItem(row, column, item)
                elif item.text() != value:
                    item.setText(value)
                item.setToolTip(job["error"] or job["url"])
                item.sort_value = {
                    2: job["progress"],
                    3: job["speed"],
                    4: job["eta"] if job["eta"] is not None else -1,
                }.get(column, value.casefold())
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, job["id"])
                elif column == 2:
                    item.setData(Qt.ItemDataRole.UserRole, job["progress"])
                if column == 1:
                    item.setForeground(
                        QColor("#d85858") if job["state"] == "failed" else self.palette().text().color()
                    )
        self.queue.clearSelection()
        for row, job in enumerate(jobs):
            if job["id"] in selected:
                for col in range(self.queue.columnCount()):
                    self.queue.item(row, col).setSelected(True)
        self.queue.setSortingEnabled(True)
        self.queue.blockSignals(False)
        self.details()
        active = sum(j["state"] in ACTIVE_STATES[1:] for j in jobs)
        self.status_label.setText(
            self.tr(
                "{active} active · {queued} queued · {done} completed",
                active=active,
                queued=sum(j["state"] == "queued" for j in jobs),
                done=sum(j["state"] == "completed" for j in jobs),
            )
        )
        self.rate_label.setText(size_text(sum(j["speed"] for j in jobs)) + "/s")
        signature = tuple((r["media_key"], r["completed"]) for r in self.db.history())
        if signature != self.last_library:
            self.last_library = signature
            self.refresh_library()

    def refresh_library(self, *_):
        if not hasattr(self, "library"):
            return
        collections = sorted({record["collection"] for record in self.db.history()})
        current = self.collection_filter.currentData()
        existing = [self.collection_filter.itemData(i) for i in range(1, self.collection_filter.count())]
        if existing != collections:
            self.collection_filter.blockSignals(True)
            self.collection_filter.clear()
            self.collection_filter.addItem(self.tr("All collections"), None)
            for collection in collections:
                self.collection_filter.addItem(collection or self.tr("Unsorted"), collection)
            self.collection_filter.setCurrentIndex(max(0, self.collection_filter.findData(current)))
            self.collection_filter.blockSignals(False)
        records = self.db.history(self.search.text(), self.collection_filter.currentData())
        self.library.setSortingEnabled(False)
        self.library.setRowCount(len(records))
        for row, record in enumerate(records):
            files = json.loads(record["files"])
            values = [
                record["title"],
                record["media_key"].partition(":")[0],
                record["collection"] or self.tr("Unsorted"),
                record["completed"].replace("T", " ")[:19],
                size_text(record["size"]),
                record["folder"],
            ]
            for column, value in enumerate(values):
                item = SortItem(value)
                item.sort_value = record["size"] if column == 4 else value.casefold()
                item.setToolTip(record["url"] if column == 0 else str(value))
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, files[0] if files else "")
                self.library.setItem(row, column, item)
        self.library.setSortingEnabled(True)

    def on_event(self, kind, value):
        if kind == "log":
            job_id, line = value
            line = f"[{job_id:04d}] {line}"
            self.log_lines.append(line)
            self.log_lines = self.log_lines[-3000:]
            self.activity.appendPlainText(line)

    def preferences(self):
        if self.busy:
            return
        try:
            options = self.current_options()
        except ValueError as exc:
            QMessageBox.warning(self, self.tr("Error"), str(exc))
            return
        dialog = Preferences(self, options)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.options = dialog.options
            self.db.save_setting("download_options", self.options.to_dict())
            self.db.save_setting("theme", dialog.theme.currentData())
            self.db.save_setting("language", dialog.language.currentData())
            self.db.save_setting("concurrency", dialog.concurrent.value())
            self.engine.concurrency = dialog.concurrent.value()
            self.build_ui()
            self.refresh()

    def run_maintenance(self, message, operation):
        if self.busy:
            return
        self.busy = True
        self.start_action.setEnabled(False)
        self.add_button.setEnabled(False)
        self.statusBar().showMessage(self.tr(message))

        def run():
            try:
                self.bridge.result.emit(True, operation())
            except Exception as exc:
                self.bridge.result.emit(False, str(exc))

        self.maintenance = threading.Thread(target=run, name="sonata-maintenance")
        self.maintenance.start()

    def on_result(self, success, message):
        self.busy = False
        self.start_action.setEnabled(True)
        self.add_button.setEnabled(True)
        self.statusBar().clearMessage()
        if success:
            QMessageBox.information(self, self.tr("Success"), message)
        else:
            QMessageBox.warning(self, self.tr("Error"), message)

    def update_tool(self):
        if self.engine.running:
            QMessageBox.information(
                self,
                self.tr("Update yt-dlp"),
                self.tr("Pause active downloads before updating the downloader."),
            )
            return
        self.engine.enabled = False
        self.run_maintenance(
            "Updating yt-dlp…",
            lambda: self.tr("yt-dlp updated to {version}.", version=update_downloader(self.paths)),
        )

    def reset_tool(self):
        if self.busy or self.engine.running:
            return
        import sys

        path = self.paths.data / "tools" / ("yt-dlp.exe" if sys.platform == "win32" else "yt-dlp")
        path.unlink(missing_ok=True)
        QMessageBox.information(self, self.tr("Success"), self.tr("The bundled downloader is active again."))

    def export(self):
        if self.busy:
            return
        collection = self.collection_filter.currentData()
        if collection is None:
            QMessageBox.information(
                self, self.tr("Export archive"), self.tr("Select one collection before exporting.")
            )
            return
        records = self.db.history(collection=collection)
        if not records:
            QMessageBox.information(self, self.tr("Export archive"), self.tr("No files in this collection."))
            return
        filename, _ = QFileDialog.getSaveFileName(
            self,
            self.tr("Export archive"),
            str(Path(self.destination.text()) / ((collection or "SONATA") + ".tar.gz")),
            "TAR.GZ (*.tar.gz);;TAR (*.tar)",
        )
        if filename:
            self.run_maintenance(
                "Exporting archive…",
                lambda: self.tr("Exported {count} files.", count=export_collection(records, Path(filename))),
            )

    def save_log(self):
        filename, _ = QFileDialog.getSaveFileName(
            self, self.tr("Save activity log…"), "sonata.log", "Log (*.log);;Text (*.txt)"
        )
        if filename:
            try:
                Path(filename).write_text("\n".join(self.log_lines), encoding="utf-8")
            except OSError as exc:
                QMessageBox.warning(self, self.tr("Error"), str(exc))

    def about(self):
        QMessageBox.about(
            self,
            self.tr("About SONATA"),
            f"<b>SONATA {__version__} — {CODENAME}</b><br>Serverless Optimized Native Adaptable Tape Archiver<br><br>{self.tr('Local library · no telemetry · no account required')}<br><br>Python · PySide6 · yt-dlp · FFmpeg · Deno<br>GPL-3.0-or-later<br><a href='https://github.com/blindicide/SONATA'>github.com/blindicide/SONATA</a>",
        )

    def closeEvent(self, event):
        if self.busy:
            QMessageBox.information(self, self.tr("Working…"), self.tr("Working…"))
            event.ignore()
            return
        if (
            self.engine.running
            and QMessageBox.question(
                self,
                "SONATA",
                self.tr("Quit SONATA? Active transfers will be paused and can be resumed later."),
            )
            != QMessageBox.StandardButton.Yes
        ):
            event.ignore()
            return
        self.timer.stop()
        self.engine.shutdown()
        try:
            self.db.save_setting("download_options", self.current_options().to_dict())
        except ValueError:
            pass
        event.accept()


class SortItem(QTableWidgetItem):
    def __init__(self, text):
        super().__init__(text)
        self.sort_value = text.casefold()

    def __lt__(self, other):
        return self.sort_value < other.sort_value if isinstance(other, SortItem) else super().__lt__(other)
