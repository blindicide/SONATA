from __future__ import annotations

import json
import shlex
import subprocess
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from sonata.engine import Stopped
from sonata.media import MediaRunner, MediaTask, execute_task, inspect_media, processing_command
from sonata.preferences import combo


class MediaSignals(QObject):
    message = Signal(str)
    progress = Signal(float)
    result = Signal(bool, object)


class MediaTools(QDialog):
    def __init__(self, parent):
        super().__init__(parent, Qt.WindowType.Window)
        self.paths = parent.paths
        self.tr = parent.tr
        self.language = parent.db.setting("language", "en")
        self.busy = False
        self.worker = None
        self.runner = None
        self.info = {}
        self.last_output = ""
        self.populating = False
        tr = self.tr
        self.setWindowTitle("SONATA — " + tr("FFmpeg tools"))
        self.setWindowIcon(parent.windowIcon())
        self.resize(800, 780)
        self.setMinimumSize(700, 650)
        root = QVBoxLayout(self)
        self.source = QLineEdit()
        self.output = QLineEdit()
        self.source_button = QPushButton(tr("Browse…"))
        self.output_button = QPushButton(tr("Browse…"))
        self.source_button.clicked.connect(self.browse_source)
        self.output_button.clicked.connect(self.browse_output)
        self.inspect_button = QPushButton(tr("Inspect file"))
        self.inspect_button.clicked.connect(self.inspect)
        for label, field, button in (
            ("Input file", self.source, self.source_button),
            ("Output file", self.output, self.output_button),
        ):
            row = QHBoxLayout()
            row.addWidget(QLabel(tr(label)))
            row.addWidget(field, 1)
            row.addWidget(button)
            if label == "Input file":
                row.addWidget(self.inspect_button)
            root.addLayout(row)
        self.source.returnPressed.connect(self.inspect)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        convert, metadata, subtitles, thumbnail, inspection, advanced = (QWidget() for _ in range(6))
        for page, label in (
            (convert, "Convert / Remux"),
            (metadata, "Metadata"),
            (subtitles, "Subtitles"),
            (thumbnail, "Thumbnail"),
            (inspection, "Media information"),
            (advanced, "Advanced"),
        ):
            self.tabs.addTab(page, tr(label))
        form = QFormLayout(convert)
        self.operation = combo(
            [
                (tr("Convert video"), "convert"),
                (tr("Remux (copy streams)"), "remux"),
                (tr("Extract audio"), "audio"),
                (tr("Trim"), "trim"),
            ],
            "convert",
        )
        self.container = combo(
            [(x.upper(), x) for x in ("mp4", "mkv", "webm", "m4a", "mp3", "opus", "flac", "wav")], "mp4"
        )
        self.video = combo(
            [
                (tr("Copy original"), "copy"),
                ("H.264", "h264"),
                ("H.265 / HEVC", "hevc"),
                ("VP9", "vp9"),
                ("AV1", "av1"),
            ],
            "copy",
        )
        self.audio = combo(
            [
                (tr("Copy original"), "copy"),
                ("AAC", "aac"),
                ("MP3", "mp3"),
                ("Opus", "opus"),
                ("FLAC", "flac"),
                ("PCM / WAV", "pcm"),
            ],
            "aac",
        )
        self.bitrate = QSpinBox()
        self.bitrate.setRange(8, 512)
        self.bitrate.setValue(192)
        self.bitrate.setSuffix(" kbit/s")
        self.crf = QSpinBox()
        self.crf.setRange(0, 51)
        self.crf.setValue(20)
        self.scale = QSpinBox()
        self.scale.setRange(0, 16384)
        self.scale.setSpecialValueText(tr("Original size"))
        self.start = self.time_field()
        self.end = self.time_field()
        self.end.setSpecialValueText(tr("Until end"))
        self.normalize = QCheckBox(tr("Normalize audio loudness"))
        for label, field in (
            ("Operation", self.operation),
            ("Output format", self.container),
            ("Video codec", self.video),
            ("Audio codec", self.audio),
            ("Audio bitrate", self.bitrate),
            ("Video quality (CRF)", self.crf),
            ("Resize height", self.scale),
            ("Start (seconds)", self.start),
            ("End (seconds)", self.end),
        ):
            form.addRow(tr(label), field)
        form.addRow(self.normalize)
        hint = QLabel(
            tr("Copy keeps the original streams. Resizing and exact frame cuts require a video encoder.")
        )
        hint.setWordWrap(True)
        form.addRow(hint)
        self.operation.currentIndexChanged.connect(self.operation_changed)
        self.container.currentIndexChanged.connect(self.output_changed)
        self.video.currentIndexChanged.connect(self.codec_changed)
        form = QFormLayout(metadata)
        self.keep_metadata = QCheckBox(tr("Keep existing metadata"))
        self.keep_metadata.setChecked(True)
        form.addRow(self.keep_metadata)
        self.tags = {}
        for key, label in (
            ("title", "Title"),
            ("artist", "Artist"),
            ("album", "Album"),
            ("date", "Date"),
            ("genre", "Genre"),
            ("comment", "Comment"),
        ):
            self.tags[key] = QLineEdit()
            form.addRow(tr(label), self.tags[key])
        self.description = QPlainTextEdit()
        self.description.setMaximumHeight(130)
        form.addRow(tr("Description"), self.description)
        form.addRow(QLabel(tr("Inspect the file to load its current tags. Unspecified tags are preserved.")))
        form = QFormLayout(subtitles)
        self.subtitle_mode = combo(
            [(tr("Embed subtitles"), "embed_subtitle"), (tr("Extract subtitles"), "extract_subtitle")],
            "embed_subtitle",
        )
        self.subtitle_file = QLineEdit()
        browse_subtitle = QPushButton(tr("Browse…"))
        browse_subtitle.clicked.connect(self.browse_subtitle)
        row = QHBoxLayout()
        row.addWidget(self.subtitle_file, 1)
        row.addWidget(browse_subtitle)
        self.subtitle_track = QSpinBox()
        self.subtitle_track.setRange(1, 99)
        self.subtitle_language = QLineEdit("eng")
        self.subtitle_format = combo([("SRT", "srt"), ("WebVTT", "vtt")], "srt")
        form.addRow(tr("Operation"), self.subtitle_mode)
        form.addRow(tr("Subtitle file"), row)
        form.addRow(tr("Subtitle track (1 = first)"), self.subtitle_track)
        form.addRow(tr("Language code"), self.subtitle_language)
        form.addRow(tr("Extract as"), self.subtitle_format)
        self.subtitle_mode.currentIndexChanged.connect(self.output_changed)
        self.subtitle_format.currentIndexChanged.connect(self.output_changed)
        form = QFormLayout(thumbnail)
        self.thumbnail_time = self.time_field()
        self.thumbnail_format = combo([("JPEG", "jpg"), ("PNG", "png")], "jpg")
        self.thumbnail_format.currentIndexChanged.connect(self.output_changed)
        form.addRow(tr("Frame time (seconds)"), self.thumbnail_time)
        form.addRow(tr("Image format"), self.thumbnail_format)
        inspect_layout = QVBoxLayout(inspection)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels([tr("Property"), tr("Value")])
        self.tree.setColumnWidth(0, 220)
        inspect_layout.addWidget(self.tree)
        save_json = QPushButton(tr("Save probe JSON…"))
        save_json.clicked.connect(self.save_probe)
        inspect_layout.addWidget(save_json, alignment=Qt.AlignmentFlag.AlignRight)
        advanced_layout = QVBoxLayout(advanced)
        advanced_layout.addWidget(QLabel(tr("Extra FFmpeg output arguments")))
        self.extra = QPlainTextEdit()
        self.extra.setPlaceholderText("-c:v libx264 -crf 18 -c:a aac")
        self.extra.setMaximumHeight(120)
        advanced_layout.addWidget(self.extra)
        advanced_layout.addWidget(QLabel(tr("Command preview")))
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        advanced_layout.addWidget(self.preview)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(1200)
        self.log.setMaximumHeight(120)
        root.addWidget(self.log)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        root.addWidget(self.progress)
        row = QHBoxLayout()
        self.status = QLabel(tr("Ready"))
        self.open_button = QPushButton(tr("Open output folder"))
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self.open_output)
        self.run_button = QPushButton(tr("Run FFmpeg"))
        self.run_button.clicked.connect(self.run_task)
        self.cancel_button = QPushButton(tr("Cancel"))
        self.cancel_button.setEnabled(False)
        self.cancel_button.clicked.connect(lambda: self.runner.cancel() if self.runner else None)
        row.addWidget(self.status, 1)
        row.addWidget(self.open_button)
        row.addWidget(self.run_button)
        row.addWidget(self.cancel_button)
        root.addLayout(row)
        self.signals = MediaSignals(self)
        self.signals.message.connect(self.log.appendPlainText)
        self.signals.progress.connect(lambda value: self.progress.setValue(int(value)))
        self.signals.result.connect(self.on_finished)
        self.tabs.currentChanged.connect(self.output_changed)
        self.extra.textChanged.connect(self.update_preview)
        self.source.textChanged.connect(self.update_preview)
        self.output.textChanged.connect(self.update_preview)
        self.operation_changed()

    def time_field(self):
        field = QDoubleSpinBox()
        field.setRange(0, 10_000_000)
        field.setDecimals(3)
        return field

    def set_source(self, filename):
        if self.busy:
            return
        self.source.setText(filename)
        self.output.setText(str(Path(filename).with_name(Path(filename).stem + ".processed.mp4")))
        self.inspect()

    def browse_source(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, self.tr("Input file"), self.source.text(), "Media (*.*)"
        )
        if filename:
            self.set_source(filename)

    def browse_output(self):
        filename, _ = QFileDialog.getSaveFileName(
            self, self.tr("Output file"), self.output.text(), "Files (*.*)"
        )
        if filename:
            self.output.setText(filename)

    def browse_subtitle(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, self.tr("Subtitle file"), "", "Subtitles (*.srt *.vtt *.ass *.ssa)"
        )
        if filename:
            self.subtitle_file.setText(filename)

    def operation_changed(self):
        operation = self.operation.currentData()
        if operation == "remux":
            self.video.setCurrentIndex(self.video.findData("copy"))
            self.audio.setCurrentIndex(self.audio.findData("copy"))
            self.normalize.setChecked(False)
            self.scale.setValue(0)
        elif operation == "audio":
            if self.container.currentData() not in {"m4a", "mp3", "opus", "flac", "wav"}:
                self.container.setCurrentIndex(self.container.findData("mp3"))
            codec = {"m4a": "aac", "mp3": "mp3", "opus": "opus", "flac": "flac", "wav": "pcm"}[
                self.container.currentData()
            ]
            self.audio.setCurrentIndex(self.audio.findData(codec))
        self.video.setEnabled(operation not in {"remux", "audio"})
        self.audio.setEnabled(operation != "remux")
        self.start.setEnabled(operation == "trim")
        self.end.setEnabled(operation == "trim")
        self.normalize.setEnabled(operation != "remux")
        self.codec_changed()
        self.output_changed()

    def codec_changed(self):
        encode = self.video.currentData() != "copy" and self.operation.currentData() not in {"remux", "audio"}
        self.crf.setEnabled(encode)
        self.scale.setEnabled(encode)

    def output_changed(self):
        tab = self.tabs.currentIndex()
        suffix = self.container.currentData()
        if (
            tab == 0
            and suffix in {"m4a", "mp3", "opus", "flac", "wav"}
            and self.operation.currentData() != "audio"
        ):
            self.operation.setCurrentIndex(self.operation.findData("audio"))
            return
        if (
            tab == 0
            and self.operation.currentData() == "audio"
            and suffix in {"m4a", "mp3", "opus", "flac", "wav"}
        ):
            codec = {"m4a": "aac", "mp3": "mp3", "opus": "opus", "flac": "flac", "wav": "pcm"}[suffix]
            self.audio.setCurrentIndex(self.audio.findData(codec))
        if tab == 0 and suffix == "webm" and self.operation.currentData() == "convert":
            self.audio.setCurrentIndex(self.audio.findData("opus"))
            self.video.setCurrentIndex(self.video.findData("vp9"))
        if tab == 2 and self.subtitle_mode.currentData() == "extract_subtitle":
            suffix = self.subtitle_format.currentData()
        elif tab == 3:
            suffix = self.thumbnail_format.currentData()
        elif tab == 1 and self.source.text():
            suffix = Path(self.source.text()).suffix.lstrip(".") or "mp4"
        if self.output.text() and suffix:
            self.output.setText(str(Path(self.output.text()).with_suffix("." + suffix)))
        self.run_button.setEnabled(tab != 4 and not self.busy)
        self.update_preview()

    def make_task(self):
        tab = self.tabs.currentIndex()
        operation = {1: "metadata", 2: self.subtitle_mode.currentData(), 3: "thumbnail", 5: "advanced"}.get(
            tab, self.operation.currentData()
        )
        tags = (
            {key: field.text() for key, field in self.tags.items() if field.text()}
            if operation == "metadata"
            else {}
        )
        if operation == "metadata" and self.description.toPlainText():
            tags["description"] = self.description.toPlainText()
        return MediaTask(
            source=self.source.text().strip(),
            output=self.output.text().strip(),
            operation=operation,
            video_codec=self.video.currentData() if operation in {"convert", "trim", "advanced"} else "copy",
            audio_codec=self.audio.currentData()
            if operation in {"convert", "trim", "audio", "advanced"}
            else "copy",
            audio_kbps=self.bitrate.value(),
            crf=self.crf.value(),
            scale_height=self.scale.value()
            if self.scale.isEnabled() and operation in {"convert", "trim", "advanced"}
            else 0,
            start=self.thumbnail_time.value()
            if operation == "thumbnail"
            else self.start.value()
            if operation == "trim"
            else 0,
            end=self.end.value() if operation == "trim" else 0,
            normalize=self.normalize.isChecked() and operation in {"convert", "trim", "audio", "advanced"},
            keep_metadata=self.keep_metadata.isChecked(),
            metadata=tags,
            subtitle=self.subtitle_file.text().strip(),
            subtitle_track=self.subtitle_track.value() - 1,
            subtitle_language=self.subtitle_language.text().strip(),
            extra_args=QProcess.splitCommand(self.extra.toPlainText()) if operation == "advanced" else [],
        )

    def update_preview(self):
        if not hasattr(self, "preview"):
            return
        if not self.source.text() or not self.output.text():
            self.preview.clear()
            return
        try:
            command = processing_command(self.paths, self.make_task(), Path(self.output.text()), self.info)
            command[command.index("-y")] = "-n"
            self.preview.setPlainText(
                subprocess.list2cmdline(command) if sys.platform == "win32" else shlex.join(command)
            )
        except (ValueError, FileNotFoundError):
            self.preview.clear()

    def inspect(self):
        if not self.busy and self.source.text():
            self.launch(None)

    def run_task(self):
        if self.busy:
            return
        task = self.make_task()
        try:
            if Path(task.source).resolve() == Path(task.output).resolve():
                raise ValueError("The output must be different from the input file.")
            if Path(task.output).exists():
                if (
                    QMessageBox.question(
                        self, self.tr("Output file"), self.tr("Replace the existing output file?")
                    )
                    != QMessageBox.StandardButton.Yes
                ):
                    return
                task.overwrite = True
            task.validate()
        except (ValueError, OSError) as exc:
            QMessageBox.warning(self, self.tr("Error"), str(exc))
            return
        self.launch(task)

    def launch(self, task):
        self.busy = True
        self.runner = MediaRunner()
        self.set_busy(True)
        self.progress.setValue(0)
        self.status.setText(self.tr("Working…"))
        source = self.source.text().strip()

        def work():
            try:
                info = (
                    execute_task(
                        self.paths,
                        task,
                        self.runner.run,
                        self.signals.message.emit,
                        self.signals.progress.emit,
                    )
                    if task
                    else inspect_media(self.paths, Path(source), self.runner.run)
                )
                if task:
                    info.setdefault("format", {})["filename"] = task.output
                self.signals.result.emit(True, {"info": info, "output": task.output if task else ""})
            except Stopped:
                self.signals.result.emit(False, {"error": self.tr("Cancelled"), "cancelled": True})
            except Exception as exc:
                self.signals.result.emit(False, {"error": str(exc)})

        self.worker = threading.Thread(target=work, name="sonata-ffmpeg")
        self.worker.start()

    def set_busy(self, busy):
        for widget in (
            self.source,
            self.output,
            self.source_button,
            self.output_button,
            self.inspect_button,
            self.tabs,
        ):
            widget.setEnabled(not busy)
        self.run_button.setEnabled(not busy and self.tabs.currentIndex() != 4)
        self.cancel_button.setEnabled(busy)

    def on_finished(self, success, result):
        self.busy = False
        self.set_busy(False)
        self.status.setText(
            self.tr("Success" if success else "Cancelled" if result.get("cancelled") else "Error")
        )
        if success:
            self.info = result["info"]
            self.populate_info()
            self.last_output = result.get("output", "")
            self.open_button.setEnabled(bool(self.last_output))
            if self.last_output:
                self.progress.setValue(100)
                self.log.appendPlainText(self.tr("Saved: {path}", path=self.last_output))
        else:
            self.log.appendPlainText(result["error"])
        self.update_preview()

    def populate_info(self):
        self.tree.clear()

        def section(label, values):
            parent = QTreeWidgetItem(self.tree, [self.tr(label)])
            for key, value in values.items():
                if value is None:
                    continue
                text = (
                    json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
                )
                item = QTreeWidgetItem(parent, [str(key), text.replace("\n", " ")[:400]])
                item.setToolTip(1, text)
            parent.setExpanded(True)

        fmt = self.info.get("format", {})
        section("File", {k: v for k, v in fmt.items() if k != "tags"})
        for index, stream in enumerate(self.info.get("streams", []), 1):
            section(f"{self.tr('Stream')} {index} · {stream.get('codec_type', '')}", stream)
        tags = {str(key).lower(): str(value) for key, value in fmt.get("tags", {}).items()}
        section("Metadata", tags)
        if self.info.get("chapters"):
            section("Chapters", {str(i + 1): c for i, c in enumerate(self.info["chapters"])})
        for key, field in self.tags.items():
            field.setText(tags.get(key, ""))
        self.description.setPlainText(tags.get("description", tags.get("synopsis", "")))

    def save_probe(self):
        if not self.info:
            return
        filename, _ = QFileDialog.getSaveFileName(
            self, self.tr("Save probe JSON…"), "media-info.json", "JSON (*.json)"
        )
        if filename:
            try:
                Path(filename).write_text(
                    json.dumps(self.info, ensure_ascii=False, indent=2), encoding="utf-8"
                )
            except OSError as exc:
                QMessageBox.warning(self, self.tr("Error"), str(exc))

    def open_output(self):
        if self.last_output:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self.last_output).parent)))

    def closeEvent(self, event):
        if self.busy:
            if (
                QMessageBox.question(
                    self,
                    self.tr("FFmpeg tools"),
                    self.tr("Cancel the current FFmpeg task and close this window?"),
                )
                != QMessageBox.StandardButton.Yes
            ):
                event.ignore()
                return
            self.runner.cancel()
            self.worker.join(timeout=10)
            if self.worker.is_alive():
                event.ignore()
                return
            self.busy = False
        event.accept()

    def reject(self):
        self.close()
