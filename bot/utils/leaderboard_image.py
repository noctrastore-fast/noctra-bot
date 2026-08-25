"""
NOCTRA leaderboard image generator -- Pillow only, no emoji (they require a
full emoji font that isn't available on Railway).

Fonts are bundled in bot/assets/fonts/ and loaded from a path relative to
this file. Earlier versions pointed at a system font path
(/usr/share/fonts/truetype/dejavu/...) which does not exist on a bare
Railway/Nixpacks container -- Pillow silently fell back to its built-in
bitmap font whenever that happened, which ignores the requested size
entirely. That's why text stayed tiny no matter what size was asked for
while shapes (circles, bars) scaled normally. Bundling the .ttf files with
the project removes that dependency on the host having system fonts
installed at all.

Design notes:
  * No brand logo image -- just the brand name, set large, plus a small
    tracked (letter-spaced) "TOP SPENDERS" label underneath it.
  * Rank, name, order count, and spend are all rendered noticeably larger
    than the original design so they're legible at a glance.
  * The whole canvas is drawn at 2x resolution internally and downsampled
    at the very end (supersampling) for crisp text and edges.
  * The background glow is restrained, and the old duplicate footer
    watermark is gone -- one clean brand header is enough.
"""

from __future__ import annotations

import math
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# -- Palette ------------------------------------------------------------------
BG_TOP       = (9,   6, 20)
BG_BOT       = (19, 12, 40)
CARD_BG      = (25, 16, 50)
CARD_BG_TOP3 = (31, 20, 61)
CARD_BORDER  = (54, 39, 92)
ACCENT       = (140, 112, 255)
GOLD         = (231, 181, 95)
SILVER       = (183, 190, 205)
BRONZE       = (199, 133, 84)
WHITE        = (248, 246, 252)
MUTED        = (146, 136, 180)
BAR_BG       = (42, 29, 74)
MEDAL_CLR    = [GOLD, SILVER, BRONZE]

# -- Layout (final output pixel values, pre-supersampling) --------------------
IMG_W    = 1800
HEADER_H = 172
ROW_H    = 130
ROW_GAP  = 14
PAD      = 56
BOTTOM   = 40
RADIUS   = 18
BAR_H    = 14
BAR_W    = 560
AVATAR_D = 78
BADGE_D  = 60

SS = 2  # supersampling factor -- draw everything at 2x, shrink at the end

# -- Fonts ----------------------------------------------------------------------
# Bundled with the repo, so this works regardless of what fonts (if any)
# the host OS has installed. Falls back to a couple of common system paths
# just in case, and to Pillow's built-in bitmap font only as a last resort
# (which will look wrong -- if you ever see tiny text again, it means even
# the bundled files failed to load, e.g. the assets folder wasn't deployed).
_ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"

_BOLD_CANDIDATES = [
    _ASSETS_DIR / "DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf",
]
_REG_CANDIDATES = [
    _ASSETS_DIR / "DejaVuSans.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/dejavu/DejaVuSans.ttf",
]


def _resolve_font_path(candidates: list) -> str | None:
    for candidate in candidates:
        if Path(candidate).is_file():
            return str(candidate)
    return None


_BOLD = _resolve_font_path(_BOLD_CANDIDATES)
_REG = _resolve_font_path(_REG_CANDIDATES)

_font_cache: dict[tuple[str | None, int], ImageFont.FreeTypeFont] = {}


def _f(path: str | None, size: int) -> ImageFont.FreeTypeFont:
    key = (path, size)
    if key in _font_cache:
        return _font_cache[key]
    font = None
    if path:
        try:
            font = ImageFont.truetype(path, size)
        except Exception:
            font = None
    if font is None:
        # Last-resort fallback -- ignores `size`, so text will look wrong.
        # If this ever triggers in production, the assets/fonts folder
        # didn't get deployed alongside the code.
        font = ImageFont.load_default()
    _font_cache[key] = font
    return font


def _tw(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    return int(draw.textlength(text, font=font))


def _tracked_width(draw, text: str, font, tracking: int) -> int:
    if not text:
        return 0
    return _tw(draw, text, font) + tracking * (len(text) - 1)


def _draw_tracked(draw, xy, text: str, font, fill, tracking: int = 0) -> None:
    """Draw text with manual letter-spacing -- used for small uppercase
    labels, which is what gives an editorial/premium feel instead of
    Pillow's default tight tracking."""
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += _tw(draw, ch, font) + tracking


def _gradient(w: int, h: int) -> Image.Image:
    img = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(img)
    for y in range(h):
        t = y / h
        r = int(BG_TOP[0] * (1 - t) + BG_BOT[0] * t)
        g = int(BG_TOP[1] * (1 - t) + BG_BOT[1] * t)
        b = int(BG_TOP[2] * (1 - t) + BG_BOT[2] * t)
        draw.line([(0, y), (w, y)], fill=(r, g, b))
    return img


def _soft_glow(w: int, h: int) -> Image.Image:
    """A single, very restrained glow in one corner -- enough to avoid a
    flat background without turning the card into a wallpaper."""
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    cx, cy, cr, alpha = int(w * 0.82), int(h * 0.05), int(w * 0.28), 16
    for r in range(cr, 0, -8):
        a = int(alpha * (r / cr) ** 2.4)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(*ACCENT, a))
    return layer


