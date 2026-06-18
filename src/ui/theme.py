"""Centralized design system for Meeting Note UI."""

from src.ui.i18n import tr


# === Surface Layers (background elevation) ===
BG_BASE = "#121212"
BG_SURFACE_1 = "#1a1a1a"
BG_SURFACE_2 = "#222222"
BG_SURFACE_3 = "#2a2a2a"
BG_SURFACE_4 = "#333333"
BG_OVERLAY = "#3a3a3a"

# === Text Colors ===
TEXT_PRIMARY = "#e8e8e8"
TEXT_SECONDARY = "#a0a0a0"
TEXT_TERTIARY = "#6b6b6b"
TEXT_INVERSE = "#121212"

# === Accent Colors ===
ACCENT_PRIMARY = "#6c5ce7"
ACCENT_PRIMARY_HOVER = "#7d6ff0"
ACCENT_PRIMARY_PRESSED = "#5a4bd6"
ACCENT_SECONDARY = "#00cec9"

# === Semantic Colors ===
STATUS_RECORDING = "#ff6b6b"
STATUS_PAUSED = "#feca57"
STATUS_SUCCESS = "#00b894"
STATUS_ERROR = "#ff6b6b"
STATUS_PROCESSING = "#74b9ff"
STATUS_PENDING = "#fdcb6e"

# === Borders ===
BORDER_SUBTLE = "#2a2a2a"
BORDER_DEFAULT = "#333333"

# === Spacing (4px grid) ===
SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 12
SPACE_LG = 16
SPACE_XL = 24
SPACE_2XL = 32

# === Border Radius ===
RADIUS_SM = 4
RADIUS_MD = 8
RADIUS_LG = 12
RADIUS_XL = 16
RADIUS_ROUND = 20

# === Font family ===
FONT_FAMILY = "'Segoe UI Variable', 'Segoe UI', sans-serif"
FONT_MONO = "'Cascadia Mono', 'Consolas', monospace"

# === Speaker colors ===
SPEAKER_COLORS = [
    "#6c5ce7", "#00cec9", "#fd79a8", "#fdcb6e", "#00b894", "#74b9ff",
]

# === Status badge config ===
STATUS_BADGE = {
    "recording": {"color": STATUS_RECORDING, "text": tr("Запись"), "bg_alpha": 38},
    "pending": {"color": STATUS_PENDING, "text": tr("Ожидание"), "bg_alpha": 38},
    "transcribing": {"color": STATUS_PROCESSING, "text": tr("Транскрибация"), "bg_alpha": 38},
    "transcribed": {"color": STATUS_PROCESSING, "text": tr("Текст готов"), "bg_alpha": 38},
    "summarizing": {"color": STATUS_PROCESSING, "text": tr("Саммари"), "bg_alpha": 38},
    "summary_failed": {"color": STATUS_PENDING, "text": tr("Без саммари"), "bg_alpha": 38},
    "completed": {"color": STATUS_SUCCESS, "text": tr("Завершено"), "bg_alpha": 38},
    "error": {"color": STATUS_ERROR, "text": tr("Сбой"), "bg_alpha": 38},
}


def _hex_to_rgba(hex_color: str, alpha: int) -> str:
    """Convert hex color to rgba string for QSS."""
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r}, {g}, {b}, {alpha})"


def badge_style(status: str) -> str:
    """Return QSS for a status badge pill."""
    cfg = STATUS_BADGE.get(status, STATUS_BADGE["pending"])
    bg = _hex_to_rgba(cfg["color"], cfg["bg_alpha"])
    return (
        f"background-color: {bg}; color: {cfg['color']}; "
        f"padding: 2px 8px; border-radius: {RADIUS_SM}px; "
        f"font-size: 11px; font-weight: 500;"
    )


