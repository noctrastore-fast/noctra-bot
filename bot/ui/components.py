"""
Layout builder buat Discord Components V2 -- pengganti sebagian embed di
embeds.py buat kartu-kartu yang paling sering dilihat customer (invoice,
pengumuman pembelian, detail produk).

Kenapa modul terpisah dari embeds.py: sebuah pesan gak bisa nyampur embed
klasik sama Components V2 -- begitu satu pesan pake LayoutView, dia gak
boleh punya `content`/`embed` sama sekali, semuanya (teks, gambar, tombol)
harus jadi komponen. Jadi builder di sini return `discord.ui.LayoutView`
siap kirim (lewat `view=...`), bukan `discord.Embed`.

Perbedaan visual yang perlu diinget dibanding embed lama:
  * Gak ada "inline field" yang sejajar kayak kolom -- semua ditumpuk jadi
    blok teks markdown (label tebal di atas, value di bawahnya).
  * Gak ada footer/timestamp otomatis -- ditulis manual sebagai baris
    "-# ..." (subtext markdown Discord, teks kecil abu-abu).
  * Warna aksen tampil sebagai garis warna di sisi kiri Container, bukan
    border penuh kayak embed.

Referensi API: discord.py >= 2.6 (Container, Section, TextDisplay,
Thumbnail, MediaGallery, Separator, LayoutView semua ada di discord.ui).
"""

from __future__ import annotations

from datetime import datetime

import discord

from bot.core.emojis import EMOJI_SUCCESS
from bot.core.theme import COLOR_ACCENT, COLOR_PRIMARY, COLOR_SUCCESS, FOOTER_TEXT, MARK_DASH, star_rating
from bot.utils.helpers import calculate_final_price, discount_label, format_price


class NoctraLayout(discord.ui.LayoutView):
    """Layout generik satu-Container -- bungkus Container yang udah jadi
    biar call site bisa langsung `view=components.invoice_view(...)`, mirip
    pola lama `embed=embeds.order_invoice_embed(...)`."""

    def __init__(self, container: discord.ui.Container, *, timeout: float | None = None) -> None:
        super().__init__(timeout=timeout)
        self.add_item(container)


def _footer_line(extra: str | None = None) -> str:
    """Subtext markdown ("-# ...") -- pengganti footer otomatis embed yang
    gak ada di Components V2."""
    text = FOOTER_TEXT if not extra else f"{FOOTER_TEXT}  {MARK_DASH}  {extra}"
    return f"-# {text}"


# -- Panel toko -----------------------------------------------------------------

def shop_panel_container(
    title: str,
    description: str,
    image_url: str | None = None,
    thumbnail_url: str | None = None,
) -> discord.ui.Container:
    """Isi panel /settings shop_panel -- staff isi title/description/gambar
    sendiri lewat parameter command, jadi teks (termasuk bullet list custom
    kayak "» ...") dirender apa adanya, gak diapa-apain sama builder ini.
    Gak ada footer text di sini biar clean -- tombolnya (ditempel sama
    ShopPanelView) udah cukup nutup card-nya."""
    header_text = discord.ui.TextDisplay(f"## {title}\n{description}")
    header = (
        discord.ui.Section(header_text, accessory=discord.ui.Thumbnail(media=thumbnail_url))
        if thumbnail_url
        else header_text
    )

    children: list = [header]
    if image_url:
        children.append(discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small))
        children.append(discord.ui.MediaGallery(discord.MediaGalleryItem(media=image_url)))

    return discord.ui.Container(*children, accent_colour=COLOR_PRIMARY)


# -- Invoice ------------------------------------------------------------------

def invoice_view(
    order_row,
    product_row,
    payment_row,
    bot_avatar_url: str | None = None,
) -> discord.ui.LayoutView:
    """Struk yang dikirim begitu order ditandain selesai. `bot_avatar_url`
    diambil langsung dari foto profil bot -- ganti icon bot, struk ini
    otomatis ikut ganti, gak perlu setting manual apapun."""
    invoice_number = f"NOCTRA-{order_row['id']:06d}"
    completed_ts = int(datetime.utcnow().timestamp())

    header_text = discord.ui.TextDisplay(
        f"## {EMOJI_SUCCESS} Invoice {invoice_number}\nMakasih udah belanja -- ini struk pembelian kamu."
    )
    header = (
        discord.ui.Section(header_text, accessory=discord.ui.Thumbnail(media=bot_avatar_url))
        if bot_avatar_url
        else header_text
    )

    lines = [f"**Barang**\n{product_row['name']}"]
    lines.append(f"**Total Bayar**\n{format_price(order_row['total_price'], order_row['currency_label'])}")
    if payment_row:
        lines.append(f"**Metode Bayar**\n{payment_row['name']}")
    lines.append(f"**Order ID**\n#{order_row['id']}")
    lines.append(f"**Selesai**\n<t:{completed_ts}:f>")
    detail_block = discord.ui.TextDisplay("\n\n".join(lines))

    container = discord.ui.Container(
        header,
        discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
        detail_block,
        discord.ui.Separator(visible=False),
        discord.ui.TextDisplay(_footer_line("Simpan ini buat catatan kamu ya")),
        accent_colour=COLOR_SUCCESS,
    )
    return NoctraLayout(container, timeout=None)


# Pengumuman pembelian ("Pembelian Baru") sempet dicoba di sini pake
# Components V2, tapi di-revert balik ke embed klasik -- lihat
# bot.ui.embeds.purchase_announcement_embed().


# -- Detail produk --------------------------------------------------------------

def product_detail_container(product, fields: list, rating_summary: dict) -> discord.ui.Container:
    """Return Container aja (bukan LayoutView lengkap) -- caller (views.py)
    yang nempelin ActionRow tombol Beli Sekarang / Kembali, soalnya tombol
    itu butuh callback yang nyambung ke alur checkout lain."""
    final = calculate_final_price(product["base_price"], product["discount_type"], product["discount_value"])
    price_text = format_price(final, product["currency_label"])
    dlabel = discount_label(product["discount_type"], product["discount_value"])

    title_line = f"## {product['emoji']} {product['name']}" if product["emoji"] else f"## {product['name']}"
    description = product["description"] or "Belum ada deskripsi."
    header_text = discord.ui.TextDisplay(f"{title_line}\n{description}")
    header = (
        discord.ui.Section(header_text, accessory=discord.ui.Thumbnail(media=product["image_url"]))
        if product["image_url"]
        else header_text
    )

    price_line = f"**{price_text}**"
    if dlabel:
        price_line += f"  {MARK_DASH}  {dlabel} (awalnya {format_price(product['base_price'], product['currency_label'])})"
    type_label = product["product_type"].replace("_", " ").title()
    stock_text = "Unlimited" if product["stock_type"] == "unlimited" else f"Sisa {product['stock_quantity']}"

    info_block = discord.ui.TextDisplay(
        f"**Harga**\n{price_line}\n\n**Tipe**\n{type_label}\n\n**Stok**\n{stock_text}"
    )

    children: list = [
        header,
        discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
        info_block,
    ]

    if fields:
        req = [f["label"] for f in fields if f["required"]]
        opt = [f["label"] for f in fields if not f["required"]]
        field_text = ""
        if req:
            field_text += "Wajib diisi: " + ", ".join(req)
        if opt:
            field_text += ("\n" if field_text else "") + "Opsional: " + ", ".join(opt)
        children.append(discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small))
        children.append(discord.ui.TextDisplay(f"**Data yang Dibutuhin Pas Checkout**\n{field_text}"))

    children.append(discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small))
    if rating_summary["total"]:
        stars = star_rating(rating_summary["average"])
        rating_text = f"{rating_summary['average']:.1f}/5 {MARK_DASH} {stars} {MARK_DASH} {rating_summary['total']} ulasan"
    else:
        rating_text = "Belum ada ulasan nih."
    children.append(discord.ui.TextDisplay(f"**Rating**\n{rating_text}"))

    children.append(discord.ui.Separator(visible=False))
    children.append(discord.ui.TextDisplay(_footer_line()))

    return discord.ui.Container(*children, accent_colour=COLOR_PRIMARY)


# -- Sambutan Member Baru --------------------------------------------------------

def welcome_container(
    member: discord.Member,
    title: str,
    description: str,
    footer_text: str,
    banner_url: str | None = None,
    color: int = COLOR_ACCENT,
) -> discord.ui.Container:
    """Card sambutan member baru -- gantiin embeds.welcome_embed() lama,
    dipindah ke Components V2 biar tiap bagian (judul, deskripsi, tanggal
    gabung, banner, footer) kepisah jelas pake garis Separator selebar
    card, bukan numpuk jadi satu blok teks kayak embed klasik. Title sendiri
    yang nempel ke thumbnail avatar member (biar avatar tetep sejajar sama
    judulnya), deskripsi turun jadi blok sendiri full-width di bawah garis.

    PENTING soal mention/ping: placeholder {mention} di title/description
    (udah diganti jadi member.mention beneran sama _render_template() di
    welcome.py sebelum nyampe sini) BAKAL NGE-PING beneran begitu kekirim,
    beda sama embed klasik yang gak PERNAH ping apapun formatnya -- soalnya
    TextDisplay di Components V2 diperlakuin kayak message content asli
    buat urusan notifikasi (bukan kayak field embed). Nyala/mati-nya ping
    tetep dikontrol dari LUAR fungsi ini lewat parameter `allowed_mentions`
    pas channel.send() (lihat welcome.py._send_welcome), BUKAN dari sini --
    biar toggle /welcome mention tetep konsisten kepake gimanapun staff
    nulis template judul/deskripsinya sendiri."""
    header_title = discord.ui.TextDisplay(f"## {title}")
    header = discord.ui.Section(header_title, accessory=discord.ui.Thumbnail(media=member.display_avatar.url))

    joined_at = member.joined_at or discord.utils.utcnow()
    joined_ts = int(joined_at.timestamp())
    join_block = discord.ui.TextDisplay(
        f"**Bergabung**\n<t:{joined_ts}:F>  ({MARK_DASH} <t:{joined_ts}:R>)"
    )

    children: list = [
        header,
        discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
        discord.ui.TextDisplay(description),
        discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
        join_block,
    ]

    if banner_url:
        children.append(discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small))
        children.append(discord.ui.MediaGallery(discord.MediaGalleryItem(media=banner_url)))

    if footer_text:
        children.append(discord.ui.Separator(visible=False))
        # Icon footer SENGAJA gak ada (dulu ada, dicabut atas request Nikss --
        # bikin baris footer jarak kosong gede/gak rapi soalnya Section
        # selalu ngisi lebar penuh card). Emoji custom bisa langsung ditempel
        # di teks footer-nya sendiri (markdown biasa, sama kayak title/desc)
        # kalau butuh aksen visual, gak perlu icon terpisah.
        children.append(discord.ui.TextDisplay(f"-# {footer_text}"))

    return discord.ui.Container(*children, accent_colour=color)


# -- Review publik & bukti foto -------------------------------------------------

def review_card_container(
    review_row,
    product_row,
    author_display: str,
    emoji_title: str,
    emoji_user: str,
    emoji_product: str,
    emoji_star_filled: str,
    emoji_star_empty: str,
    emoji_message: str,
    author_avatar_url: str | None = None,
    banner_url: str | None = None,
    verified: bool = True,
) -> discord.ui.Container:
    """Kartu review publik yang diposting ke /settings reviews_channel abis
    staff approve -- ini social proof/reputasi toko, jadi didesain buat
    dibaca cepet: judul tebal + baris User/Product/Rating masing-masing
    pake emoji custom di depannya (bukan field embed klasik). Emoji-nya
    diatur staff lewat /settings review_emoji, sekali ganti kepake di semua
    kartu review berikutnya (bukan per-review)."""
    header_text = discord.ui.TextDisplay(f"## {emoji_title} REVIEW BARU #{review_row['id']}")
    header = (
        discord.ui.Section(header_text, accessory=discord.ui.Thumbnail(media=author_avatar_url))
        if author_avatar_url
        else header_text
    )

    stars = emoji_star_filled * review_row["rating"] + emoji_star_empty * (5 - review_row["rating"])
    detail_block = discord.ui.TextDisplay(
        f"{emoji_user} **User** : {author_display}\n"
        f"{emoji_product} **Product** : {product_row['name']}\n"
        f"{emoji_star_filled} **Rating** : {stars}"
    )

    children: list = [
        header,
        discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
        detail_block,
    ]

    if review_row["review_text"]:
        children.append(discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small))
        children.append(discord.ui.TextDisplay(f"{emoji_message} **Pesan**\n> {review_row['review_text']}"))

    # Beda dari author_avatar_url (thumbnail kecil di header): ini foto
    # BESAR full-width, diambil dari foto yang customer kirim sendiri kalau
    # ada, fallback ke banner default staff (/settings review_banner_image)
    # kalau enggak.
    banner = review_row["image_url"] or banner_url
    if banner:
        children.append(discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small))
        children.append(discord.ui.MediaGallery(discord.MediaGalleryItem(media=banner)))

    children.append(discord.ui.Separator(visible=False))
    badge = "Pembelian Terverifikasi" if verified else "Belum Terverifikasi"
    children.append(discord.ui.TextDisplay(_footer_line(badge)))

    return discord.ui.Container(*children, accent_colour=COLOR_PRIMARY)


def testi_proof_container(
    buyer_display: str,
    product_name: str,
    price_text: str,
    testi_number: int,
    photo_url: str,
    emoji_title: str,
    emoji_buyer: str,
    emoji_product: str,
    emoji_price: str,
    emoji_testi: str,
) -> discord.ui.Container:
    """Notifikasi INTERNAL buat staff begitu foto bukti review masuk lewat
    DM (lihat bot.cogs.review_photo) -- BEDA dari review_card_container di
    atas yang showcase publik nunggu approve dulu; ini langsung kekirim ke
    channel staff (/settings testi_proof_channel) pas fotonya baru aja
    masuk, biar staff bisa langsung cross-check tanpa nunggu approval
    flow. Foto-nya WAJIB ada (caller yang mastiin sebelum manggil ini)."""
    header = discord.ui.TextDisplay(f"## {emoji_title} TESTI MONEY")

    detail_block = discord.ui.TextDisplay(
        f"{emoji_buyer} **Buyer** : {buyer_display}\n"
        f"{emoji_product} **Product** : {product_name}\n"
        f"{emoji_price} **Price** : {price_text}\n"
        f"{emoji_testi} **Testi** : #{testi_number}"
    )
    detail_section = discord.ui.Section(detail_block, accessory=discord.ui.Thumbnail(media=photo_url))

    container = discord.ui.Container(
        header,
        discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small),
        detail_section,
        accent_colour=COLOR_PRIMARY,
    )
    return container
