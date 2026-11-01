from PySide6.QtCore import Qt
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionProgressBar, QTableWidget


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
