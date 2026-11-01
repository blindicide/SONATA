from dataclasses import replace

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from sonata.models import DownloadOptions


def combo(items, selected):
    widget = QComboBox()
    for label, value in items:
        widget.addItem(label, value)
    widget.setCurrentIndex(max(0, widget.findData(selected)))
    return widget


class Preferences(QDialog):
    def __init__(self, parent, options: DownloadOptions):
        super().__init__(parent)
        self.options = options
        self.tr = parent.tr
        tr = self.tr
        self.setWindowTitle(tr("Preferences"))
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)
        general, downloads, extras = QWidget(), QWidget(), QWidget()
        tabs.addTab(general, tr("General"))
        tabs.addTab(downloads, tr("Downloads"))
        tabs.addTab(extras, tr("Subtitles and metadata"))
        form = QFormLayout(general)
        self.theme = combo(
            [(tr("Light"), "light"), (tr("Dark"), "dark")], parent.db.setting("theme", "light")
        )
        self.language = combo([("English", "en"), ("Русский", "ru")], parent.db.setting("language", "en"))
        self.concurrent = QSpinBox()
        self.concurrent.setRange(1, 8)
        self.concurrent.setValue(parent.engine.concurrency)
        form.addRow(tr("Theme"), self.theme)
        form.addRow(tr("Language"), self.language)
        form.addRow(tr("Concurrent downloads"), self.concurrent)
        form = QFormLayout(downloads)
        self.template = QLineEdit(options.template)
        self.video = combo(
            [(tr("Any"), "any"), ("H.264", "h264"), ("VP9", "vp9"), ("AV1", "av1")], options.video_codec
        )
        self.audio = combo(
            [(x.upper(), x) for x in ("mp3", "m4a", "opus", "flac", "wav", "best")], options.audio_codec
        )
        self.rate = QSpinBox()
        self.rate.setRange(0, 1_000_000)
        self.rate.setValue(options.rate_kib)
        self.retries = QSpinBox()
        self.retries.setRange(0, 50)
        self.retries.setValue(options.retries)
        self.playlist = QCheckBox(tr("Expand playlists and channels"))
        self.playlist.setChecked(options.playlist)
        form.addRow(tr("Filename template"), self.template)
        hint = QLabel(tr("Use yt-dlp fields, including %(id)s and %(ext)s. Folders are set above."))
        hint.setWordWrap(True)
        form.addRow(hint)
        form.addRow(tr("Video codec"), self.video)
        form.addRow(tr("Audio format"), self.audio)
        form.addRow(tr("Rate limit (KiB/s, 0 = unlimited)"), self.rate)
        form.addRow(tr("Retries"), self.retries)
        form.addRow(self.playlist)
        hint = QLabel(tr("Formats depend on the source. Remuxing does not re-encode the video."))
        hint.setWordWrap(True)
        form.addRow(hint)
        form = QFormLayout(extras)
        self.subs = QCheckBox(tr("Download subtitles"))
        self.subs.setChecked(options.subtitles)
        self.auto = QCheckBox(tr("Include automatic captions"))
        self.auto.setChecked(options.automatic_subtitles)
        self.langs = QLineEdit(options.subtitle_languages)
        self.metadata = QCheckBox(tr("Embed metadata and save info JSON"))
        self.metadata.setChecked(options.metadata)
        self.thumbnail = QCheckBox(tr("Save thumbnail"))
        self.thumbnail.setChecked(options.thumbnail)
        form.addRow(self.subs)
        form.addRow(self.auto)
        form.addRow(tr("Subtitle languages"), self.langs)
        form.addRow(self.metadata)
        form.addRow(self.thumbnail)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(tr("Save"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("Cancel"))
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def save(self):
        try:
            self.options = replace(
                self.options,
                template=self.template.text(),
                video_codec=self.video.currentData(),
                audio_codec=self.audio.currentData(),
                rate_kib=self.rate.value(),
                retries=self.retries.value(),
                playlist=self.playlist.isChecked(),
                subtitles=self.subs.isChecked(),
                automatic_subtitles=self.auto.isChecked(),
                subtitle_languages=self.langs.text(),
                metadata=self.metadata.isChecked(),
                thumbnail=self.thumbnail.isChecked(),
            ).validate()
        except ValueError as exc:
            QMessageBox.warning(self, self.tr("Error"), str(exc))
            return
        self.accept()
