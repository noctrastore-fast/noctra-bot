"""
NOCTRA digital card image generator -- Pillow only, no emoji (sama alasan
kayak bot.utils.leaderboard_image: font emoji penuh gak available di
Railway). Font dibundle dari bot/assets/fonts/, teknik supersampling 2x
sama persis kayak leaderboard_image.py biar konsisten kualitasnya.

PENTING: background/chip/pola titik di sini di-generate PENUH lewat kode
(bukan nempel di atas asset gambar siap pake) -- staff belum punya asset
background sendiri pas fitur ini dibikin, jadi hasilnya usaha terbaik niru
referensi visual yang dikasih, BUKAN replika piksel-sempurna. Kalau nanti
staff desain background sendiri, generator ini gampang diganti jadi
"tempel teks+avatar di atas template" -- tinggal skip semua fungsi gradient
di bawah dan load Image.open() buat backgroundnya.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# -- Palette (senada sama bot.core.theme.COLOR_PRIMARY/COLOR_ACCENT, --------
# dikonversi ke tuple RGB soalnya Pillow gak nerima int hex kayak Discord)
BG_TOP     = (8, 5, 18)
BG_BOT     = (20, 11, 42)
GLOW       = (124, 92, 255)   # COLOR_ACCENT
PRIMARY    = (75, 31, 168)    # COLOR_PRIMARY
WHITE      = (245, 243, 250)
MUTED      = (176, 166, 210)
CHIP_LIGHT = (196, 172, 255)
CHIP_DARK  = (108, 78, 200)

IMG_W  = 1600
IMG_H  = 1000
RADIUS = 48
PAD    = 72

SS = 2  # supersampling factor, sama kayak leaderboard_image.py

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


def _bg_gradient(w: int, h: int) -> Image.Image:
    img = Image.new("RGB", (w, h))
    draw = ImageDraw.Draw(img)
    for y in range(h):
        t = y / h
        r = int(BG_TOP[0] * (1 - t) + BG_BOT[0] * t)
        g = int(BG_TOP[1] * (1 - t) + BG_BOT[1] * t)
        b = int(BG_TOP[2] * (1 - t) + BG_BOT[2] * t)
        draw.line([(0, y), (w, y)], fill=(r, g, b))
    return img


def _swoosh_glow(w: int, h: int) -> Image.Image:
    """Lengkung cahaya ungu lembut di sisi kanan -- niru aksen di
    referensi, restrained kayak _soft_glow di leaderboard_image.py biar
    background tetep gelap/premium, gak jadi wallpaper."""
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    cx, cy = int(w * 0.8), int(h * 0.55)
    for r, alpha in ((int(w * 0.62), 8), (int(w * 0.48), 12), (int(w * 0.34), 16)):
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(*GLOW, alpha))
    return layer


def _gradient_text(base: Image.Image, xy: tuple[int, int], text: str, font,
                    top_colour, bottom_colour) -> None:
    """Render teks gradient vertikal (buat wordmark "Noctra") lewat
    text-as-mask -- Pillow gak punya gradient fill teks bawaan."""
    bbox = font.getbbox(text)
    tw_, th_ = bbox[2] - bbox[0], bbox[3] - bbox[1]
    mask = Image.new("L", (tw_ + 4, th_ + 4), 0)
    ImageDraw.Draw(mask).text((-bbox[0] + 2, -bbox[1] + 2), text, font=font, fill=255)

    grad = Image.new("RGB", mask.size)
    gdraw = ImageDraw.Draw(grad)
    for y in range(mask.size[1]):
        t = y / max(1, mask.size[1])
        r = int(top_colour[0] * (1 - t) + bottom_colour[0] * t)
        g = int(top_colour[1] * (1 - t) + bottom_colour[1] * t)
        b = int(top_colour[2] * (1 - t) + bottom_colour[2] * t)
        gdraw.line([(0, y), (mask.size[0], y)], fill=(r, g, b))

    base.paste(grad, (xy[0] - 2, xy[1] - 2), mask)


def _circle_avatar(base: Image.Image, avatar: Image.Image | None, initials: str,
                    x: int, y: int, d: int) -> None:
    draw = ImageDraw.Draw(base)
    if avatar:
        try:
            av = avatar.copy().convert("RGBA").resize((d, d), Image.LANCZOS)
            mask = Image.new("L", (d, d), 0)
            ImageDraw.Draw(mask).ellipse([0, 0, d - 1, d - 1], fill=255)
            buf = Image.new("RGBA", (d, d))
            buf.paste(av, (0, 0))
            base.paste(buf, (x, y), mask)
            draw.ellipse([x - 3, y - 3, x + d + 2, y + d + 2], outline=GLOW, width=3)
            return
        except Exception:
            pass
    draw.ellipse([x, y, x + d, y + d], fill=PRIMARY)
    draw.ellipse([x - 3, y - 3, x + d + 2, y + d + 2], outline=GLOW, width=3)
    ini = (initials[:2] if len(initials) >= 2 else initials or "?").upper()
    f = _f(_BOLD, int(d * 0.36))
    fw = _tw(draw, ini, f)
    draw.text((x + (d - fw) // 2, y + int(d * 0.28)), ini, font=f, fill=WHITE)


def _stat_icon(draw: ImageDraw.ImageDraw, cx: int, cy: int, r: int, kind: str) -> None:
    """Icon flat sederhana pake shape PIL doang -- bukan emoji, sama
    alasannya kayak leaderboard_image.py (font emoji gak ke-bundle)."""
    draw.rounded_rectangle([cx - r, cy - r, cx + r, cy + r], radius=int(r * 0.32),
                            fill=PRIMARY, outline=GLOW, width=2)
    ir = int(r * 0.5)
    if kind == "wallet":
        draw.rounded_rectangle(
            [cx - ir, cy - int(ir * 0.7), cx + ir, cy + int(ir * 0.7)],
            radius=int(ir * 0.25), outline=WHITE, width=3,
        )
        draw.ellipse(
            [cx + ir * 0.15, cy - int(ir * 0.2), cx + ir * 0.15 + int(ir * 0.4), cy + int(ir * 0.2)],
            fill=WHITE,
        )
    elif kind == "coins":
        for dy in (-int(ir * 0.32), 0, int(ir * 0.32)):
            draw.ellipse([cx - ir, cy + dy - int(ir * 0.26), cx + ir, cy + dy + int(ir * 0.26)],
                         outline=WHITE, width=3)
    else:  # points
        draw.ellipse([cx - ir, cy - ir, cx + ir, cy + ir], outline=WHITE, width=3)
        f = _f(_BOLD, int(ir * 1.1))
        txt = "$"
        tw_ = _tw(draw, txt, f)
        draw.text((cx - tw_ // 2, cy - int(ir * 0.62)), txt, font=f, fill=WHITE)


def _chip(draw: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int) -> None:
    draw.rounded_rectangle([x, y, x + w, y + h], radius=int(h * 0.28),
                           fill=CHIP_LIGHT, outline=CHIP_DARK, width=3)
    for i in range(1, 3):
        lx = x + w * i // 3
        draw.line([(lx, y), (lx, y + h)], fill=CHIP_DARK, width=2)
    draw.line([(x, y + h // 2), (x + w, y + h // 2)], fill=CHIP_DARK, width=2)


def generate_card_image(
    *,
    username: str,
    avatar: Image.Image | None,
    credit_balance: float,
    currency_label: str,
    noctoins: int,
    server_points: int,
    tier: str = "standard",
) -> BytesIO:
    """`avatar` PIL Image (RGBA) atau None -- fallback ke inisial nama kalau
    gagal di-fetch, sama pola kayak leaderboard_image.py."""
    S = SS
    w, h = IMG_W * S, IMG_H * S
    pad = PAD * S
    radius = RADIUS * S

    img = _bg_gradient(w, h)
    img = Image.alpha_composite(img.convert("RGBA"), _swoosh_glow(w, h))

    # Rounded card frame -- crop ke bentuk rounded-rect, baru gambar border-nya.
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, w - 1, h - 1], radius=radius, fill=255)
    framed = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    framed.paste(img, (0, 0), mask)
    img = framed
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([2 * S, 2 * S, w - 2 * S, h - 2 * S], radius=radius,
                           outline=GLOW, width=3 * S)

    # Wordmark
    f_brand = _f(_BOLD, 108 * S)
    _gradient_text(img, (pad, 60 * S), "Noctra", f_brand, CHIP_LIGHT, GLOW)

    # Tier label, kanan atas
    f_tier = _f(_REG, 34 * S)
    tier_w = _tw(draw, tier, f_tier)
    draw.text((w - pad - tier_w, 66 * S), tier, font=f_tier, fill=WHITE)

    # Baris stat: Credit, Noctoins, Server Points
    f_stat = _f(_REG, 40 * S)
    stats = [
        ("wallet", f"{credit_balance:,.0f} {currency_label}"),
        ("coins", f"{noctoins} Noctoins"),
        ("points", f"{server_points} Server Points"),
    ]
    icon_r = 34 * S
    row_gap = 96 * S
    start_y = 300 * S
    for i, (kind, label) in enumerate(stats):
        cy = start_y + i * row_gap
        _stat_icon(draw, pad + icon_r, cy, icon_r, kind)
        draw.text((pad + icon_r * 2 + 24 * S, cy - 20 * S), label, font=f_stat, fill=WHITE)

    # Chip (niru posisi kartu kredit fisik) + pola titik di kanan bawah
    chip_w, chip_h = 210 * S, 150 * S
    chip_x = w - pad - chip_w
    chip_y = int(h * 0.32)
    _chip(draw, chip_x, chip_y, chip_w, chip_h)

    dot_y = h - pad - 20 * S
    dot_r = 10 * S
    dot_gap = 60 * S
    dot_x0 = w - pad - dot_r * 2 - dot_gap * 3
    for i in range(4):
        dx = dot_x0 + i * dot_gap
        draw.ellipse([dx, dot_y - dot_r, dx + dot_r * 2, dot_y + dot_r], fill=WHITE)

    # Avatar + username, kiri bawah
    av_d = 96 * S
    av_x = pad
    av_y = h - pad - av_d
    _circle_avatar(img, avatar, username, av_x, av_y, av_d)
    draw = ImageDraw.Draw(img)  # re-acquire abis paste ops, sama kayak leaderboard_image.py
    f_user = _f(_BOLD, 40 * S)
    draw.text((av_x + av_d + 28 * S, av_y + av_d // 2 - 22 * S), username[:24], font=f_user, fill=WHITE)

    final = img.convert("RGB").resize((IMG_W, IMG_H), Image.LANCZOS)
    buf = BytesIO()
    final.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf
