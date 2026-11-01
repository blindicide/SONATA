from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemDelegate,
    QComboBox,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionComboBox,
    QStyleOptionProgressBar,
    QTableWidget,
)


def resolution_label(row):
    return f"{row['height']}p · {row['width']}×{row['height']}" if row.get("width") else f"{row['height']}p"


class ResolutionDelegate(QStyledItemDelegate):
    def __init__(self, parent, on_change):
        super().__init__(parent)
        self.on_change = on_change

    def paint(self, painter, option, index):
        choices = index.data(Qt.ItemDataRole.UserRole)
        if not choices:
            return super().paint(painter, option, index)
        combo = QStyleOptionComboBox()
        combo.rect = option.rect.adjusted(2, 2, -2, -2)
        combo.palette = option.palette
        combo.currentText = index.data() or ""
        combo.state = option.state
        if not index.flags() & Qt.ItemFlag.ItemIsEditable:
            combo.state &= ~QStyle.StateFlag.State_Enabled
        option.widget.style().drawComplexControl(
            QStyle.ComplexControl.CC_ComboBox, combo, painter, option.widget
        )
        option.widget.style().drawControl(
            QStyle.ControlElement.CE_ComboBoxLabel, combo, painter, option.widget
        )

    def editorEvent(self, event, model, option, index):
        if (
            event.type() == QEvent.Type.MouseButtonRelease
            and event.button() == Qt.MouseButton.LeftButton
            and index.flags() & Qt.ItemFlag.ItemIsEditable
        ):
            self.parent().edit(index)
            return True
        return super().editorEvent(event, model, option, index)

    def createEditor(self, parent, option, index):
        editor = QComboBox(parent)
        for row in index.data(Qt.ItemDataRole.UserRole) or []:
            editor.addItem(resolution_label(row), row["height"])

        def commit(_index):
            self.commitData.emit(editor)
            self.closeEditor.emit(editor, QAbstractItemDelegate.EndEditHint.NoHint)

        editor.activated.connect(commit)
        QTimer.singleShot(0, editor.showPopup)
        return editor

    def setEditorData(self, editor, index):
        editor.setCurrentIndex(max(0, editor.findData(index.data(Qt.ItemDataRole.UserRole + 1))))

    def setModelData(self, editor, model, index):
        height = editor.currentData()
        if height is not None and self.on_change(index.data(Qt.ItemDataRole.UserRole + 2), height):
            model.setData(index, editor.currentText())


class ProgressDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        value = index.data(Qt.ItemDataRole.UserRole)
        if value is None:
            return super().paint(painter, option, index)
        self.initStyleOption(option, index)
        option.widget.style().drawPrimitive(
            QStyle.PrimitiveElement.PE_PanelItemViewItem, option, painter, option.widget
        )
        progress = QStyleOptionProgressBar()
        progress.rect = option.rect.adjusted(5, 5, -5, -5)
        progress.minimum, progress.maximum = 0, 1000
        progress.progress = int(float(value) * 10)
        progress.text = f"{float(value):.1f}%"
        progress.textVisible = True
        progress.textAlignment = Qt.AlignmentFlag.AlignCenter
        progress.palette = option.palette
        option.widget.style().drawControl(
            QStyle.ControlElement.CE_ProgressBar, progress, painter, option.widget
        )


def table(headers):
    widget = QTableWidget(0, len(headers))
    widget.setHorizontalHeaderLabels(headers)
    widget.setAlternatingRowColors(True)
    widget.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    widget.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
    widget.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    widget.setSortingEnabled(True)
    widget.setShowGrid(False)
    widget.verticalHeader().setVisible(False)
    widget.verticalHeader().setDefaultSectionSize(28)
    return widget


def size_text(value: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if value < 1024:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{value:.1f} PiB"


def eta_text(seconds) -> str:
    if seconds is None:
        return "—"
    seconds = max(0, int(seconds))
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}" if hours else f"{minutes:02}:{seconds:02}"
