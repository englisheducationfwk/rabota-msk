# -*- coding: utf-8 -*-
"""🎨 Иконка страницы: генерим PNG-ки без интернета (PIL есть на ПК).

Рисуем скруглённый квадрат с градиентом и метёлкой 🧹 (шрифт эмодзи
Windows — seguiemj.ttf). Результат: docs/apple-touch-icon.png (180),
docs/icon-192.png, docs/icon-512.png.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

GRAD_FROM = (124, 108, 255)   # фиолетовый — как акцент страницы
GRAD_TO = (61, 217, 192)      # бирюзовый
EMOJI_FONT = r"C:\Windows\Fonts\seguiemj.ttf"


def rounded_gradient(size: int) -> Image.Image:
    """🟪 Скруглённый квадрат с диагональным градиентом."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    grad = Image.new("RGB", (size, size))
    px = grad.load()
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * size - 2)
            px[x, y] = (
                int(GRAD_FROM[0] + (GRAD_TO[0] - GRAD_FROM[0]) * t),
                int(GRAD_FROM[1] + (GRAD_TO[1] - GRAD_FROM[1]) * t),
                int(GRAD_FROM[2] + (GRAD_TO[2] - GRAD_FROM[2]) * t),
            )
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    radius = int(size * 0.22)
    draw.rounded_rectangle((0, 0, size - 1, size - 1), radius=radius,
                           fill=255)
    img.paste(grad, (0, 0), mask)
    return img


def with_emoji(size: int) -> Image.Image:
    """🧹 Иконка с метёлкой по центру (или чистый градиент без шрифта)."""
    img = rounded_gradient(size)
    try:
        font = ImageFont.truetype(EMOJI_FONT, int(size * 0.62))
        draw = ImageDraw.Draw(img)
        text = "🧹"
        box = draw.textbbox((0, 0), text, font=font, embedded_color=True)
        w = box[2] - box[0]
        h = box[3] - box[1]
        draw.text(((size - w) / 2 - box[0], (size - h) / 2 - box[1]), text,
                  font=font, embedded_color=True)
    except Exception:
        pass
    return img


def main() -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    for size, name in ((180, "apple-touch-icon.png"),
                       (192, "icon-192.png"),
                       (512, "icon-512.png")):
        img = with_emoji(size).convert("RGB")
        img.save(DOCS / name, "PNG")
        print(f"✅ {name} ({size}x{size})")


if __name__ == "__main__":
    main()
