"""History list widget showing past recordings."""

from typing import Optional

from loguru import logger
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from src.core.database import Recording
from src.core.recording_titles import display_recording_title, format_recording_title
from src.ui.theme import (
    ACCENT_PRIMARY,
    BG_BASE, BG_SURFACE_2, BG_SURFACE_3,
    BORDER_DEFAULT,
    FONT_MONO,
    RADIUS_LG, RADIUS_SM,
    STATUS_BADGE,
    TEXT_PRIMARY, TEXT_SECONDARY, TEXT_TERTIARY,
    badge_style, _hex_to_rgba,
)
from src.ui.i18n import tr


class RecordingListItem(QWidget):
    """Custom widget for recording list item with card design."""

    def __init__(
        self,
        recording: Recording,
        is_recording: bool = False,
        file_missing: bool = False,
        match_text: str = "",
        parent=None,
    ):
        super().__init__(parent)
        self.recording = recording
        self._is_recording = is_recording
        self._file_missing = file_missing
        self._match_text = match_text
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        # Row 1: Title + status badge
        top_row = QHBoxLayout()
        top_row.setSpacing(8)

        # Title
        title = self.recording.title
        display_title = display_recording_title(self.recording)

        title_color = TEXT_TERTIARY if self._file_missing else TEXT_PRIMARY
        self.title_label = QLabel(display_title)
        self.title_label.setStyleSheet(f"""
            font-weight: 600; font-size: 13px; color: {title_color};
            background: transparent;
        """)
        self.title_label.setWordWrap(False)
        self.title_label.setMaximumWidth(200)

        top_row.addWidget(self.title_label, stretch=1)

        # Status badge - show a missing-file state before the normal status.
        if self._file_missing:
            status_label = QLabel(tr("Файл удалён"))
            status_label.setStyleSheet(badge_style("error"))
        elif self._is_recording:
            status_label = QLabel(STATUS_BADGE["recording"]["text"])
            status_label.setStyleSheet(badge_style("recording"))
        else:
            status = self.recording.status or "pending"
            badge_cfg = STATUS_BADGE.get(status, STATUS_BADGE["pending"])
            status_label = QLabel(badge_cfg["text"])
            status_label.setStyleSheet(badge_style(status))
        top_row.addWidget(status_label)

        layout.addLayout(top_row)

        if self._match_text:
            snippet = " ".join(self._match_text.split())
            if len(snippet) > 130:
                snippet = snippet[:127].rstrip() + "..."
            match_label = QLabel(snippet)
            match_label.setWordWrap(True)
            match_label.setStyleSheet(f"""
                color: {TEXT_SECONDARY}; font-size: 11px;
                background: transparent; line-height: 1.4;
            """)
            layout.addWidget(match_label)

        # Row 2: Date + Duration (only when it is not already the title)
        date_str = ""
        if self.recording.created_at and display_title != format_recording_title(
            self.recording.created_at
        ):
            if isinstance(self.recording.created_at, str):
                date_str = self.recording.created_at
            else:
                date_str = self.recording.created_at.strftime("%d %b %Y")

        bottom_row = QHBoxLayout()
        bottom_row.setSpacing(8)

        if date_str:
            date_label = QLabel(date_str)
            date_label.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: 11px; background: transparent;")
            bottom_row.addWidget(date_label)

        bottom_row.addStretch()

        # Duration
        if self.recording.duration_seconds:
            minutes = self.recording.duration_seconds // 60
            seconds = self.recording.duration_seconds % 60
            duration_str = f"{minutes}:{seconds:02d}"
        else:
            duration_str = "--:--"

        duration_label = QLabel(duration_str)
        duration_label.setStyleSheet(f"""
            color: {TEXT_SECONDARY}; font-size: 11px;
            font-family: {FONT_MONO}; background: transparent;
        """)
        bottom_row.addWidget(duration_label)

        layout.addLayout(bottom_row)


