"""Shorts sablonu: beyaz kenarliklar, ust baslik, alt via yazisi."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

try:
    from moviepy import CompositeVideoClip, ImageClip, VideoFileClip
except ImportError:
    from moviepy.editor import CompositeVideoClip, ImageClip, VideoFileClip


CANVAS_WIDTH = 1080
CANVAS_HEIGHT = 1920
BORDER = 48
HEADER_HEIGHT = 130
FOOTER_HEIGHT = 80

FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
]


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    words = text.split()
    if not words:
        return [""]

    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        trial = f"{current} {word}"
        bbox = font.getbbox(trial)
        if bbox[2] - bbox[0] <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines[:2]


def _render_text_band(
    text: str,
    width: int,
    height: int,
    *,
    font_size: int = 42,
    text_color: tuple[int, int, int] = (20, 20, 20),
    bg_color: tuple[int, int, int] = (255, 255, 255),
    max_lines: int = 2,
) -> np.ndarray:
    img = Image.new("RGB", (width, height), bg_color)
    draw = ImageDraw.Draw(img)
    font = _load_font(font_size)

    lines = _wrap_text(text, font, width - 40)[:max_lines]
    line_height = font_size + 10
    total_height = len(lines) * line_height
    y = max(10, (height - total_height) // 2)

    for line in lines:
        bbox = font.getbbox(line)
        text_width = bbox[2] - bbox[0]
        x = (width - text_width) // 2
        draw.text((x, y), line, fill=text_color, font=font)
        y += line_height

    return np.array(img)


def apply_shorts_template(
    input_path: Path,
    output_path: Path,
    *,
    title: str,
    via_credit: str,
) -> None:
    """Videoyu beyaz cerceveli Shorts sablonuna yerlestirir."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    inner_width = CANVAS_WIDTH - (BORDER * 2)
    inner_height = CANVAS_HEIGHT - HEADER_HEIGHT - FOOTER_HEIGHT

    with VideoFileClip(str(input_path)) as source:
        source_w, source_h = source.size
        scale = min(inner_width / source_w, inner_height / source_h)
        new_w = int(source_w * scale)
        new_h = int(source_h * scale)

        if hasattr(source, "resized"):
            fitted = source.resized(new_size=(new_w, new_h))
        else:
            fitted = source.resize(newsize=(new_w, new_h))

        duration = source.duration
        fps = source.fps or 30

        bg_array = np.full((CANVAS_HEIGHT, CANVAS_WIDTH, 3), 255, dtype=np.uint8)
        bg_clip = ImageClip(bg_array).with_duration(duration)

        title_array = _render_text_band(title, CANVAS_WIDTH, HEADER_HEIGHT, font_size=40)
        title_clip = ImageClip(title_array).with_duration(duration).with_position((0, 0))

        via_text = via_credit if via_credit.lower().startswith("via") else f"via {via_credit}"
        footer_array = _render_text_band(
            via_text,
            CANVAS_WIDTH,
            FOOTER_HEIGHT,
            font_size=28,
            text_color=(80, 80, 80),
        )
        footer_clip = ImageClip(footer_array).with_duration(duration).with_position(
            (0, CANVAS_HEIGHT - FOOTER_HEIGHT)
        )

        video_x = (CANVAS_WIDTH - new_w) // 2
        video_y = HEADER_HEIGHT + (inner_height - new_h) // 2
        positioned = fitted.with_position((video_x, video_y))

        final = CompositeVideoClip(
            [bg_clip, positioned, title_clip, footer_clip],
            size=(CANVAS_WIDTH, CANVAS_HEIGHT),
        ).with_duration(duration)

        try:
            final.write_videofile(
                str(output_path),
                codec="libx264",
                audio_codec="aac",
                fps=fps,
                preset="medium",
                logger=None,
            )
        finally:
            final.close()
            fitted.close()
