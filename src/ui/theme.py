"""Centralized design system for Meeting Note UI.

The palette follows the Windows app theme (light or dark) and is chosen once,
when this module is imported. Widgets import the tokens by name, so every
token below exists in both palettes. ``MEETING_NOTE_THEME=light|dark``
overrides the system choice (handy for screenshots and support).
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

from src.ui.i18n import tr


def _detect_theme_mode() -> str:
    override = os.environ.get("MEETING_NOTE_THEME", "").strip().lower()
    if override in {"light", "dark"}:
        return override
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            ) as key:
                value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return "light" if value else "dark"
        except OSError:
            pass
    return "light"


THEME_MODE = _detect_theme_mode()
IS_DARK = THEME_MODE == "dark"


# Brand colors come from the app icon: violet core, teal wave, pink spark.
_LIGHT = {
    # Surfaces: canvas -> cards -> wells
    "BG_BASE": "#F4F5F9",
    "BG_SURFACE_1": "#FFFFFF",
    "BG_SURFACE_2": "#FFFFFF",
    "BG_SURFACE_3": "#F1F2F7",
    "BG_SURFACE_4": "#E6E8F0",
    "BG_OVERLAY": "#FFFFFF",
    "BG_FIELD": "#FFFFFF",
    "BG_HOVER": "#F1F2F7",
    "BG_PRESSED": "#E6E8F0",
    # Text
    "TEXT_PRIMARY": "#1A1C27",
    "TEXT_SECONDARY": "#5A5F71",
    "TEXT_TERTIARY": "#8C91A3",
    "TEXT_INVERSE": "#FFFFFF",
    "TEXT_ON_ACCENT": "#FFFFFF",
    # Accents
    "ACCENT_PRIMARY": "#5B3BF0",
    "ACCENT_PRIMARY_HOVER": "#6A4DF6",
    "ACCENT_PRIMARY_PRESSED": "#4A2DD6",
    "ACCENT_SECONDARY": "#0A928A",
    "ACCENT_PINK": "#D6409F",
    # Status
    "STATUS_RECORDING": "#EE3F5C",
    "STATUS_PAUSED": "#E0960A",
    "STATUS_SUCCESS": "#10A26E",
    "STATUS_ERROR": "#E5484D",
    "STATUS_PROCESSING": "#2F78E8",
    "STATUS_PENDING": "#D48A04",
    # Lines
    "BORDER_SUBTLE": "#E9EBF1",
    "BORDER_DEFAULT": "#DCDFE8",
    "BORDER_STRONG": "#C3C7D4",
    # Search highlight in transcripts
    "HIGHLIGHT_BG": "#FFE27A",
    "HIGHLIGHT_FG": "#1A1C27",
}

_DARK = {
    "BG_BASE": "#0F1014",
    "BG_SURFACE_1": "#17181E",
    "BG_SURFACE_2": "#1B1D24",
    "BG_SURFACE_3": "#22252E",
    "BG_SURFACE_4": "#2C2F3A",
    "BG_OVERLAY": "#20222A",
    "BG_FIELD": "#1B1D24",
    "BG_HOVER": "#22252E",
    "BG_PRESSED": "#2C2F3A",
    "TEXT_PRIMARY": "#ECEDF3",
    "TEXT_SECONDARY": "#A4A9B8",
    "TEXT_TERTIARY": "#6E7383",
    "TEXT_INVERSE": "#0F1014",
    "TEXT_ON_ACCENT": "#FFFFFF",
    "ACCENT_PRIMARY": "#7C63FF",
    "ACCENT_PRIMARY_HOVER": "#8D78FF",
    "ACCENT_PRIMARY_PRESSED": "#6A50F0",
    "ACCENT_SECONDARY": "#2DD4C8",
    "ACCENT_PINK": "#FF8AD8",
    "STATUS_RECORDING": "#FF5C77",
    "STATUS_PAUSED": "#F5B73B",
    "STATUS_SUCCESS": "#34C789",
    "STATUS_ERROR": "#FF6369",
    "STATUS_PROCESSING": "#5B9DFF",
    "STATUS_PENDING": "#F0B43C",
    "BORDER_SUBTLE": "#22252E",
    "BORDER_DEFAULT": "#2E323D",
    "BORDER_STRONG": "#3D4251",
    "HIGHLIGHT_BG": "#F5C84C",
    "HIGHLIGHT_FG": "#111216",
}

_PALETTE = _DARK if IS_DARK else _LIGHT

# === Surface Layers (background elevation) ===
BG_BASE = _PALETTE["BG_BASE"]            # window canvas
BG_SURFACE_1 = _PALETTE["BG_SURFACE_1"]  # panels and cards
BG_SURFACE_2 = _PALETTE["BG_SURFACE_2"]  # cards inside content and dialogs
BG_SURFACE_3 = _PALETTE["BG_SURFACE_3"]  # wells: meters, slider grooves
BG_SURFACE_4 = _PALETTE["BG_SURFACE_4"]  # stronger wells, scrollbar handles
BG_OVERLAY = _PALETTE["BG_OVERLAY"]      # menus, popups, notifications
BG_FIELD = _PALETTE["BG_FIELD"]          # text inputs
BG_HOVER = _PALETTE["BG_HOVER"]
BG_PRESSED = _PALETTE["BG_PRESSED"]

# === Text Colors ===
TEXT_PRIMARY = _PALETTE["TEXT_PRIMARY"]
TEXT_SECONDARY = _PALETTE["TEXT_SECONDARY"]
TEXT_TERTIARY = _PALETTE["TEXT_TERTIARY"]
TEXT_INVERSE = _PALETTE["TEXT_INVERSE"]
TEXT_ON_ACCENT = _PALETTE["TEXT_ON_ACCENT"]

# === Accent Colors ===
ACCENT_PRIMARY = _PALETTE["ACCENT_PRIMARY"]
ACCENT_PRIMARY_HOVER = _PALETTE["ACCENT_PRIMARY_HOVER"]
ACCENT_PRIMARY_PRESSED = _PALETTE["ACCENT_PRIMARY_PRESSED"]
ACCENT_SECONDARY = _PALETTE["ACCENT_SECONDARY"]
ACCENT_PINK = _PALETTE["ACCENT_PINK"]

# === Semantic Colors ===
STATUS_RECORDING = _PALETTE["STATUS_RECORDING"]
STATUS_PAUSED = _PALETTE["STATUS_PAUSED"]
STATUS_SUCCESS = _PALETTE["STATUS_SUCCESS"]
STATUS_ERROR = _PALETTE["STATUS_ERROR"]
STATUS_PROCESSING = _PALETTE["STATUS_PROCESSING"]
STATUS_PENDING = _PALETTE["STATUS_PENDING"]

# === Borders ===
BORDER_SUBTLE = _PALETTE["BORDER_SUBTLE"]
BORDER_DEFAULT = _PALETTE["BORDER_DEFAULT"]
BORDER_STRONG = _PALETTE["BORDER_STRONG"]

# === Search highlight ===
HIGHLIGHT_BG = _PALETTE["HIGHLIGHT_BG"]
HIGHLIGHT_FG = _PALETTE["HIGHLIGHT_FG"]

# === Spacing (4px grid) ===
SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 12
SPACE_LG = 16
SPACE_XL = 24
SPACE_2XL = 32

# === Border Radius ===
RADIUS_SM = 6
RADIUS_MD = 10
RADIUS_LG = 14
RADIUS_XL = 18
RADIUS_ROUND = 20

# === Font family ===
FONT_FAMILY = "'Segoe UI Variable Text', 'Segoe UI Variable', 'Segoe UI', sans-serif"
FONT_MONO = "'Cascadia Mono', 'Consolas', monospace"

# === Speaker colors ===
SPEAKER_COLORS = (
    ["#8F78FF", "#2DD4C8", "#FF8AD8", "#F5B73B", "#34C789", "#5B9DFF"]
    if IS_DARK
    else ["#5B3BF0", "#0A928A", "#C2378F", "#B87300", "#0E8F61", "#2F6FD6"]
)

# === Status badge config ===
_BADGE_ALPHA = 46 if IS_DARK else 26
STATUS_BADGE = {
    "recording": {"color": STATUS_RECORDING, "text": tr("Запись"), "bg_alpha": _BADGE_ALPHA},
    "pending": {"color": STATUS_PENDING, "text": tr("Ожидание"), "bg_alpha": _BADGE_ALPHA},
    "transcribing": {"color": STATUS_PROCESSING, "text": tr("Транскрибация"), "bg_alpha": _BADGE_ALPHA},
    "transcribed": {"color": STATUS_PROCESSING, "text": tr("Текст готов"), "bg_alpha": _BADGE_ALPHA},
    "summarizing": {"color": STATUS_PROCESSING, "text": tr("Саммари"), "bg_alpha": _BADGE_ALPHA},
    "summary_failed": {"color": STATUS_PENDING, "text": tr("Без саммари"), "bg_alpha": _BADGE_ALPHA},
    "completed": {"color": STATUS_SUCCESS, "text": tr("Завершено"), "bg_alpha": _BADGE_ALPHA},
    "error": {"color": STATUS_ERROR, "text": tr("Сбой"), "bg_alpha": _BADGE_ALPHA},
}


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _hex_to_rgba(hex_color: str, alpha: int) -> str:
    """Convert hex color to rgba string for QSS (alpha is 0-255)."""
    r, g, b = _hex_to_rgb(hex_color)
    return f"rgba({r}, {g}, {b}, {alpha})"


def mix(color_a: str, color_b: str, amount: float) -> str:
    """Blend two hex colors; ``amount`` is the share of ``color_b`` (0..1)."""
    a = _hex_to_rgb(color_a)
    b = _hex_to_rgb(color_b)
    t = max(0.0, min(1.0, amount))
    return "#" + "".join(f"{round(x + (y - x) * t):02X}" for x, y in zip(a, b))


def hover_color(color: str) -> str:
    """Hover shade for a filled control of the given color."""
    return mix(color, "#FFFFFF", 0.12) if IS_DARK else mix(color, "#000000", 0.07)


def pressed_color(color: str) -> str:
    """Pressed shade for a filled control of the given color."""
    return mix(color, "#000000", 0.12) if IS_DARK else mix(color, "#000000", 0.15)


def tint(color: str, amount: float = 0.08) -> str:
    """A soft, opaque wash of ``color`` over the card surface."""
    return mix(BG_SURFACE_1, color, amount)


def readable_on_surface(color: str) -> str:
    """Darken bright status colors enough to read as text on light cards."""
    return color if IS_DARK else mix(color, "#000000", 0.18)


# Soft accent used for selection, active tabs and focus rings.
ACCENT_SOFT = _hex_to_rgba(ACCENT_PRIMARY, 46 if IS_DARK else 22)
ACCENT_SOFT_STRONG = _hex_to_rgba(ACCENT_PRIMARY, 70 if IS_DARK else 36)

# Drop shadow for floating windows (r, g, b, a).
SHADOW_RGBA = (0, 0, 0, 150) if IS_DARK else (24, 26, 48, 46)


def badge_style(status: str) -> str:
    """Return QSS for a status badge pill."""
    cfg = STATUS_BADGE.get(status, STATUS_BADGE["pending"])
    bg = _hex_to_rgba(cfg["color"], cfg["bg_alpha"])
    return (
        f"background-color: {bg}; color: {readable_on_surface(cfg['color'])}; "
        f"padding: 2px 8px; border-radius: 9px; "
        f"font-size: 11px; font-weight: 600;"
    )


def primary_button_style(radius: int = RADIUS_MD, padding: str = "8px 18px") -> str:
    """QSS for the main call-to-action button."""
    return f"""
        QPushButton {{
            background-color: {ACCENT_PRIMARY};
            color: {TEXT_ON_ACCENT};
            border: 1px solid {ACCENT_PRIMARY};
            border-radius: {radius}px;
            padding: {padding};
            font-weight: 600;
        }}
        QPushButton:hover {{
            background-color: {ACCENT_PRIMARY_HOVER};
            border-color: {ACCENT_PRIMARY_HOVER};
        }}
        QPushButton:pressed {{
            background-color: {ACCENT_PRIMARY_PRESSED};
            border-color: {ACCENT_PRIMARY_PRESSED};
        }}
        QPushButton:disabled {{
            background-color: {BG_SURFACE_3};
            border-color: {BG_SURFACE_3};
            color: {TEXT_TERTIARY};
        }}
    """


def secondary_button_style(radius: int = RADIUS_MD, padding: str = "8px 16px") -> str:
    """QSS for a quiet outlined button."""
    return f"""
        QPushButton {{
            background-color: {BG_SURFACE_1};
            color: {TEXT_PRIMARY};
            border: 1px solid {BORDER_DEFAULT};
            border-radius: {radius}px;
            padding: {padding};
            font-weight: 500;
        }}
        QPushButton:hover {{
            background-color: {BG_HOVER};
            border-color: {BORDER_STRONG};
        }}
        QPushButton:pressed {{
            background-color: {BG_PRESSED};
        }}
        QPushButton:disabled {{
            background-color: {BG_SURFACE_3};
            border-color: {BORDER_SUBTLE};
            color: {TEXT_TERTIARY};
        }}
    """


def danger_button_style(radius: int = RADIUS_MD, padding: str = "8px 16px") -> str:
    """QSS for a soft destructive button that fills on hover."""
    return f"""
        QPushButton {{
            background-color: {_hex_to_rgba(STATUS_ERROR, 40 if IS_DARK else 22)};
            color: {readable_on_surface(STATUS_ERROR)};
            border: 1px solid transparent;
            border-radius: {radius}px;
            padding: {padding};
            font-weight: 600;
        }}
        QPushButton:hover {{
            background-color: {STATUS_ERROR};
            color: {TEXT_ON_ACCENT};
        }}
        QPushButton:pressed {{
            background-color: {pressed_color(STATUS_ERROR)};
            color: {TEXT_ON_ACCENT};
        }}
        QPushButton:disabled {{
            background-color: {BG_SURFACE_3};
            color: {TEXT_TERTIARY};
        }}
    """


# --- Small vector glyphs for QSS sub-controls (combo arrows, checkmarks) ---

# Glyphs as polylines in their own square box: (box size, stroke width, points).
# Drawn to PNG at runtime because Qt's SVG image plugin is not always present
# (it is missing in the source venv), and a missing plugin hides the arrows.
_ICON_GLYPHS = {
    "chevron-down": (12, 1.6, ((2.5, 4.5), (6.0, 8.0), (9.5, 4.5))),
    "chevron-up": (12, 1.6, ((2.5, 7.5), (6.0, 4.0), (9.5, 7.5))),
    "check": (14, 2.0, ((3.0, 7.2), (5.8, 10.0), (11.0, 4.2))),
}


def _draw_icon(path: Path, name: str, color: str, scale: int) -> None:
    """Render one glyph to a transparent PNG at the given pixel scale."""
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPolygonF

    box, width, points = _ICON_GLYPHS[name]
    image = QImage(box * scale, box * scale, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor(color), width * scale)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.drawPolyline(QPolygonF([QPointF(x * scale, y * scale) for x, y in points]))
    painter.end()
    image.save(str(path), "PNG")


def _icon_url(name: str, color: str) -> str:
    """Write a small PNG glyph once (plus @2x/@3x) and return a QSS ``url()``."""
    folder = Path(tempfile.gettempdir()) / "MeetingNote" / "ui-icons"
    stem = f"{name}-{color.lstrip('#').lower()}"
    path = folder / f"{stem}.png"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        for scale in (1, 2, 3):
            target = path if scale == 1 else folder / f"{stem}@{scale}x.png"
            if not target.exists():
                _draw_icon(target, name, color, scale)
    except OSError:
        return "none"
    return f'url("{path.as_posix()}")'


def build_palette():
    """Qt palette matching the tokens, for parts QSS does not reach."""
    from PySide6.QtGui import QColor, QPalette

    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: BG_BASE,
        QPalette.ColorRole.WindowText: TEXT_PRIMARY,
        QPalette.ColorRole.Base: BG_FIELD,
        QPalette.ColorRole.AlternateBase: BG_SURFACE_3,
        QPalette.ColorRole.Text: TEXT_PRIMARY,
        QPalette.ColorRole.Button: BG_SURFACE_1,
        QPalette.ColorRole.ButtonText: TEXT_PRIMARY,
        QPalette.ColorRole.BrightText: TEXT_ON_ACCENT,
        QPalette.ColorRole.Highlight: ACCENT_PRIMARY,
        QPalette.ColorRole.HighlightedText: TEXT_ON_ACCENT,
        QPalette.ColorRole.ToolTipBase: BG_OVERLAY,
        QPalette.ColorRole.ToolTipText: TEXT_PRIMARY,
        QPalette.ColorRole.PlaceholderText: TEXT_TERTIARY,
        QPalette.ColorRole.Link: ACCENT_PRIMARY,
        QPalette.ColorRole.LinkVisited: ACCENT_PRIMARY_PRESSED,
        QPalette.ColorRole.Light: BG_SURFACE_1,
        QPalette.ColorRole.Midlight: BG_SURFACE_3,
        QPalette.ColorRole.Mid: BORDER_DEFAULT,
        QPalette.ColorRole.Dark: BORDER_STRONG,
        QPalette.ColorRole.Shadow: "#000000",
    }
    for role, color in roles.items():
        palette.setColor(role, QColor(color))
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor(TEXT_TERTIARY))
    return palette


def apply_theme(app) -> None:
    """Apply the palette and global stylesheet to a QApplication."""
    app.setStyle("Fusion")
    app.setPalette(build_palette())
    app.setStyleSheet(get_global_stylesheet())


def get_global_stylesheet() -> str:
    """Return the complete application QSS."""
    chevron_down = _icon_url("chevron-down", TEXT_SECONDARY)
    chevron_up = _icon_url("chevron-up", TEXT_SECONDARY)
    check = _icon_url("check", TEXT_ON_ACCENT)
    return f"""
    /* === Base: text only. Containers paint their own backgrounds. === */
    QWidget {{
        color: {TEXT_PRIMARY};
        font-family: {FONT_FAMILY};
        font-size: 13px;
    }}
    QMainWindow, QDialog {{
        background-color: {BG_BASE};
    }}
    QLabel, QCheckBox, QRadioButton {{
        background: transparent;
    }}
    QScrollArea {{
        background: transparent;
        border: none;
    }}
    QScrollArea > QWidget > QWidget {{
        background: transparent;
    }}

    /* === Menu Bar === */
    QMenuBar {{
        background-color: {BG_BASE};
        border: none;
        padding: 4px 8px 0 8px;
    }}
    QMenuBar::item {{
        background: transparent;
        color: {TEXT_SECONDARY};
        padding: 5px 10px;
        border-radius: {RADIUS_SM}px;
    }}
    QMenuBar::item:selected {{
        background-color: {BG_SURFACE_4 if IS_DARK else BG_PRESSED};
        color: {TEXT_PRIMARY};
    }}

    QMenu {{
        background-color: {BG_OVERLAY};
        border: 1px solid {BORDER_DEFAULT};
        border-radius: {RADIUS_SM}px;
        padding: 5px;
    }}
    QMenu::item {{
        background: transparent;
        color: {TEXT_PRIMARY};
        padding: 7px 28px 7px 12px;
        border-radius: {RADIUS_SM}px;
    }}
    QMenu::item:selected {{
        background-color: {ACCENT_SOFT};
        color: {TEXT_PRIMARY};
    }}
    QMenu::item:disabled {{
        color: {TEXT_TERTIARY};
    }}
    QMenu::separator {{
        height: 1px;
        background-color: {BORDER_SUBTLE};
        margin: 4px 6px;
    }}

    /* === Buttons === */
    QPushButton {{
        background-color: {BG_SURFACE_1};
        color: {TEXT_PRIMARY};
        border: 1px solid {BORDER_DEFAULT};
        border-radius: {RADIUS_MD}px;
        padding: 7px 16px;
        font-weight: 500;
    }}
    QPushButton:hover {{
        background-color: {BG_HOVER};
        border-color: {BORDER_STRONG};
    }}
    QPushButton:pressed {{
        background-color: {BG_PRESSED};
    }}
    QPushButton:disabled {{
        background-color: {BG_SURFACE_3};
        border-color: {BORDER_SUBTLE};
        color: {TEXT_TERTIARY};
    }}
    QPushButton:default {{
        background-color: {ACCENT_PRIMARY};
        border-color: {ACCENT_PRIMARY};
        color: {TEXT_ON_ACCENT};
        font-weight: 600;
    }}
    QPushButton:default:hover {{
        background-color: {ACCENT_PRIMARY_HOVER};
        border-color: {ACCENT_PRIMARY_HOVER};
    }}
    QPushButton:default:pressed {{
        background-color: {ACCENT_PRIMARY_PRESSED};
        border-color: {ACCENT_PRIMARY_PRESSED};
    }}
    /* The weight lives here too, not only under :default: Qt sizes a button
       from its normal-state font, so a bolder :default label gets clipped. */
    QDialogButtonBox QPushButton, QMessageBox QPushButton {{
        min-width: 84px;
        min-height: 20px;
        font-weight: 600;
    }}

    /* === Inputs === */
    QLineEdit, QTextEdit, QPlainTextEdit {{
        background-color: {BG_FIELD};
        border: 1px solid {BORDER_DEFAULT};
        border-radius: {RADIUS_MD}px;
        padding: 7px 12px;
        selection-background-color: {ACCENT_SOFT_STRONG};
        selection-color: {TEXT_PRIMARY};
        color: {TEXT_PRIMARY};
    }}
    QLineEdit:hover, QTextEdit:hover, QPlainTextEdit:hover {{
        border-color: {BORDER_STRONG};
    }}
    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
        border: 1px solid {ACCENT_PRIMARY};
    }}
    QLineEdit:disabled {{
        background-color: {BG_SURFACE_3};
        color: {TEXT_TERTIARY};
    }}

    /* === Combo Box === */
    QComboBox {{
        background-color: {BG_FIELD};
        border: 1px solid {BORDER_DEFAULT};
        border-radius: {RADIUS_MD}px;
        padding: 6px 30px 6px 12px;
        color: {TEXT_PRIMARY};
        min-height: 20px;
    }}
    QComboBox:hover {{
        border-color: {BORDER_STRONG};
    }}
    QComboBox:focus, QComboBox:on {{
        border-color: {ACCENT_PRIMARY};
    }}
    QComboBox::drop-down {{
        subcontrol-origin: padding;
        subcontrol-position: center right;
        width: 26px;
        border: none;
        background: transparent;
    }}
    QComboBox::down-arrow {{
        image: {chevron_down};
        width: 12px;
        height: 12px;
    }}
    QComboBox QAbstractItemView {{
        background-color: {BG_OVERLAY};
        border: 1px solid {BORDER_DEFAULT};
        border-radius: {RADIUS_SM}px;
        padding: 4px;
        outline: none;
        selection-background-color: {ACCENT_SOFT};
        selection-color: {TEXT_PRIMARY};
    }}
    QComboBox QAbstractItemView::item {{
        min-height: 28px;
        padding: 0 8px;
        border-radius: {RADIUS_SM}px;
    }}

    /* === Spin Box === */
    QSpinBox, QDoubleSpinBox {{
        background-color: {BG_FIELD};
        border: 1px solid {BORDER_DEFAULT};
        border-radius: {RADIUS_MD}px;
        padding: 6px 26px 6px 12px;
        color: {TEXT_PRIMARY};
        min-height: 20px;
    }}
    QSpinBox:hover, QDoubleSpinBox:hover {{
        border-color: {BORDER_STRONG};
    }}
    QSpinBox:focus, QDoubleSpinBox:focus {{
        border-color: {ACCENT_PRIMARY};
    }}
    QSpinBox::up-button, QDoubleSpinBox::up-button {{
        subcontrol-origin: border;
        subcontrol-position: top right;
        width: 24px;
        border: none;
        background: transparent;
        margin: 3px 3px 0 0;
    }}
    QSpinBox::down-button, QDoubleSpinBox::down-button {{
        subcontrol-origin: border;
        subcontrol-position: bottom right;
        width: 24px;
        border: none;
        background: transparent;
        margin: 0 3px 3px 0;
    }}
    QSpinBox::up-button:hover, QSpinBox::down-button:hover,
    QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {{
        background-color: {BG_HOVER};
        border-radius: 4px;
    }}
    QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
        image: {chevron_up};
        width: 10px;
        height: 10px;
    }}
    QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
        image: {chevron_down};
        width: 10px;
        height: 10px;
    }}

    /* === Checkbox / Radio === */
    QCheckBox, QRadioButton {{
        spacing: 10px;
        color: {TEXT_PRIMARY};
    }}
    QCheckBox::indicator {{
        width: 18px;
        height: 18px;
        border-radius: 5px;
        border: 1px solid {BORDER_STRONG};
        background-color: {BG_FIELD};
    }}
    QCheckBox::indicator:hover {{
        border-color: {ACCENT_PRIMARY};
    }}
    QCheckBox::indicator:checked {{
        background-color: {ACCENT_PRIMARY};
        border-color: {ACCENT_PRIMARY};
        image: {check};
    }}
    QCheckBox::indicator:checked:hover {{
        background-color: {ACCENT_PRIMARY_HOVER};
        border-color: {ACCENT_PRIMARY_HOVER};
    }}
    QCheckBox::indicator:disabled {{
        background-color: {BG_SURFACE_3};
        border-color: {BORDER_DEFAULT};
    }}
    QCheckBox:disabled, QRadioButton:disabled {{
        color: {TEXT_TERTIARY};
    }}
    QRadioButton::indicator {{
        width: 16px;
        height: 16px;
        border-radius: 9px;
        border: 1px solid {BORDER_STRONG};
        background-color: {BG_FIELD};
    }}
    QRadioButton::indicator:checked {{
        border: 5px solid {ACCENT_PRIMARY};
        background-color: {TEXT_ON_ACCENT};
    }}

    /* === Tab Widget: soft pill tabs === */
    QTabWidget::pane {{
        border: none;
        background: transparent;
        top: 6px;
    }}
    QTabWidget::tab-bar {{
        left: 0px;
    }}
    QTabBar {{
        background: transparent;
    }}
    QTabBar::tab {{
        background: transparent;
        border: none;
        border-radius: {RADIUS_SM + 2}px;
        padding: 7px 14px;
        margin: 0 4px 0 0;
        color: {TEXT_SECONDARY};
        font-size: 13px;
        font-weight: 600;
    }}
    QTabBar::tab:selected {{
        background-color: {ACCENT_SOFT};
        color: {ACCENT_PRIMARY_HOVER if IS_DARK else ACCENT_PRIMARY};
    }}
    QTabBar::tab:hover:!selected {{
        background-color: {BG_SURFACE_4 if IS_DARK else BG_PRESSED};
        color: {TEXT_PRIMARY};
    }}

    /* === Scroll Bars: thin, quiet === */
    QScrollBar:vertical {{
        background: transparent;
        width: 10px;
        margin: 2px 2px 2px 0;
    }}
    QScrollBar::handle:vertical {{
        background-color: {BG_SURFACE_4};
        border-radius: 4px;
        min-height: 32px;
        margin: 0 1px;
    }}
    QScrollBar::handle:vertical:hover {{
        background-color: {BORDER_STRONG};
    }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: none;
    }}
    QScrollBar:horizontal {{
        background: transparent;
        height: 10px;
        margin: 0 2px 2px 2px;
    }}
    QScrollBar::handle:horizontal {{
        background-color: {BG_SURFACE_4};
        border-radius: 4px;
        min-width: 32px;
        margin: 1px 0;
    }}
    QScrollBar::handle:horizontal:hover {{
        background-color: {BORDER_STRONG};
    }}
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0px;
    }}
    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
        background: none;
    }}

    /* === Progress Bar === */
    QProgressBar {{
        background-color: {BG_SURFACE_3};
        border: none;
        border-radius: 3px;
        text-align: center;
        color: {TEXT_SECONDARY};
        font-size: 11px;
    }}
    QProgressBar::chunk {{
        background-color: {ACCENT_PRIMARY};
        border-radius: 3px;
    }}

    /* === Status Bar === */
    QStatusBar {{
        background-color: {BG_BASE};
        border: none;
        color: {TEXT_SECONDARY};
    }}

    /* === Group Box: titled card === */
    QGroupBox {{
        background-color: {BG_SURFACE_2};
        border: 1px solid {BORDER_SUBTLE};
        border-radius: {RADIUS_LG}px;
        margin-top: 26px;
        padding: 14px 16px 16px 16px;
        font-weight: 400;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        subcontrol-position: top left;
        left: 4px;
        top: 0px;
        padding: 0 0 6px 0;
        color: {TEXT_PRIMARY};
        font-size: 13px;
        font-weight: 600;
    }}

    /* === Splitter === */
    QSplitter::handle {{
        background-color: transparent;
    }}
    QSplitter::handle:horizontal {{
        width: 6px;
    }}
    QSplitter::handle:hover {{
        background-color: {ACCENT_SOFT};
    }}

    /* === Tooltips === */
    QToolTip {{
        background-color: {"#2A2D38" if IS_DARK else "#1F2130"};
        color: #F4F5F9;
        border: none;
        border-radius: {RADIUS_SM}px;
        padding: 6px 10px;
        font-size: 12px;
    }}

    /* === Dialogs === */
    QDialogButtonBox {{
        button-layout: 0;
    }}
    QMessageBox {{
        background-color: {BG_SURFACE_1};
    }}
    QMessageBox QLabel {{
        color: {TEXT_PRIMARY};
    }}
    """
