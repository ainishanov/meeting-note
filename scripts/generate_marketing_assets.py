"""Generate deterministic OG and demo assets from the current app artwork."""

from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "site" / "assets"
BUILD = ROOT / "build" / "marketing"

BG = (10, 13, 22)
SURFACE = (24, 29, 43)
WHITE = (248, 249, 252)
MUTED = (180, 188, 205)
PURPLE = (118, 92, 255)
TEAL = (16, 199, 190)
YELLOW = (255, 194, 87)


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "segoeuib.ttf" if bold else "segoeui.ttf"
    path = Path("C:/Windows/Fonts") / name
    return ImageFont.truetype(str(path), size=size)


def gradient_canvas(size: tuple[int, int]) -> Image.Image:
    width, height = size
    canvas = Image.new("RGB", size, BG)
    draw = ImageDraw.Draw(canvas)
    for y in range(height):
        mix = y / max(1, height - 1)
        color = (
            int(BG[0] + 8 * mix),
            int(BG[1] + 10 * mix),
            int(BG[2] + 16 * mix),
        )
        draw.line((0, y, width, y), fill=color)

    glow = Image.new("RGBA", size, (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.ellipse((width - 420, -250, width + 160, 330), fill=(*TEAL, 55))
    glow_draw.ellipse((width - 500, height - 180, width + 140, height + 430), fill=(*PURPLE, 68))
    glow_draw.ellipse((-260, height - 120, 250, height + 360), fill=(*YELLOW, 20))
    glow = glow.filter(ImageFilter.GaussianBlur(45))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), glow)
    return canvas.convert("RGB")


def rounded_image(source: Image.Image, size: tuple[int, int], radius: int) -> Image.Image:
    image = source.copy()
    image.thumbnail(size, Image.Resampling.LANCZOS)
    background = Image.new("RGBA", size, (*SURFACE, 255))
    x = (size[0] - image.width) // 2
    y = (size[1] - image.height) // 2
    background.alpha_composite(image.convert("RGBA"), (x, y))
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0], size[1]), radius, fill=255)
    background.putalpha(mask)
    return background


def paste_with_shadow(
    canvas: Image.Image,
    image: Image.Image,
    position: tuple[int, int],
    radius: int,
) -> None:
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    x, y = position
    shadow_draw.rounded_rectangle(
        (x + 8, y + 16, x + image.width + 8, y + image.height + 16),
        radius,
        fill=(0, 0, 0, 150),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(20))
    canvas.alpha_composite(shadow)
    canvas.alpha_composite(image, position)


def add_brand(
    canvas: Image.Image,
    draw: ImageDraw.ImageDraw,
    icon: Image.Image,
    y: int,
    *,
    x: int = 72,
) -> None:
    icon_size = 46
    draw.rounded_rectangle((x, y, x + icon_size, y + icon_size), 12, fill=(29, 33, 53))
    icon.thumbnail((34, 34), Image.Resampling.LANCZOS)
    canvas.alpha_composite(icon.convert("RGBA"), (x + 6, y + 6))
    draw.text((x + 62, y + 7), "MEETING NOTE", font=font(24, True), fill=WHITE)


def generate_og() -> Path:
    canvas = gradient_canvas((1200, 630)).convert("RGBA")
    draw = ImageDraw.Draw(canvas)
    icon = Image.open(ASSETS / "app-icon-512.png").convert("RGBA")
    hero = Image.open(ASSETS / "hero-app.png").convert("RGBA")

    add_brand(canvas, draw, icon, 55)
    draw.rounded_rectangle((72, 135, 322, 174), 19, fill=(39, 48, 69))
    draw.text((92, 143), "WINDOWS • OPEN SOURCE", font=font(16, True), fill=(210, 218, 234))

    draw.text((72, 202), "TURN EVERY CALL", font=font(54, True), fill=WHITE)
    draw.text((72, 266), "INTO NEXT STEPS", font=font(54, True), fill=YELLOW)
    draw.text(
        (76, 352),
        "Record → transcript → decisions and tasks",
        font=font(24),
        fill=MUTED,
    )
    draw.rounded_rectangle((72, 425, 325, 490), 14, fill=PURPLE)
    draw.text((101, 443), "Download for Windows", font=font(19, True), fill=WHITE)
    draw.text((76, 528), "No meeting bot. Local searchable history.", font=font(17), fill=MUTED)

    app_card = rounded_image(hero, (565, 355), 22)
    paste_with_shadow(canvas, app_card, (600, 150), 22)
    draw.rounded_rectangle((810, 506, 1138, 554), 22, fill=(*TEAL, 245))
    draw.text((836, 518), "DECISIONS • TASKS • NOTES", font=font(15, True), fill=(5, 31, 35))

    output = ASSETS / "og-image.png"
    canvas.convert("RGB").save(output, "PNG", optimize=True)
    return output


