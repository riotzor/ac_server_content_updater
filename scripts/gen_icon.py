"""One-off script to generate the app icon (assets/icon.ico + assets/icon.png).

Not part of the runtime dependency set — requires Pillow, which is only needed
here at icon-authoring time. Re-run this after editing the design below to
regenerate the committed binary assets.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

_BG = (26, 26, 30, 255)  # near-black, matches the app's dark Text/log panels
_ACCENT = (39, 174, 96, 255)  # _GREEN from app.py
_ACCENT_DIM = (39, 174, 96, 120)

_OUT_DIR = Path(__file__).resolve().parent.parent / "src" / "ac_updater" / "gui" / "assets"


def _draw_glyph(size: int) -> Image.Image:
    """Rounded-square dark tile with a circular sync/update arrow in accent green."""
    scale = 4  # supersample for smooth edges, then downscale
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Rounded-square background
    radius = int(s * 0.22)
    draw.rounded_rectangle([0, 0, s - 1, s - 1], radius=radius, fill=_BG)

    # Sync arrow: two arcs forming a broken ring, each ending in an arrowhead
    cx, cy = s / 2, s / 2
    r = s * 0.28
    width = max(2, int(s * 0.065))

    bbox = [cx - r, cy - r, cx + r, cy + r]
    draw.arc(bbox, start=-160, end=110, fill=_ACCENT, width=width)
    draw.arc(bbox, start=20, end=290, fill=_ACCENT, width=width)

    def arrowhead(angle_deg: float, tip_r: float, size_: float) -> None:
        angle = math.radians(angle_deg)
        tip = (cx + tip_r * math.cos(angle), cy + tip_r * math.sin(angle))
        perp = angle + math.pi / 2
        base_a = (tip[0] - size_ * math.cos(angle) + size_ * 0.5 * math.cos(perp),
                   tip[1] - size_ * math.sin(angle) + size_ * 0.5 * math.sin(perp))
        base_b = (tip[0] - size_ * math.cos(angle) - size_ * 0.5 * math.cos(perp),
                   tip[1] - size_ * math.sin(angle) - size_ * 0.5 * math.sin(perp))
        draw.polygon([tip, base_a, base_b], fill=_ACCENT)

    arrowhead(110, r, s * 0.11)
    arrowhead(-70, r, s * 0.11)

    # Subtle center dot for polish
    dot_r = s * 0.035
    draw.ellipse([cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r], fill=_ACCENT_DIM)

    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    _OUT_DIR.mkdir(parents=True, exist_ok=True)

    sizes = [16, 24, 32, 48, 64, 128, 256]
    images = [_draw_glyph(sz) for sz in sizes]

    ico_path = _OUT_DIR / "icon.ico"
    images[0].save(
        ico_path,
        format="ICO",
        sizes=[(sz, sz) for sz in sizes],
        append_images=images[1:],
    )

    png_path = _OUT_DIR / "icon.png"
    images[-1].save(png_path, format="PNG")

    print(f"Wrote {ico_path} and {png_path}")


if __name__ == "__main__":
    main()
