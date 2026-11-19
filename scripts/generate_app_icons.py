"""Render the Meeting Note app icon from its SVG sources.

The icon has three hand-tuned SVG sources so it stays sharp at every size:

    assets/app_icon_small.svg   16-24 px   three bold, pixel-snapped bars
    assets/app_icon_medium.svg  30-48 px   five thicker bars (taskbar sizes)
    assets/app_icon.svg         64 px +    detailed master artwork

Outputs:

    assets/app_icon.ico         Windows exe, installer, window and tray icon
    site/assets/app-icon.svg    copy of the master artwork
    site/assets/app-icon-512.png
    site/favicon.ico

Usage: python scripts/generate_app_icons.py
"""

from __future__ import annotations

import os
import shutil
import struct
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QImage, QPainter  # noqa: E402
from PySide6.QtSvg import QSvgRenderer  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
SITE_ASSETS = ROOT / "site" / "assets"

SOURCES = {
    "small": ASSETS / "app_icon_small.svg",
    "medium": ASSETS / "app_icon_medium.svg",
    "large": ASSETS / "app_icon.svg",
}
# 30/36 px are the Windows 11 taskbar sizes at 125%/150% scaling.
APP_ICO_SIZES = [16, 20, 24, 30, 32, 36, 40, 48, 64, 96, 128, 256]
FAVICON_SIZES = [16, 32, 48]


def source_for(size: int) -> Path:
    if size <= 24:
        return SOURCES["small"]
    if size <= 48:
        return SOURCES["medium"]
    return SOURCES["large"]


def render(size: int) -> QImage:
    renderer = QSvgRenderer(str(source_for(size)))
    if not renderer.isValid():
        raise RuntimeError(f"Cannot parse {source_for(size)}")
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, size, size))
    painter.end()
    return image.convertToFormat(QImage.Format.Format_ARGB32)


def png_bytes(image: QImage) -> bytes:
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    buffer.close()
    return bytes(data)


def bmp_icon_bytes(image: QImage) -> bytes:
    """32-bit DIB icon entry: BGRA rows bottom-up plus a 1-bit AND mask."""
    size = image.width()
    stride = size * 4
    pixels = bytes(image.constBits())[: stride * size]  # ARGB32 = BGRA in memory
    rows = [pixels[y * stride : (y + 1) * stride] for y in range(size)]
    xor = b"".join(reversed(rows))

    mask_stride = ((size + 31) // 32) * 4
    mask_rows = []
    for row in reversed(rows):
        bits = bytearray(mask_stride)
        for x in range(size):
            if row[x * 4 + 3] == 0:
                bits[x // 8] |= 0x80 >> (x % 8)
        mask_rows.append(bytes(bits))
    and_mask = b"".join(mask_rows)

    header = struct.pack(
        "<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, len(xor) + len(and_mask), 0, 0, 0, 0
    )
    return header + xor + and_mask


def write_ico(path: Path, sizes: list[int]) -> None:
    """Write a multi-size ICO: BMP entries below 256 px, PNG for 256 px."""
    entries = []
    for size in sizes:
        image = render(size)
        entries.append((size, png_bytes(image) if size >= 256 else bmp_icon_bytes(image)))

    offset = 6 + 16 * len(entries)
    directory = struct.pack("<HHH", 0, 1, len(entries))
    payload = b""
    for size, data in entries:
        dim = 0 if size >= 256 else size
        directory += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset)
        offset += len(data)
        payload += data
    path.write_bytes(directory + payload)
    print(f"{path.relative_to(ROOT)}: {', '.join(map(str, sizes))} px")


def main() -> int:
    app = QGuiApplication(sys.argv)  # noqa: F841 - QtSvg needs a GUI application

    write_ico(ASSETS / "app_icon.ico", APP_ICO_SIZES)
    write_ico(ROOT / "site" / "favicon.ico", FAVICON_SIZES)

    shutil.copyfile(SOURCES["large"], SITE_ASSETS / "app-icon.svg")
    print("site/assets/app-icon.svg: copied")

    large = QSvgRenderer(str(SOURCES["large"]))
    image = QImage(512, 512, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    large.render(painter, QRectF(0, 0, 512, 512))
    painter.end()
    image.save(str(SITE_ASSETS / "app-icon-512.png"), "PNG")
    print("site/assets/app-icon-512.png: 512 px")
    return 0


if __name__ == "__main__":
    sys.exit(main())