def get_global_stylesheet() -> str:
    """Return the complete application QSS."""
    return f"""
    /* === Base === */
    QWidget {{
        background-color: {BG_BASE};
        color: {TEXT_PRIMARY};
        font-family: {FONT_FAMILY};
        font-size: 13px;
    }}

    QMainWindow {{
        background-color: {BG_BASE};
    }}

    /* === Menu Bar === */
    QMenuBar {{
        background-color: {BG_SURFACE_1};
        border-bottom: 1px solid {BORDER_SUBTLE};
        padding: 2px 0;
    }}
    QMenuBar::item {{
        padding: 6px 12px;
        border-radius: {RADIUS_SM}px;
        margin: 2px;
    }}
    QMenuBar::item:selected {{
        background-color: {_hex_to_rgba(ACCENT_PRIMARY, 50)};
    }}

    QMenu {{
        background-color: {BG_SURFACE_3};
        border: 1px solid {BORDER_DEFAULT};
        border-radius: {RADIUS_MD}px;
        padding: {SPACE_XS}px;
    }}
    QMenu::item {{
        padding: 8px 24px;
        border-radius: {RADIUS_SM}px;
        margin: 2px 4px;
    }}
    QMenu::item:selected {{
        background-color: {_hex_to_rgba(ACCENT_PRIMARY, 50)};
    }}
    QMenu::separator {{
        height: 1px;
        background-color: {BORDER_DEFAULT};
        margin: 4px 8px;
    }}

    /* === Buttons === */
    QPushButton {{
        background-color: {BG_SURFACE_4};
        border: none;
        border-radius: {RADIUS_MD}px;
        padding: 8px 16px;
        min-width: 70px;
        color: {TEXT_PRIMARY};
    }}
    QPushButton:hover {{
        background-color: {BG_OVERLAY};
    }}
    QPushButton:pressed {{
        background-color: {BG_SURFACE_3};
    }}
    QPushButton:disabled {{
        background-color: {BG_SURFACE_2};
        color: {TEXT_TERTIARY};
    }}

    /* === Inputs === */
    QLineEdit, QTextEdit, QPlainTextEdit {{
        background-color: {BG_SURFACE_3};
        border: 1px solid transparent;
        border-radius: {RADIUS_MD}px;
        padding: 8px 12px;
        selection-background-color: {_hex_to_rgba(ACCENT_PRIMARY, 100)};
        color: {TEXT_PRIMARY};
    }}
    QLineEdit:focus, QTextEdit:focus {{
        border: 1px solid {_hex_to_rgba(ACCENT_PRIMARY, 128)};
        background-color: {BG_SURFACE_4};
    }}

    /* === Combo Box === */
    QComboBox {{
        background-color: {BG_SURFACE_3};
        border: 1px solid transparent;
        border-radius: {RADIUS_MD}px;
        padding: 8px 12px;
        color: {TEXT_PRIMARY};
    }}
    QComboBox:hover {{
        background-color: {BG_SURFACE_4};
    }}
    QComboBox::drop-down {{
        border: none;
        width: 20px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {BG_SURFACE_3};
        border: 1px solid {BORDER_DEFAULT};
        border-radius: {RADIUS_MD}px;
        selection-background-color: {_hex_to_rgba(ACCENT_PRIMARY, 80)};
    }}

    /* === Spin Box === */
    QSpinBox {{
        background-color: {BG_SURFACE_3};
        border: 1px solid transparent;
        border-radius: {RADIUS_MD}px;
        padding: 6px 10px;
        color: {TEXT_PRIMARY};
    }}
    QSpinBox:focus {{
        border: 1px solid {_hex_to_rgba(ACCENT_PRIMARY, 128)};
    }}

    /* === Checkbox === */
    QCheckBox {{
        spacing: 8px;
        color: {TEXT_PRIMARY};
    }}
    QCheckBox::indicator {{
        width: 18px;
        height: 18px;
        border-radius: {RADIUS_SM}px;
        border: 1px solid {BORDER_DEFAULT};
        background-color: {BG_SURFACE_3};
    }}
    QCheckBox::indicator:checked {{
        background-color: {ACCENT_PRIMARY};
        border: 1px solid {ACCENT_PRIMARY};
    }}
    QCheckBox::indicator:hover {{
        border: 1px solid {TEXT_TERTIARY};
    }}

    /* === Tab Widget === */
    QTabWidget::pane {{
        border: none;
        background-color: transparent;
        border-top: 1px solid {BORDER_SUBTLE};
    }}
    QTabBar::tab {{
        background-color: transparent;
        border: none;
        border-bottom: 2px solid transparent;
        padding: 10px 20px;
        margin-right: 4px;
        color: {TEXT_SECONDARY};
        font-size: 13px;
    }}
    QTabBar::tab:selected {{
        color: {TEXT_PRIMARY};
        border-bottom: 2px solid {ACCENT_PRIMARY};
    }}
    QTabBar::tab:hover:!selected {{
        color: {TEXT_PRIMARY};
        border-bottom: 2px solid {BORDER_DEFAULT};
    }}

    /* === Scroll Bars === */
    QScrollBar:vertical {{
        background-color: transparent;
        width: 8px;
        border-radius: 4px;
        margin: 2px;
    }}
    QScrollBar::handle:vertical {{
        background-color: {BG_SURFACE_4};
        border-radius: 4px;
        min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{
        background-color: {TEXT_TERTIARY};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: none;
    }}
    QScrollBar:horizontal {{
        background-color: transparent;
        height: 8px;
        border-radius: 4px;
        margin: 2px;
    }}
    QScrollBar::handle:horizontal {{
        background-color: {BG_SURFACE_4};
        border-radius: 4px;
        min-width: 30px;
    }}
    QScrollBar::handle:horizontal:hover {{
        background-color: {TEXT_TERTIARY};
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0px;
    }}
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
        background: none;
    }}

    /* === Progress Bar === */
    QProgressBar {{
        background-color: {BG_SURFACE_1};
        border: none;
        border-radius: {RADIUS_SM}px;
        text-align: center;
        color: {TEXT_PRIMARY};
        font-size: 11px;
    }}
    QProgressBar::chunk {{
        background-color: {ACCENT_PRIMARY};
        border-radius: {RADIUS_SM}px;
    }}

    /* === Status Bar === */
    QStatusBar {{
        background-color: {BG_SURFACE_1};
        border-top: 1px solid {BORDER_SUBTLE};
        color: {TEXT_SECONDARY};
    }}

    /* === Group Box === */
    QGroupBox {{
        border: none;
        border-radius: {RADIUS_LG}px;
        background-color: {BG_SURFACE_2};
        margin-top: 16px;
        padding: 16px;
        padding-top: 28px;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 12px;
        padding: 0 6px;
        color: {TEXT_PRIMARY};
        font-weight: 600;
    }}

    /* === Splitter === */
    QSplitter::handle {{
        background-color: transparent;
    }}
    QSplitter::handle:horizontal {{
        width: 4px;
    }}
    QSplitter::handle:hover {{
        background-color: {ACCENT_PRIMARY};
    }}

    /* === Tooltips === */
    QToolTip {{
        background-color: {BG_OVERLAY};
        color: {TEXT_PRIMARY};
        border: 1px solid {BORDER_DEFAULT};
        border-radius: {RADIUS_MD}px;
        padding: 6px 10px;
    }}

    /* === Dialogs === */
    QDialog {{
        background-color: {BG_BASE};
    }}
    QDialogButtonBox {{
        button-layout: 0;
    }}

    /* === Message Box === */
    QMessageBox {{
        background-color: {BG_SURFACE_1};
    }}
    """
