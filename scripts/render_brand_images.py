#!/usr/bin/env python
"""Render the Home Assistant brand images from FIMER's logo SVG.

Reads ``docs/brand/fimer_logo.svg`` (the "RGB blue positive" wordmark from
https://www.fimer.com/themes/custom/fimer_corporate/logo.svg: a white
wordmark on a #250e62 box) and writes to ``custom_components/fimer/brand/``:

- ``icon.png`` (256) and ``icon@2x.png`` (512): the blue box with the wordmark
- ``logo.png`` (128 high) and ``logo@2x.png`` (256 high): the blue wordmark
- ``dark_logo.png`` and ``dark_logo@2x.png``: the white wordmark for dark themes

Needs cairosvg (libcairo) and Pillow::

    python scripts/render_brand_images.py
"""

from __future__ import annotations

import io
from pathlib import Path
import re

import cairosvg
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "docs" / "brand" / "fimer_logo.svg"
OUTPUT = ROOT / "custom_components" / "fimer" / "brand"

BRAND_BLUE = "#250e62"
WHITE = "#ffffff"
ICON_WORDMARK_WIDTH = 0.78
"""Share of the icon's width the wordmark spans."""


def wordmark(color: str, width: int = 3000) -> Image.Image:
    """Render the wordmark path alone, in ``color``, cropped to its bounds."""
    svg = SOURCE.read_text(encoding="utf-8")
    match = re.search(r'<path class="cls-1" d="([^"]+)" transform="([^"]+)"', svg)
    if match is None:
        raise SystemExit(f"no wordmark path found in {SOURCE}")
    variant = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 600">'
        f'<path fill="{color}" d="{match.group(1)}" transform="{match.group(2)}"/></svg>'
    )
    png = cairosvg.svg2png(bytestring=variant.encode(), output_width=width)
    image = Image.open(io.BytesIO(png)).convert("RGBA")
    return image.crop(image.getbbox())


def logo(mark: Image.Image, height: int) -> Image.Image:
    """Scale the wordmark to ``height`` pixels, keeping its proportions."""
    return mark.resize((round(mark.width * height / mark.height), height), Image.LANCZOS)


def icon(mark: Image.Image, size: int) -> Image.Image:
    """Centre the white wordmark on a brand-blue square."""
    canvas = Image.new("RGBA", (size, size), BRAND_BLUE)
    width = round(size * ICON_WORDMARK_WIDTH)
    scaled = mark.resize((width, round(mark.height * width / mark.width)), Image.LANCZOS)
    canvas.alpha_composite(scaled, ((size - scaled.width) // 2, (size - scaled.height) // 2))
    return canvas


def main() -> None:
    blue = wordmark(BRAND_BLUE)
    white = wordmark(WHITE)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    logo(blue, 128).save(OUTPUT / "logo.png")
    logo(blue, 256).save(OUTPUT / "logo@2x.png")
    logo(white, 128).save(OUTPUT / "dark_logo.png")
    logo(white, 256).save(OUTPUT / "dark_logo@2x.png")
    icon(white, 256).save(OUTPUT / "icon.png")
    icon(white, 512).save(OUTPUT / "icon@2x.png")
    for path in sorted(OUTPUT.glob("*.png")):
        with Image.open(path) as image:
            print(f"{path.name}: {image.size[0]}x{image.size[1]}")  # noqa: T201


if __name__ == "__main__":
    main()
