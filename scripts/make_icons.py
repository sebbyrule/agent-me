"""Generate the agent-me app icon set.

Draws a simple, distinctive mark — an accent-blue chat bubble with a terminal
prompt (`>` + cursor) on a dark rounded square — at high resolution, then
downscales to the sizes Tauri needs and writes a multi-size Windows .ico.

Run: python scripts/make_icons.py   (outputs to desktop/src-tauri/icons/)
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "desktop", "src-tauri", "icons")

BG = (15, 17, 21, 255)        # near-black app background
PANEL = (30, 34, 43, 255)     # rounded-square panel
ACCENT = (110, 168, 254, 255)  # chat bubble
INK = (11, 18, 32, 255)       # dark glyphs on the bubble


def render(size: int) -> Image.Image:
    # Supersample 4x for clean antialiased edges, then downscale.
    s = size * 4
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    pad = int(s * 0.06)
    d.rounded_rectangle([pad, pad, s - pad, s - pad], radius=int(s * 0.22), fill=PANEL)

    # Chat bubble.
    bx0, by0, bx1, by1 = int(s * 0.20), int(s * 0.24), int(s * 0.80), int(s * 0.66)
    d.rounded_rectangle([bx0, by0, bx1, by1], radius=int(s * 0.10), fill=ACCENT)
    # Bubble tail (bottom-left).
    tail = int(s * 0.10)
    tx = bx0 + int(s * 0.12)
    d.polygon(
        [(tx, by1 - 2), (tx + tail, by1 - 2), (tx, by1 + tail)],
        fill=ACCENT,
    )

    # Prompt chevron ">" inside the bubble.
    lw = max(2, int(s * 0.035))
    cx0 = bx0 + int(s * 0.13)
    cym = (by0 + by1) // 2
    dx, dy = int(s * 0.10), int(s * 0.09)
    d.line([(cx0, cym - dy), (cx0 + dx, cym)], fill=INK, width=lw, joint="curve")
    d.line([(cx0 + dx, cym), (cx0, cym + dy)], fill=INK, width=lw, joint="curve")
    # Cursor bar to the right of the chevron.
    bar_x = cx0 + int(s * 0.18)
    d.rounded_rectangle(
        [bar_x, cym - dy, bar_x + int(s * 0.16), cym - dy + lw],
        radius=lw // 2,
        fill=INK,
    )

    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    os.makedirs(OUT, exist_ok=True)
    master = render(1024)

    pngs = {
        "32x32.png": 32,
        "128x128.png": 128,
        "128x128@2x.png": 256,
        "icon.png": 512,
        "Square150x150Logo.png": 150,
        "StoreLogo.png": 256,
    }
    for name, size in pngs.items():
        master.resize((size, size), Image.LANCZOS).save(os.path.join(OUT, name))

    # Multi-size Windows .ico.
    ico_sizes = [(s, s) for s in (16, 24, 32, 48, 64, 128, 256)]
    master.save(os.path.join(OUT, "icon.ico"), sizes=ico_sizes)

    print("wrote:", ", ".join(sorted(os.listdir(OUT))))


if __name__ == "__main__":
    main()