def _draw_medal(draw: ImageDraw.ImageDraw, cx: int, cy: int, rank: int, r: int, font) -> None:
    colour = MEDAL_CLR[rank] if rank < 3 else CARD_BG_TOP3
    border = MEDAL_CLR[rank] if rank < 3 else ACCENT
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=colour, outline=border, width=2)
    txt = str(rank + 1)
    tw = _tw(draw, txt, font)
    # Baseline offset via textbbox so the digit is actually centred instead
    # of guessed from font size (matters a lot for a fallback bitmap font,
    # whose metrics don't match the truetype ones we designed the layout
    # around).
    bbox = draw.textbbox((0, 0), txt, font=font)
    th = bbox[3] - bbox[1]
    text_fill = (24, 14, 46) if rank < 3 else WHITE
    draw.text((cx - tw // 2, cy - th // 2 - bbox[1]), txt, font=font, fill=text_fill)


def _circle_avatar(img: Image.Image, avatar: Image.Image | None, initials: str,
                    x: int, y: int, d: int, ring_colour) -> None:
    draw = ImageDraw.Draw(img)
    if avatar:
        try:
            av = avatar.copy().convert("RGBA").resize((d, d), Image.LANCZOS)
            mask = Image.new("L", (d, d), 0)
            ImageDraw.Draw(mask).ellipse([0, 0, d - 1, d - 1], fill=255)
            buf = Image.new("RGBA", (d, d))
            buf.paste(av, (0, 0))
            img.paste(buf, (x, y), mask)
            draw.ellipse([x - 3, y - 3, x + d + 2, y + d + 2], outline=ring_colour, width=3)
            return
        except Exception:
            pass

    draw.ellipse([x, y, x + d, y + d], fill=(52, 34, 96))
    draw.ellipse([x - 3, y - 3, x + d + 2, y + d + 2], outline=ring_colour, width=3)
    ini = (initials[:2] if len(initials) >= 2 else initials or "?").upper()
    f = _f(_BOLD, int(d * 0.34))
    fw = _tw(draw, ini, f)
    draw.text((x + (d - fw) // 2, y + (d - int(d * 0.4)) // 2), ini, font=f, fill=WHITE)


def _fmt(amount: float, currency: str) -> str:
    c = currency.upper()
    if amount >= 1_000_000:
        s = f"{amount / 1_000_000:.1f}Jt"
    elif amount >= 1_000:
        s = f"{amount / 1_000:.1f}K"
    else:
        s = f"{amount:,.0f}"
    return f"{c} {s}"


def generate_leaderboard_image(
    entries: list[dict],
    *,
    title: str = "NOCTRA STORE",
    subtitle: str = "TOP SPENDERS",
    timestamp: str = "",
) -> BytesIO:
    """`entries` is a list of dicts already sorted best-first, matching what
    bot.utils.leaderboard builds: rank, display_name, total_spent,
    total_orders, currency_label, avatar (PIL Image or None). Cancelled and
    refunded orders are excluded upstream by the database query, so nothing
    here needs to filter them again."""
    n = max(1, len(entries))

    S = SS
    img_w    = IMG_W * S
    header_h = HEADER_H * S
    row_h    = ROW_H * S
    row_gap  = ROW_GAP * S
    pad      = PAD * S
    bottom   = BOTTOM * S
    radius   = RADIUS * S
    bar_h    = BAR_H * S
    bar_w    = BAR_W * S
    avatar_d = AVATAR_D * S
    badge_d  = BADGE_D * S

    h = header_h + n * (row_h + row_gap) - row_gap + bottom
    img = _gradient(img_w, h)
    img = Image.alpha_composite(img.convert("RGBA"), _soft_glow(img_w, h)).convert("RGB")
    draw = ImageDraw.Draw(img)

    # -- Header -------------------------------------------------------------
    f_title = _f(_BOLD, 52 * S)
    f_sub   = _f(_BOLD, 20 * S)
    f_ts    = _f(_REG, 15 * S)

    ty = 30 * S
    tw = _tw(draw, title, f_title)
    tx = (img_w - tw) // 2
    draw.text((tx + 2 * S, ty + 2 * S), title, font=f_title, fill=(16, 9, 36))
    draw.text((tx, ty), title, font=f_title, fill=WHITE)

    sub_tracking = 6 * S
    sy = ty + 66 * S
    sw = _tracked_width(draw, subtitle, f_sub, sub_tracking)
    _draw_tracked(draw, ((img_w - sw) // 2, sy), subtitle, f_sub, ACCENT, sub_tracking)

    if timestamp:
        ts_y = sy + 34 * S
        tsw = _tw(draw, timestamp, f_ts)
        draw.text(((img_w - tsw) // 2, ts_y), timestamp, font=f_ts, fill=MUTED)

    div_y = header_h - 14 * S
    draw.line([(pad, div_y), (img_w - pad, div_y)], fill=CARD_BORDER, width=1 * S)

    # -- Rows -----------------------------------------------------------------
    f_rank    = _f(_BOLD, 24 * S)
    f_name    = _f(_BOLD, 27 * S)
    f_orders  = _f(_REG, 17 * S)
    f_caption = _f(_BOLD, 12 * S)
    f_amount  = _f(_BOLD, 27 * S)

    max_spent = max((e["total_spent"] for e in entries), default=1) or 1
    caption_tracking = 3 * S

    for i, entry in enumerate(entries):
        rank   = entry.get("rank", i)
        name   = entry.get("display_name", "Unknown")[:22]
        spent  = entry.get("total_spent", 0)
        orders = entry.get("total_orders", 0)
        cur    = entry.get("currency_label", "IDR")
        avatar = entry.get("avatar")

        ry0 = header_h + i * (row_h + row_gap)
        ry1 = ry0 + row_h
        rx0 = pad
        rx1 = img_w - pad

        card_fill = CARD_BG_TOP3 if rank < 3 else CARD_BG
        draw.rounded_rectangle([rx0, ry0, rx1, ry1], radius=radius, fill=card_fill,
                                outline=CARD_BORDER, width=1 * S)
        if rank < 3:
            draw.rounded_rectangle([rx0, ry0, rx1, ry0 + 4 * S], radius=2 * S, fill=MEDAL_CLR[rank])

        badge_cx = rx0 + 44 * S
        badge_cy = ry0 + row_h // 2
        _draw_medal(draw, badge_cx, badge_cy, rank, badge_d // 2, f_rank)

        av_x = badge_cx + badge_d // 2 + 22 * S
        av_y = ry0 + (row_h - avatar_d) // 2
        ring_colour = MEDAL_CLR[rank] if rank < 3 else ACCENT
        _circle_avatar(img, avatar, name, av_x, av_y, avatar_d, ring_colour)
        draw = ImageDraw.Draw(img)  # re-acquire after paste ops

        text_x = av_x + avatar_d + 24 * S
        draw.text((text_x, ry0 + 30 * S), name, font=f_name, fill=WHITE)
        ord_txt = f"{orders} order{'s' if orders != 1 else ''}"
        draw.text((text_x, ry0 + 74 * S), ord_txt, font=f_orders, fill=MUTED)

        bar_x1 = rx1 - 38 * S
        bar_x0 = bar_x1 - bar_w
        col = MEDAL_CLR[rank] if rank < 3 else ACCENT

        caption = "TOTAL SPENT"
        cap_w = _tracked_width(draw, caption, f_caption, caption_tracking)
        _draw_tracked(draw, (bar_x0 + (bar_w - cap_w) // 2, ry0 + 26 * S),
                      caption, f_caption, MUTED, caption_tracking)

        spend_s = _fmt(spent, cur)
        sw2 = _tw(draw, spend_s, f_amount)
        draw.text((bar_x0 + (bar_w - sw2) // 2, ry0 + 44 * S), spend_s, font=f_amount, fill=col)

        bar_y = ry0 + 92 * S
        ratio = math.sqrt(spent / max_spent) if max_spent else 0
        fill_w = max(8 * S, int(bar_w * ratio))
        draw.rounded_rectangle([bar_x0, bar_y, bar_x0 + bar_w, bar_y + bar_h],
                               radius=bar_h // 2, fill=BAR_BG)
        bar_col = tuple(int(col[c] * 0.8 + ACCENT[c] * 0.2) for c in range(3))
        draw.rounded_rectangle([bar_x0, bar_y, bar_x0 + fill_w, bar_y + bar_h],
                               radius=bar_h // 2, fill=bar_col)

    final_h = h // S
    img = img.resize((IMG_W, final_h), Image.LANCZOS)

    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf
