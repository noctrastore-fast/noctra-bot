"""
NOCTRA leaderboard image generator v2 -- podium + glass-panel list, upgrade
dari versi flat-list sebelumnya biar lebih hidup & gak generic-looking.
Teknik font-bundling, no-emoji-policy, dan supersampling 2x tetep
dipertahanin sama persis kayak versi lama (alasannya sama: Railway/Nixpacks
gak punya font system, emoji butuh font penuh yang gak ke-bundle).

Perubahan desain utama dibanding versi lama:
  * Top 3 dirender sebagai PODIUM -- 3 card kepisah dengan tinggi beda-beda
    (#1 di tengah paling tinggi, #2/#3 di kanan-kiri lebih pendek), bukan
    baris rata kayak rank lainnya. Sekilas pandang langsung kebaca "ini
    leaderboard" tanpa perlu baca angka rank-nya.
  * Semua card (podium maupun list #4+) dirender pake efek glassmorphism
    ringan -- overlay putih transparan tipis + border atas terang / border
    bawah gelap buat simulasi tepi kaca -- BUKAN flat solid fill.
  * Aksen warna KEDUA (crimson/garnet gelap) ditambahin khusus buat #1 --
    glow di belakang podium-nya beda dari ungu brand biasa, plus mahkota
    kecil di atas avatar-nya, biar juara 1 kerasa "spesial", bukan cuma
    beda ukuran doang.
  * Background dikasih tekstur garis diagonal tipis banget (bukan flat
    gradient polos) buat depth/tekstur halus.
"""

from __future__ import annotations

import math
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# -- Palette ------------------------------------------------------------------
BG_TOP       = (7,   5,  16)
BG_BOT       = (17,  10, 36)
ACCENT       = (140, 112, 255)   # ungu brand -- dipake buat rank 2+ dan aksen umum
CRIMSON      = (168, 40,  68)    # aksen kedua, KHUSUS #1 -- dark red sesuai selera Nikss
CRIMSON_SOFT = (214, 92, 118)
GOLD         = (231, 181, 95)
SILVER       = (192, 198, 212)
BRONZE       = (205, 140, 90)
WHITE        = (248, 246, 252)
MUTED        = (150, 140, 182)
GLASS_TOP    = (255, 255, 255, 26)   # highlight tipis di tepi atas card kaca
GLASS_BOTTOM = (0,   0,   0,  46)    # shadow tipis di tepi bawah card kaca
BAR_BG       = (42, 29, 74)
MEDAL_CLR    = [GOLD, SILVER, BRONZE]

# -- Layout (nilai final pre-supersampling) ------------------------------------
IMG_W        = 1800
PAD          = 60
HEADER_H     = 230
PODIUM_GAP   = 28
PODIUM_H1    = 480   # tinggi card #1
PODIUM_H23   = 396   # tinggi card #2 & #3
PODIUM_TO_LIST_GAP = 44
ROW_H        = 118
ROW_GAP      = 14
BOTTOM       = 48
RADIUS       = 26
AVATAR_D_1   = 128
AVATAR_D_23  = 96
AVATAR_D_LIST = 70
BADGE_D      = 54

SS = 2  # supersampling factor

# -- Fonts ----------------------------------------------------------------------
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
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += _tw(draw, ch, font) + tracking


