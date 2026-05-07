"""
Generates SquadPay app icon, adaptive icon, splash icon, and favicon.

Brand:
  - Primary gradient: #7C3AED (violet) -> #4F46E5 (indigo)
  - Accent: #22D3EE (cyan)
  - Mark: "SP" monogram (heavy, white, slightly italic feel via subtle shear) +
    a small cyan sparkle in the upper-right of the P.

Outputs (overwrites):
  - frontend/assets/images/icon.png            1024x1024  full bleed (rounded square crop done by OS)
  - frontend/assets/images/adaptive-icon.png   1024x1024  Android adaptive foreground (key art ~62% safe zone)
  - frontend/assets/images/splash-icon.png     1024x1024  white mark on transparent for the splash plugin
  - frontend/assets/images/favicon.png          256x256   smaller icon for web
"""

from __future__ import annotations
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from pathlib import Path
import os
import sys

OUT_DIR = Path("/app/frontend/assets/images")

# Brand colors
VIOLET = (124, 58, 237)        # #7C3AED
INDIGO = (79, 70, 229)         # #4F46E5
CYAN = (34, 211, 238)          # #22D3EE
WHITE = (255, 255, 255)


# ---------- helpers ----------

def vertical_gradient(size: int, top: tuple, bottom: tuple) -> Image.Image:
    """Return an `size x size` RGB image with a smooth diagonal gradient."""
    base = Image.new("RGB", (size, size), top)
    px = base.load()
    for y in range(size):
        for x in range(size):
            # Diagonal blend: 0 at top-left, 1 at bottom-right
            t = (x + y) / (2 * (size - 1))
            r = int(top[0] + (bottom[0] - top[0]) * t)
            g = int(top[1] + (bottom[1] - top[1]) * t)
            b = int(top[2] + (bottom[2] - top[2]) * t)
            px[x, y] = (r, g, b)
    return base


def find_bold_font(size: int) -> ImageFont.FreeTypeFont:
    """Locate a heavy sans-serif font on the system. Falls back to default if missing."""
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ]
    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    print("[icon-gen] WARN: no bold TTF found, using default font", file=sys.stderr)
    return ImageFont.load_default()


def draw_sparkle(img: Image.Image, cx: int, cy: int, size: int, color: tuple) -> None:
    """Draw a 4-pointed sparkle/star centered at (cx, cy)."""
    draw = ImageDraw.Draw(img, "RGBA")
    # Two crossed elongated diamonds
    s = size
    # Vertical diamond
    draw.polygon([(cx, cy - s), (cx + s * 0.3, cy), (cx, cy + s), (cx - s * 0.3, cy)], fill=color)
    # Horizontal diamond
    draw.polygon([(cx - s, cy), (cx, cy - s * 0.3), (cx + s, cy), (cx, cy + s * 0.3)], fill=color)


def draw_sp_monogram(img: Image.Image, cx: int, cy: int, font_size: int, fill=WHITE) -> None:
    """Draw a tight 'SP' monogram centered at (cx, cy)."""
    draw = ImageDraw.Draw(img, "RGBA")
    font = find_bold_font(font_size)
    text = "SP"
    # Pillow's textbbox is anchor-aware; use anchor='mm' for true center alignment.
    try:
        bbox = draw.textbbox((cx, cy), text, font=font, anchor="mm")
        # Offset slightly for visual balance (S sits a hair higher than P)
        draw.text((cx, cy - 4), text, font=font, fill=fill, anchor="mm")
    except TypeError:
        # Older Pillow without anchor support
        w = font.getsize(text)[0] if hasattr(font, "getsize") else font_size * len(text) // 2
        draw.text((cx - w // 2, cy - font_size // 2), text, font=font, fill=fill)


# ---------- builders ----------

def build_app_icon(size: int = 1024) -> Image.Image:
    """The full-bleed iOS / Android app icon with gradient background + SP monogram."""
    img = vertical_gradient(size, VIOLET, INDIGO).convert("RGBA")
    # Subtle radial highlight in upper-left to add depth
    highlight = Image.new("L", (size, size), 0)
    hd = ImageDraw.Draw(highlight)
    hd.ellipse([(-size * 0.2, -size * 0.2), (size * 0.8, size * 0.8)], fill=80)
    highlight = highlight.filter(ImageFilter.GaussianBlur(size * 0.18))
    glow = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    glow.putalpha(highlight)
    img = Image.alpha_composite(img, glow)

    # Big SP monogram, ~58% of canvas height
    draw_sp_monogram(img, cx=size // 2, cy=int(size * 0.5), font_size=int(size * 0.6))

    # Cyan sparkle in the top-right area
    draw_sparkle(img, cx=int(size * 0.78), cy=int(size * 0.22), size=int(size * 0.06), color=CYAN)
    # Smaller white sparkle bottom-left for balance
    draw_sparkle(img, cx=int(size * 0.18), cy=int(size * 0.82), size=int(size * 0.035), color=(255, 255, 255, 220))
    return img


def build_adaptive_icon(size: int = 1024) -> Image.Image:
    """
    Android adaptive foreground. Background is set in app.json (#7C3AED solid),
    so the foreground is just the SP mark + accents on transparent. The key art
    lives inside the central 66% safe zone so the OS mask never crops it.
    """
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))

    # Draw a soft circular gradient "puck" so the mark sits on its own surface
    # even when the OS mask is square. This stays inside the safe zone.
    puck_diameter = int(size * 0.62)
    puck_offset = (size - puck_diameter) // 2
    puck = vertical_gradient(puck_diameter, VIOLET, INDIGO).convert("RGBA")
    puck_mask = Image.new("L", (puck_diameter, puck_diameter), 0)
    ImageDraw.Draw(puck_mask).ellipse([(0, 0), (puck_diameter, puck_diameter)], fill=255)
    img.paste(puck, (puck_offset, puck_offset), puck_mask)

    # SP monogram centered inside the puck
    draw_sp_monogram(img, cx=size // 2, cy=size // 2, font_size=int(puck_diameter * 0.55))

    # Cyan sparkle near upper-right of puck
    draw_sparkle(
        img,
        cx=int(size / 2 + puck_diameter * 0.32),
        cy=int(size / 2 - puck_diameter * 0.32),
        size=int(size * 0.045),
        color=CYAN,
    )
    return img


def build_splash_icon(size: int = 1024) -> Image.Image:
    """
    Splash mark — used by `expo-splash-screen` plugin which composes it over the
    backgroundColor (#7C3AED). So we draw white SP + cyan sparkle on transparent.
    """
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw_sp_monogram(img, cx=size // 2, cy=size // 2, font_size=int(size * 0.62), fill=WHITE)
    draw_sparkle(
        img,
        cx=int(size * 0.74),
        cy=int(size * 0.24),
        size=int(size * 0.06),
        color=CYAN,
    )
    return img


def build_favicon(size: int = 256) -> Image.Image:
    """Smaller version of the app icon for the web favicon."""
    return build_app_icon(size)


# ---------- main ----------

def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    pairs = [
        (OUT_DIR / "icon.png", build_app_icon(1024)),
        (OUT_DIR / "adaptive-icon.png", build_adaptive_icon(1024)),
        (OUT_DIR / "splash-icon.png", build_splash_icon(1024)),
        (OUT_DIR / "favicon.png", build_favicon(256)),
    ]
    for path, img in pairs:
        img.save(path, format="PNG", optimize=True)
        kb = path.stat().st_size / 1024
        print(f"[icon-gen] wrote {path.name:24s}  {img.size[0]}x{img.size[1]:<5}  {kb:6.1f} KB")


if __name__ == "__main__":
    main()