def demo_slide(
    headline: str,
    accent_line: str,
    body: str,
    badge: str,
    crop: tuple[int, int, int, int] | None = None,
) -> Image.Image:
    canvas = gradient_canvas((1600, 900)).convert("RGBA")
    draw = ImageDraw.Draw(canvas)
    icon = Image.open(ASSETS / "app-icon-512.png").convert("RGBA")
    hero = Image.open(ASSETS / "hero-app.png").convert("RGBA")
    if crop:
        hero = hero.crop(crop)

    add_brand(canvas, draw, icon, 56, x=72)
    draw.rounded_rectangle((72, 145, 72 + max(250, len(badge) * 15), 190), 22, fill=(39, 48, 69))
    draw.text((94, 156), badge.upper(), font=font(18, True), fill=(208, 217, 235))
    draw.text((72, 235), headline, font=font(58, True), fill=WHITE)
    draw.text((72, 304), accent_line, font=font(58, True), fill=YELLOW)
    draw.multiline_text((76, 405), body, font=font(26), fill=MUTED, spacing=12)

    app_card = rounded_image(hero, (770, 520), 28)
    paste_with_shadow(canvas, app_card, (760, 205), 28)

    draw.rounded_rectangle((72, 720, 520, 790), 16, fill=PURPLE)
    draw.text((111, 740), "Download Meeting Note for Windows", font=font(21, True), fill=WHITE)
    draw.text((74, 830), "ainishanov.github.io/meeting-note", font=font(18), fill=MUTED)
    return canvas.convert("RGB")


def generate_demo_frames() -> list[Path]:
    BUILD.mkdir(parents=True, exist_ok=True)
    slides = [
        demo_slide(
            "START THE CALL.",
            "PRESS RECORD.",
            "Meeting Note captures system audio\nand your microphone on Windows.",
            "01 • Record",
        ),
        demo_slide(
            "STOP SEARCHING",
            "THROUGH RAW AUDIO.",
            "Every call becomes a searchable transcript\ninside your local meeting history.",
            "02 • Transcript",
            crop=(210, 90, 1500, 965),
        ),
        demo_slide(
            "SEE DECISIONS.",
            "LEAVE WITH NEXT STEPS.",
            "The summary puts decisions and action items\nbefore the full transcript.",
            "03 • Outcome",
            crop=(560, 170, 1540, 940),
        ),
        demo_slide(
            "YOUR MEETINGS.",
            "YOUR COMPUTER.",
            "Recordings and meeting history stay local.\nYou choose the AI providers and API keys.",
            "04 • Local first",
        ),
    ]

    paths: list[Path] = []
    for index, slide in enumerate(slides, start=1):
        path = BUILD / f"demo-{index:02d}.png"
        slide.save(path, "PNG", optimize=True)
        paths.append(path)
    slides[0].save(ASSETS / "meeting-note-demo-poster.png", "PNG", optimize=True)
    return paths


def generate_video(frames: list[Path]) -> Path:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        try:
            import imageio_ffmpeg

            ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        except ImportError as error:
            raise RuntimeError("ffmpeg is required to generate the MP4 demo") from error

    output = ASSETS / "meeting-note-demo.mp4"
    command = [ffmpeg, "-y"]
    for frame in frames:
        command.extend(["-loop", "1", "-t", "7.5", "-i", str(frame)])

    filters = []
    labels = []
    for index in range(len(frames)):
        label = f"v{index}"
        filters.append(
            f"[{index}:v]scale=1600:900,setsar=1,fps=30,"
            f"fade=t=in:st=0:d=0.35,fade=t=out:st=7.15:d=0.35[{label}]"
        )
        labels.append(f"[{label}]")
    filters.append(f"{''.join(labels)}concat=n={len(frames)}:v=1:a=0,format=yuv420p[out]")
    command.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[out]",
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "22",
            "-movflags",
            "+faststart",
            str(output),
        ]
    )
    subprocess.run(command, check=True)
    return output


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", action="store_true", help="Also render the 30-second MP4")
    args = parser.parse_args()

    print(generate_og())
    frames = generate_demo_frames()
    if args.video:
        print(generate_video(frames))


if __name__ == "__main__":
    main()