class HistoryListWidget(QWidget):
    """Widget displaying recording history."""

    recording_selected = pyqtSignal(Recording)
    recording_deleted = pyqtSignal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._recordings: list[Recording] = []
        self._current_recording_id: Optional[int] = None
        self._missing_file_ids: set[int] = set()
        self._match_text_by_id: dict[int, str] = {}
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # List widget
        self.list_widget = QListWidget()
        self.list_widget.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.list_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list_widget.customContextMenuRequested.connect(self._show_context_menu)
        self.list_widget.itemClicked.connect(self._on_item_clicked)
        self.list_widget.setStyleSheet(f"""
            QListWidget {{
                background-color: {BG_BASE};
                border: none;
                outline: none;
            }}
            QListWidget::item {{
                padding: 2px 4px;
                margin-bottom: 4px;
                border: none;
                border-radius: {RADIUS_LG}px;
            }}
            QListWidget::item:selected {{
                background-color: {_hex_to_rgba(ACCENT_PRIMARY, 38)};
            }}
            QListWidget::item:hover:!selected {{
                background-color: {BG_SURFACE_2};
            }}
        """)

        layout.addWidget(self.list_widget)

        # Empty state label (hidden by default)
        self._empty_label = QLabel(tr("Нет записей\nНажмите кнопку для начала"))
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setStyleSheet(f"color: {TEXT_TERTIARY}; font-size: 13px;")
        self._empty_label.setVisible(False)
        layout.addWidget(self._empty_label)

    def set_recordings(self, recordings: list[Recording], match_text_by_id: Optional[dict[int, str]] = None):
        self._recordings = recordings
        self._match_text_by_id = match_text_by_id or {}
        self._missing_file_ids = set()
        self._refresh_list()

    def _refresh_list(self):
        self.list_widget.clear()

        if not self._recordings:
            self._empty_label.setVisible(True)
            self.list_widget.setVisible(False)
            return

        self._empty_label.setVisible(False)
        self.list_widget.setVisible(True)

        for recording in self._recordings:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, recording)

            is_recording = (
                self._current_recording_id is not None
                and recording.id == self._current_recording_id
            )
            file_missing = recording.id in self._missing_file_ids
            match_text = self._match_text_by_id.get(recording.id or 0, "")
            widget = RecordingListItem(
                recording,
                is_recording=is_recording,
                file_missing=file_missing,
                match_text=match_text,
            )
            item.setSizeHint(widget.sizeHint())

            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, widget)

    def set_current_recording_id(self, recording_id: Optional[int]):
        self._current_recording_id = recording_id
        self._refresh_list()

    def _on_item_clicked(self, item: QListWidgetItem):
        recording = item.data(Qt.ItemDataRole.UserRole)
        if recording:
            self.recording_selected.emit(recording)

    def _show_context_menu(self, position):
        item = self.list_widget.itemAt(position)
        if not item:
            return

        recording = item.data(Qt.ItemDataRole.UserRole)
        if not recording:
            return

        menu = QMenu(self)

        open_action = menu.addAction(tr("Открыть"))
        open_action.triggered.connect(lambda: self._emit_selected(recording))

        menu.addSeparator()

        delete_action = menu.addAction(tr("Удалить"))
        if recording.id == self._current_recording_id:
            delete_action.setEnabled(False)
            delete_action.setToolTip(tr("Нельзя удалить активную запись"))
        else:
            delete_action.triggered.connect(lambda: self._emit_deleted(recording.id))

        menu.exec(self.list_widget.mapToGlobal(position))

    def _emit_selected(self, recording: Recording):
        self.recording_selected.emit(recording)

    def _emit_deleted(self, recording_id: int):
        logger.info(f"Delete requested for recording {recording_id}")

        if recording_id == self._current_recording_id:
            QMessageBox.warning(
                self,
                tr("Запись активна"),
                tr("Нельзя удалить запись, пока она выполняется."),
            )
            logger.warning(f"Deletion blocked for active recording {recording_id}")
            return

        reply = QMessageBox.question(
            self,
            tr("Подтверждение"),
            tr("Удалить запись и все связанные данные?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            logger.info(f"User confirmed deletion, emitting signal for {recording_id}")
            self.recording_deleted.emit(recording_id)
        else:
            logger.info(f"User cancelled deletion of {recording_id}")

    def is_file_missing(self, recording_id: int) -> bool:
        return recording_id in self._missing_file_ids

    def get_selected_recording(self) -> Optional[Recording]:
        item = self.list_widget.currentItem()
        if item:
            return item.data(Qt.ItemDataRole.UserRole)
        return None