def _draw_centered_tracked(draw, cx: int, y: int, text: str, font, fill, tracking: int = 0) -> None:
    w = _tracked_width(draw, text, font, tracking)
    _draw_tracked(draw, (cx - w // 2, y), text, font, fill, tracking)


def _gradient(w: int, h: int, top, bot) -> Image.Image:
    img = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(img)
    for y in range(h):
        t = y / h
        r = int(top[0] * (1 - t) + bot[0] * t)
        g = int(top[1] * (1 - t) + bot[1] * t)
        b = int(top[2] * (1 - t) + bot[2] * t)
        draw.line([(0, y), (w, y)], fill=(r, g, b))
    return img


def _diagonal_texture(w: int, h: int) -> Image.Image:
    """Garis diagonal SANGAT tipis buat tekstur background -- niatnya
    kerasa doang, bukan keliatan jelas, biar background gak flat polos
    tapi tetep gak ganggu keterbacaan konten di atasnya."""
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    spacing = 46
    for x in range(-h, w, spacing):
        d.line([(x, 0), (x + h, h)], fill=(255, 255, 255, 5), width=1)
    return layer


def _soft_glow(w: int, h: int, cx: int, cy: int, max_r: int, colour, peak_alpha: int) -> Image.Image:
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for r in range(max_r, 0, -10):
        a = int(peak_alpha * (r / max_r) ** 2.6)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(*colour, a))
    return layer


def _glass_panel(img: Image.Image, x0: int, y0: int, x1: int, y1: int, radius: int,
                  accent_top_colour=None, accent_top_h: int = 0) -> None:
    """Card glassmorphism: overlay putih transparan tipis di atas apapun
    yang udah ada di belakangnya (background gradient + glow keliatan
    samar-samar nembus), plus highlight tipis di tepi atas dan shadow tipis
    di tepi bawah biar kerasa punya ketebalan kaca. `accent_top_colour`
    (opsional) nambahin strip warna solid tipis di tepi paling atas --
    dipake buat medali rank di podium."""
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.rounded_rectangle([x0, y0, x1, y1], radius=radius, fill=GLASS_TOP)
    img.alpha_composite(overlay)

    shadow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle([x0, y0 + (y1 - y0) // 2, x1, y1], radius=radius, fill=GLASS_BOTTOM)
    img.alpha_composite(shadow)

    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([x0, y0, x1, y1], radius=radius, outline=(255, 255, 255, 40), width=2)

    if accent_top_colour and accent_top_h:
        draw.rounded_rectangle([x0, y0, x1, y0 + accent_top_h], radius=radius // 2, fill=accent_top_colour)


def _circle_avatar(img: Image.Image, avatar: Image.Image | None, initials: str,
                    cx: int, top_y: int, d: int, ring_colour) -> None:
    x = cx - d // 2
    y = top_y
    draw = ImageDraw.Draw(img)
    if avatar:
        try:
            av = avatar.copy().convert("RGBA").resize((d, d), Image.LANCZOS)
            mask = Image.new("L", (d, d), 0)
            ImageDraw.Draw(mask).ellipse([0, 0, d - 1, d - 1], fill=255)
            buf = Image.new("RGBA", (d, d))
            buf.paste(av, (0, 0))
            img.paste(buf, (x, y), mask)
            draw.ellipse([x - 4, y - 4, x + d + 3, y + d + 3], outline=ring_colour, width=4)
            return
        except Exception:
            pass
    draw.ellipse([x, y, x + d, y + d], fill=(52, 34, 96))
    draw.ellipse([x - 4, y - 4, x + d + 3, y + d + 3], outline=ring_colour, width=4)
    ini = (initials[:2] if len(initials) >= 2 else initials or "?").upper()
    f = _f(_BOLD, int(d * 0.34))
    fw = _tw(draw, ini, f)
    draw.text((x + (d - fw) // 2, y + (d - int(d * 0.4)) // 2), ini, font=f, fill=WHITE)


def _draw_crown(draw: ImageDraw.ImageDraw, cx: int, base_y: int, w: int, h: int, colour) -> None:
    """Mahkota flat sederhana (poligon 3-puncak) -- vector shape doang,
    BUKAN emoji, khusus dipasang di atas avatar #1 biar kerasa "juara"
    tanpa gantungan ke font emoji yang gak ke-bundle di Railway."""
    hw = w // 2
    pts = [
        (cx - hw, base_y),
        (cx - hw, base_y - int(h * 0.45)),
        (cx - hw // 2, base_y - int(h * 0.78)),
        (cx - hw // 4, base_y - int(h * 0.45)),
        (cx, base_y - h),
        (cx + hw // 4, base_y - int(h * 0.45)),
        (cx + hw // 2, base_y - int(h * 0.78)),
        (cx + hw, base_y - int(h * 0.45)),
        (cx + hw, base_y),
    ]
    draw.polygon(pts, fill=colour, outline=WHITE)
    draw.rounded_rectangle([cx - hw, base_y - 6, cx + hw, base_y + 8], radius=4, fill=colour)


def _draw_medal_badge(draw: ImageDraw.ImageDraw, cx: int, cy: int, rank: int, r: int, font) -> None:
    colour = MEDAL_CLR[rank] if rank < 3 else ACCENT
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=colour, outline=WHITE, width=3)
    txt = str(rank + 1)
    tw_ = draw.textlength(txt, font=font)
    bbox = draw.textbbox((0, 0), txt, font=font)
    th = bbox[3] - bbox[1]
    draw.text((cx - tw_ // 2, cy - th // 2 - bbox[1]), txt, font=font, fill=(20, 12, 34))


def _fmt(amount: float, currency: str) -> str:
    c = currency.upper()
    if amount >= 1_000_000:
        s = f"{amount / 1_000_000:.1f}Jt"
    elif amount >= 1_000:
        s = f"{amount / 1_000:.1f}K"
    else:
        s = f"{amount:,.0f}"
    return f"{c} {s}"


def _podium_card(
    img: Image.Image, entry: dict, rank: int, x0: int, x1: int, top_y: int, bottom_y: int,
    avatar_d: int, fonts: dict,
) -> None:
    draw = ImageDraw.Draw(img)
    cx = (x0 + x1) // 2
    accent = CRIMSON if rank == 0 else MEDAL_CLR[rank]

    _glass_panel(img, x0, top_y, x1, bottom_y, RADIUS, accent_top_colour=accent, accent_top_h=8 * SS)
    draw = ImageDraw.Draw(img)

    avatar_top = top_y + 34 * SS
    if rank == 0:
        _draw_crown(draw, cx, avatar_top - 10 * SS, int(avatar_d * 0.9), int(avatar_d * 0.55), GOLD)
    ring_colour = CRIMSON_SOFT if rank == 0 else MEDAL_CLR[rank]
    _circle_avatar(img, entry.get("avatar"), entry.get("display_name", "?"), cx, avatar_top, avatar_d, ring_colour)

    badge_cy = avatar_top + avatar_d
    _draw_medal_badge(ImageDraw.Draw(img), cx, badge_cy, rank, BADGE_D // 2, fonts["badge"])

    draw = ImageDraw.Draw(img)
    name = entry.get("display_name", "Unknown")[:18]
    name_y = badge_cy + BADGE_D // 2 + 18 * SS
    nw = _tw(draw, name, fonts["name"])
    draw.text((cx - nw // 2, name_y), name, font=fonts["name"], fill=WHITE)

    spend_s = _fmt(entry.get("total_spent", 0), entry.get("currency_label", "IDR"))
    spend_y = name_y + fonts["name_h"] + 12 * SS
    sw = _tw(draw, spend_s, fonts["amount"])
    draw.text((cx - sw // 2, spend_y), spend_s, font=fonts["amount"], fill=accent if rank == 0 else WHITE)

    orders = entry.get("total_orders", 0)
    ord_txt = f"{orders} order{'s' if orders != 1 else ''}"
    ord_y = spend_y + fonts["amount_h"] + 10 * SS
    ow = _tw(draw, ord_txt, fonts["orders"])
    draw.text((cx - ow // 2, ord_y), ord_txt, font=fonts["orders"], fill=MUTED)


def generate_leaderboard_image(
    entries: list[dict],
    *,
    title: str = "NOCTRA STORE",
    subtitle: str = "TOP SPENDERS",
    timestamp: str = "",
) -> BytesIO:
    """`entries` sorted best-first: rank, display_name, total_spent,
    total_orders, currency_label, avatar (PIL Image atau None). Sama
    kontrak-nya kayak versi lama -- cancelled/refunded udah difilter
    upstream, gak perlu difilter lagi di sini."""
    S = SS
    img_w = IMG_W * S
    pad = PAD * S
    header_h = HEADER_H * S
    podium_gap = PODIUM_GAP * S
    podium_h1 = PODIUM_H1 * S
    podium_h23 = PODIUM_H23 * S
    podium_to_list_gap = PODIUM_TO_LIST_GAP * S
    row_h = ROW_H * S
    row_gap = ROW_GAP * S
    bottom = BOTTOM * S
    radius = RADIUS * S
    avatar_d1 = AVATAR_D_1 * S
    avatar_d23 = AVATAR_D_23 * S
    avatar_d_list = AVATAR_D_LIST * S
    badge_d = BADGE_D * S

    top3 = entries[:3]
    rest = entries[3:]
    has_podium = len(top3) > 0

    podium_section_h = (podium_h1 + 40 * S) if has_podium else 0
    list_n = max(0, len(rest))
    list_section_h = list_n * (row_h + row_gap) - (row_gap if list_n else 0)

    h = header_h + podium_section_h + (podium_to_list_gap if (has_podium and list_n) else 0) + list_section_h + bottom
    h = max(h, header_h + bottom + 200 * S)

    img = _gradient(img_w, h, BG_TOP, BG_BOT)
    img = img.convert("RGBA")
    img.alpha_composite(_diagonal_texture(img_w, h))
    if has_podium:
        podium_cy = header_h + podium_section_h // 2
        img.alpha_composite(_soft_glow(img_w, h, img_w // 2, podium_cy, int(img_w * 0.42), CRIMSON, 20))
        img.alpha_composite(_soft_glow(img_w, h, int(img_w * 0.15), int(h * 0.1), int(img_w * 0.22), ACCENT, 14))
    draw = ImageDraw.Draw(img)

    # -- Header ---------------------------------------------------------------
    f_title = _f(_BOLD, 56 * S)
    f_sub = _f(_BOLD, 21 * S)
    f_ts = _f(_REG, 15 * S)

    ty = 32 * S
    tw = _tw(draw, title, f_title)
    tx = (img_w - tw) // 2
    draw.text((tx + 2 * S, ty + 2 * S), title, font=f_title, fill=(0, 0, 0, 90))
    draw.text((tx, ty), title, font=f_title, fill=WHITE)

    sub_tracking = 7 * S
    sy = ty + 72 * S
    _draw_centered_tracked(draw, img_w // 2, sy, subtitle, f_sub, CRIMSON_SOFT, sub_tracking)

    # Divider kecil di bawah subtitle -- bukan garis panjang full-width
    # kayak sebelumnya, biar keliatan lebih editorial/gak generic.
    div_w = 90 * S
    div_y = sy + 40 * S
    draw.line([(img_w // 2 - div_w // 2, div_y), (img_w // 2 + div_w // 2, div_y)], fill=CRIMSON, width=3 * S)

    if timestamp:
        ts_y = div_y + 16 * S
        tsw = _tw(draw, timestamp, f_ts)
        draw.text(((img_w - tsw) // 2, ts_y), timestamp, font=f_ts, fill=MUTED)

    # -- Podium (top 3) ---------------------------------------------------------
    fonts = {
        "badge": _f(_BOLD, 24 * S),
        "name": _f(_BOLD, 30 * S),
        "amount": _f(_BOLD, 30 * S),
        "orders": _f(_REG, 18 * S),
    }
    bbox = draw.textbbox((0, 0), "Ag", font=fonts["name"])
    fonts["name_h"] = bbox[3] - bbox[1]
    bbox = draw.textbbox((0, 0), "Ag", font=fonts["amount"])
    fonts["amount_h"] = bbox[3] - bbox[1]

    if has_podium:
        col_gap = 26 * S
        col_w = (img_w - 2 * pad - 2 * col_gap) // 3
        podium_bottom = header_h + podium_section_h - 20 * S

        order_slots = [1, 0, 2]  # #2 kiri, #1 tengah, #3 kanan
        for slot_idx, entry_idx in enumerate(order_slots):
            if entry_idx >= len(top3):
                continue
            entry = top3[entry_idx]
            x0 = pad + slot_idx * (col_w + col_gap)
            x1 = x0 + col_w
            card_h = podium_h1 if entry_idx == 0 else podium_h23
            top_y = podium_bottom - card_h
            avatar_d = avatar_d1 if entry_idx == 0 else avatar_d23
            _podium_card(img, entry, entry_idx, x0, x1, top_y, podium_bottom, avatar_d, fonts)

    # -- List (rank 4+) ---------------------------------------------------------
    if rest:
        f_rank_list = _f(_BOLD, 22 * S)
        f_name_list = _f(_BOLD, 25 * S)
        f_orders_list = _f(_REG, 16 * S)
        f_amount_list = _f(_BOLD, 25 * S)

        list_top = header_h + podium_section_h + (podium_to_list_gap if has_podium else 0)
        rx0 = pad
        rx1 = img_w - pad

        for i, entry in enumerate(rest):
            rank = i + 3
            ry0 = list_top + i * (row_h + row_gap)
            ry1 = ry0 + row_h

            _glass_panel(img, rx0, ry0, rx1, ry1, radius)
            draw = ImageDraw.Draw(img)

            badge_cx = rx0 + 50 * S
            badge_cy = ry0 + row_h // 2
            _draw_medal_badge(draw, badge_cx, badge_cy, rank, badge_d // 2, f_rank_list)

            av_x = badge_cx + badge_d // 2 + 24 * S
            av_y = ry0 + (row_h - avatar_d_list) // 2
            _circle_avatar(img, entry.get("avatar"), entry.get("display_name", "?"), av_x + avatar_d_list // 2, av_y, avatar_d_list, ACCENT)
            draw = ImageDraw.Draw(img)

            text_x = av_x + avatar_d_list + 26 * S
            name = entry.get("display_name", "Unknown")[:22]
            draw.text((text_x, ry0 + 24 * S), name, font=f_name_list, fill=WHITE)
            orders = entry.get("total_orders", 0)
            ord_txt = f"{orders} order{'s' if orders != 1 else ''}"
            draw.text((text_x, ry0 + 66 * S), ord_txt, font=f_orders_list, fill=MUTED)

            spend_s = _fmt(entry.get("total_spent", 0), entry.get("currency_label", "IDR"))
            sw2 = _tw(draw, spend_s, f_amount_list)
            draw.text((rx1 - 40 * S - sw2, ry0 + row_h // 2 - fonts["amount_h"] // 2), spend_s, font=f_amount_list, fill=ACCENT)

    final_h = h // S
    img = img.convert("RGB").resize((IMG_W, final_h), Image.LANCZOS)

    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf
