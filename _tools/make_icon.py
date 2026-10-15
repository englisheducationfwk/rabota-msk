# -*- coding: utf-8 -*-
"""🎨 Иконка приложения: скруглённый квадрат с градиентом и буквой «Р».

Без эмодзи-метлы: спокойный брендовый знак — градиент (фиолетовый →
бирюзовый) и белая «Р» шрифтом Segoe UI Bold. Результат:
docs/apple-touch-icon.png (180), docs/icon-192.png, docs/icon-512.png.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

GRAD_FROM = (124, 108, 255)   # фиолетовый — как акцент страницы
GRAD_TO = (61, 217, 192)      # бирюзовый
LETTER = "Р"
BOLD_FONTS = [
    r"C:\Windows\Fonts\seguibl.ttf",
    r"C:\Windows\Fonts\segoeuib.ttf",
    r"C:\Windows\Fonts\arialbd.ttf",
]


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


def with_letter(size: int) -> Image.Image:
    """🅿️ Белая «Р» по центру (крупно, с лёгкой тенью для чёткости)."""
    img = rounded_gradient(size)
    font = None
    for path in BOLD_FONTS:
        try:
            font = ImageFont.truetype(path, int(size * 0.60))
            break
        except OSError:
            continue
    if font is None:
        font = ImageFont.load_default()
    draw = ImageDraw.Draw(img)
    box = draw.textbbox((0, 0), LETTER, font=font)
    w, h = box[2] - box[0], box[3] - box[1]
    x = (size - w) / 2 - box[0]
    y = (size - h) / 2 - box[1] - int(size * 0.02)
    # тень
    draw.text((x + max(1, size // 90), y + max(1, size // 90)), LETTER,
              font=font, fill=(20, 20, 45, 90))
    draw.text((x, y), LETTER, font=font, fill=(255, 255, 255, 255))
    return img


def main() -> None:
    DOCS.mkdir(parents=True, exist_ok=True)
    for size, name in ((180, "apple-touch-icon.png"),
                       (192, "icon-192.png"),
                       (512, "icon-512.png")):
        img = with_letter(size).convert("RGB")
        img.save(DOCS / name, "PNG")
        print(f"OK {name} ({size}x{size})")
    # .ico для ярлыка
    icon = with_letter(256)
    icon.save(DOCS / "msk.ico",
              sizes=[(256, 256), (128, 128), (64, 64), (48, 48),
                     (32, 32), (16, 16)])
    print("OK msk.ico")


if __name__ == "__main__":
    main()
