"""
Interactive Views buat NOCTRA: browsing toko (Category -> Category Type ->
Product select), wizard pembelian (dynamic fields -> payment select ->
konfirmasi order), tombol kontrol ticket persistent (support umum aja), dan
alur review button-only (tombol rating -> modal teks opsional).

Gak ada konsep "variant" -- tiap produk di bawah category type itu barang
sendiri yang harganya independen penuh. Dynamic checkout fields nempel di
category type dan otomatis dishare sama semua produk di bawahnya.

Wizard pembelian dan alur review berbasis DM: abis klik "Buy Now" pertama
kali di channel guild, semua langkah selanjutnya (modal dynamic field,
payment select, konfirmasi order, instruksi bayar, dan nanti prompt review)
terjadi di DM customer. Ini bikin seluruh toko guild-agnostic by design --
katalog/order/review yang sama tetep jalan di server manapun bot ini
diundang, soalnya gak ada satupun yang customer-facing yang bergantung ke
channel ticket per-guild. Staff kelola order lewat command `/order` atau
channel order-log opsional (`/settings order_log_channel`).

Persistent views/items (survive restart bot):
  - Custom_id statis, didaftarin lewat `add_view` di setup_hook:
    ShopPanelView, TicketControlView, TicketClaimedView, TicketReopenView,
    OpenTicketPanelView.
  - Custom_id dinamis (id order/rating ke-encode di id-nya sendiri),
    didaftarin lewat `add_dynamic_items` di setup_hook: OrderActionButton,
    ReviewStartButton.
"""

from __future__ import annotations

import discord

from bot.core.logger import logger
from bot.core.theme import COLOR_ACCENT
from bot.database.queries import (
    categories as categories_q,
    category_types as category_types_q,
    fields as fields_q,
    orders as orders_q,
    payments as payments_q,
    products as products_q,
    reviews as reviews_q,
    tickets as tickets_q,
)
from bot.ui import components, embeds
from bot.ui.modals import MessageModal, ReasonModal, ReviewTextModal, collect_dynamic_fields
from bot.utils import order_actions, ticket_actions
from bot.utils.helpers import RuntimeSettings, calculate_final_price
from bot.utils.permissions import is_staff
from bot.utils.validators import FieldValidationError, validate_field_value

MAX_SELECT_OPTIONS = 25


async def build_join_server_view(db) -> discord.ui.View | None:
    """Tombol link "Gabung Server" -- ditampilin abis customer selesai
    kasih review, ngarahin mereka ke server utama toko. Return None kalau
    link invite-nya belum diatur (/settings main_server_invite), biar
    caller bisa skip nampilin view sama sekali. Tombol link gak butuh
    custom_id dan gak persistent -- Discord yang handle klik-nya langsung
    di sisi client buat buka URL, gak ada interaction yang balik ke bot."""
    runtime = RuntimeSettings(db)
    invite_url = await runtime.main_server_invite_url()
    if not invite_url:
        return None
    view = discord.ui.View(timeout=None)
    view.add_item(discord.ui.Button(label="Gabung Server", style=discord.ButtonStyle.link, url=invite_url))
    return view


# ============================================================================
# BROWSING TOKO (Category -> Category Type -> Product)
# ============================================================================

class CategorySelect(discord.ui.Select):
    def __init__(self, categories: list):
        options = [
            discord.SelectOption(
                label=cat["name"][:100],
                value=str(cat["id"]),
                description=(cat["description"] or "")[:100] or None,
                emoji=cat["emoji"] or None,
            )
            for cat in categories[:MAX_SELECT_OPTIONS]
        ]
        super().__init__(placeholder="Pilih kategori...", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        db = interaction.client.db  # type: ignore[attr-defined]
        category_id = int(self.values[0])
        category = await categories_q.get_category(db, category_id)
        category_types = await category_types_q.list_category_types(db, category_id=category_id, enabled_only=True)
        embed = embeds.base_embed(
            f"NOCTRA -- {category['emoji'] + ' ' if category['emoji'] else ''}{category['name']}",
            "Pilih tipe di bawah buat liat produknya.",
            color=COLOR_ACCENT,
        )
        if not category_types:
            embed.description = "Belum ada tipe produk di kategori ini."
        view = CategoryTypeBrowseView(category, category_types)
        await interaction.response.edit_message(embed=embed, view=view)


class CategoryBrowseView(discord.ui.View):
    def __init__(self, categories: list):
        super().__init__(timeout=300)
        self.add_item(CategorySelect(categories))


class CategoryTypeSelect(discord.ui.Select):
    def __init__(self, category_types: list):
        options = [
            discord.SelectOption(
                label=ct["name"][:100],
                value=str(ct["id"]),
                description=(ct["description"] or "")[:100] or None,
                emoji=ct["emoji"] or None,
            )
            for ct in category_types[:MAX_SELECT_OPTIONS]
        ]
        super().__init__(placeholder="Pilih tipe...", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        db = interaction.client.db  # type: ignore[attr-defined]
        category_type_id = int(self.values[0])
        category_type = await category_types_q.get_category_type(db, category_type_id)
        products = await products_q.list_products(db, category_type_id=category_type_id, visible_only=True)
        embed = embeds.product_list_embed(category_type, products)
        view = ProductBrowseView(category_type, products)
        await interaction.response.edit_message(embed=embed, view=view)


class BackToCategoriesButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(label="Kembali", style=discord.ButtonStyle.secondary)

    async def callback(self, interaction: discord.Interaction) -> None:
        db = interaction.client.db  # type: ignore[attr-defined]
        categories = await categories_q.list_categories(db, enabled_only=True)
        embed = embeds.base_embed(
            "NOCTRA STORE", "Pilih kategori di bawah buat liat produk yang ada.", color=COLOR_ACCENT
        )
        view = CategoryBrowseView(categories)
        await interaction.response.edit_message(embed=embed, view=view)


class CategoryTypeBrowseView(discord.ui.View):
    def __init__(self, category, category_types: list) -> None:
        super().__init__(timeout=300)
        if category_types:
            self.add_item(CategoryTypeSelect(category_types))
        self.add_item(BackToCategoriesButton())


class ProductSelect(discord.ui.Select):
    def __init__(self, products: list):
        options = [
            discord.SelectOption(
                label=p["name"][:100], value=str(p["id"]), emoji=p["emoji"] or None
            )
            for p in products[:MAX_SELECT_OPTIONS]
        ]
        super().__init__(placeholder="Liat produk...", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        db = interaction.client.db  # type: ignore[attr-defined]
        product_id = int(self.values[0])
        product = await products_q.get_product(db, product_id)
        fields = await fields_q.list_fields(db, product["category_type_id"])
        rating_summary = await reviews_q.get_rating_summary(db, product_id)
        view = ProductDetailView(product, fields, rating_summary)
        # Discord ngewajibin embed lama di-clear eksplisit pas pesan pindah
        # ke Components V2 -- kalau enggak, edit-nya ditolak dan interaction
        # timeout ("didn't respond in time") tanpa pesan error yang jelas.
        await interaction.response.edit_message(embed=None, view=view)


class BackToCategoryTypesButton(discord.ui.Button):
    def __init__(self, category_id: int) -> None:
        super().__init__(label="Kembali", style=discord.ButtonStyle.secondary)
        self.category_id = category_id

    async def callback(self, interaction: discord.Interaction) -> None:
        db = interaction.client.db  # type: ignore[attr-defined]
        category = await categories_q.get_category(db, self.category_id)
        category_types = await category_types_q.list_category_types(db, category_id=self.category_id, enabled_only=True)
        embed = embeds.base_embed(
            f"NOCTRA -- {category['emoji'] + ' ' if category and category['emoji'] else ''}{category['name'] if category else ''}",
            "Pilih tipe di bawah buat liat produknya.",
            color=COLOR_ACCENT,
        )
        view = CategoryTypeBrowseView(category, category_types)
        await interaction.response.edit_message(embed=embed, view=view)


class ProductBrowseView(discord.ui.View):
    def __init__(self, category_type, products: list) -> None:
        super().__init__(timeout=300)
        if products:
            self.add_item(ProductSelect(products))
        self.add_item(BackToCategoryTypesButton(category_type["category_id"] if category_type else 0))


class BuyButton(discord.ui.Button):
    def __init__(self, product) -> None:
        super().__init__(label="Beli Sekarang", style=discord.ButtonStyle.success)
        self.product = product

    async def callback(self, interaction: discord.Interaction) -> None:
        await start_purchase(interaction, self.product["id"])


class BackFromProductDetailButton(discord.ui.Button):
    """Tombol Kembali khusus buat kartu produk Components V2. Discord GAK
    ngebolehin ngedit pesan yang udah kepake Components V2 balik ke embed
    klasik (batasan permanen dari API-nya, bukan bug) -- jadi daripada
    edit_message() pesan kartu ini, tombol ini kirim pesan ephemeral BARU
    yang isinya browsing embed klasik. Kartu V2 yang lama dibiarin apa
    adanya (customer bisa dismiss sendiri lewat "Dismiss message")."""

    def __init__(self, category_id: int) -> None:
        super().__init__(label="Kembali", style=discord.ButtonStyle.secondary)
        self.category_id = category_id

    async def callback(self, interaction: discord.Interaction) -> None:
        db = interaction.client.db  # type: ignore[attr-defined]
        category = await categories_q.get_category(db, self.category_id)
        category_types = await category_types_q.list_category_types(db, category_id=self.category_id, enabled_only=True)
        embed = embeds.base_embed(
            f"NOCTRA -- {category['emoji'] + ' ' if category and category['emoji'] else ''}{category['name'] if category else ''}",
            "Pilih tipe di bawah buat liat produknya.",
            color=COLOR_ACCENT,
        )
        view = CategoryTypeBrowseView(category, category_types)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


class ProductDetailView(discord.ui.LayoutView):
    """Kartu detail produk -- Components V2. Isinya (harga/tipe/stok/rating)
    dibangun sama components.product_detail_container(), tombol Beli
    Sekarang & Kembali ditempel di sini soalnya butuh callback yang nyambung
    ke alur checkout/browsing lain."""

    def __init__(self, product, fields: list, rating_summary: dict) -> None:
        super().__init__(timeout=300)
        container = components.product_detail_container(product, fields, rating_summary)
        container.add_item(
            discord.ui.ActionRow(
                BuyButton(product),
                BackFromProductDetailButton(product["category_type_id"]),
            )
        )
        self.add_item(container)


class ShopPanelView(discord.ui.LayoutView):
    """Panel persistent yang diposting sekali lewat /settings shop_panel --
    Components V2. Customer klik ini daripada jalanin /shop -- browsing
    sepenuhnya lewat tombol.

    custom_id-nya tetep sama ("noctra:shop:browse") jadi ini tetep jalan
    abis bot restart -- yang dicocokin Discord buat routing klik tombol
    cuma custom_id-nya, bukan isi title/description/gambar panel (itu baked
    di message pas awal diposting, gak perlu match persis pas restart)."""

    def __init__(
        self,
        title: str = "NOCTRA STORE",
        description: str = "Klik di bawah buat jelajahin katalog dan pesen -- gak perlu command.",
        image_url: str | None = None,
        thumbnail_url: str | None = None,
        button_label: str = "Jelajahi Toko",
    ) -> None:
        super().__init__(timeout=None)
        container = components.shop_panel_container(title, description, image_url, thumbnail_url)

        button = discord.ui.Button(
            label=button_label[:80], style=discord.ButtonStyle.secondary, custom_id="noctra:shop:browse"
        )
        button.callback = self.browse
        container.add_item(discord.ui.Separator(visible=True, spacing=discord.SeparatorSpacing.small))
        container.add_item(discord.ui.ActionRow(button))

        self.add_item(container)

    async def browse(self, interaction: discord.Interaction) -> None:
        db = interaction.client.db  # type: ignore[attr-defined]
        categories = await categories_q.list_categories(db, enabled_only=True)
        embed = embeds.base_embed(
            "NOCTRA STORE", "Pilih kategori di bawah buat liat produk yang ada.", color=COLOR_ACCENT
        )
        if not categories:
            embed.description = "Toko belum ada kategori yang aktif nih. Cek lagi nanti ya."
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return
        await interaction.response.send_message(
            embed=embed, view=CategoryBrowseView(categories), ephemeral=True
        )


# ============================================================================
# WIZARD PEMBELIAN (berbasis DM)
# ============================================================================

async def start_purchase(interaction: discord.Interaction, product_id: int) -> None:
    db = interaction.client.db  # type: ignore[attr-defined]
    product = await products_q.get_product(db, product_id)
    if not product or not product["visible"]:
        await interaction.response.send_message(
            embed=embeds.error_embed("Produk ini lagi gak tersedia."), ephemeral=True
        )
        return
    if product["stock_type"] == "manual" and product["stock_quantity"] <= 0:
        await interaction.response.send_message(
            embed=embeds.error_embed("Stok produk ini lagi abis."), ephemeral=True
        )
        return

    dm_channel = await interaction.user.create_dm()
    embed = embeds.info_embed(
        "Lanjutin Order Kamu", f"Klik di bawah buat lanjutin pesen **{product['name']}**."
    )
    try:
        await dm_channel.send(embed=embed, view=ContinueOrderView(product))
    except discord.Forbidden:
        await interaction.response.send_message(
            embed=embeds.error_embed(
                "Gak bisa kirim DM ke kamu buat lanjutin checkout. Aktifin dulu "
                '"Allow direct messages from server members" di Privacy Settings '
                "server ini, terus coba lagi ya."
            ),
            ephemeral=True,
        )
        return

    await interaction.response.send_message(
        embed=embeds.success_embed("Cek DM kamu buat lanjutin order ya."), ephemeral=True
    )


async def _delete_source_message(interaction: discord.Interaction) -> None:
    """Hapus pesan DM yang nempel di tombol/select ini, begitu tugasnya
    kelar -- ini yang bikin prompt "Lanjutin Order" / "Pilih Metode
    Pembayaran" gak numpuk terus, gak peduli order-nya kelar atau enggak
    (ringkasan order sendiri dibersihin terpisah, pas selesai, lewat
    tracking order_dm_messages)."""
    message = interaction.message
    if message is None:
        return
    try:
        await message.delete()
    except discord.HTTPException:
        pass  # udah ilang, atau entah kenapa gak bisa dihapus -- gapapa diabaikan


class ContinueOrderButton(discord.ui.Button):
    """Ngasih customer sesuatu buat diklik di DM mereka biar Modal bisa
    dibuka buat checkout fields, soalnya Discord cuma ngebolehin buka Modal
    sebagai respon ke interaction komponen, gak bisa dari pesan bot biasa."""

    def __init__(self, product) -> None:
        super().__init__(label="Lanjutin Order", style=discord.ButtonStyle.success)
        self.product = product

    async def callback(self, interaction: discord.Interaction) -> None:
        await proceed_to_fields(interaction, self.product)
        await _delete_source_message(interaction)


class ContinueOrderView(discord.ui.View):
    def __init__(self, product) -> None:
        super().__init__(timeout=600)
        self.add_item(ContinueOrderButton(product))


async def proceed_to_fields(interaction: discord.Interaction, product) -> None:
    db = interaction.client.db  # type: ignore[attr-defined]
    fields = await fields_q.list_fields(db, product["category_type_id"])

    if not fields:
        await proceed_to_payment(interaction, product, [])
        return

    async def on_fields_complete(inter: discord.Interaction, values_by_id: dict) -> None:
        field_rows = {f["id"]: f for f in fields}
        cleaned, errors = [], []
        for field_id, raw_value in values_by_id.items():
            f = field_rows[field_id]
            try:
                value = validate_field_value(
                    raw_value,
                    required=bool(f["required"]),
                    min_length=f["min_length"],
                    max_length=f["max_length"],
                    validation=f["validation"],
                    label=f["label"],
                )
                cleaned.append({"label": f["label"], "field_type": f["field_type"], "value": value})
            except FieldValidationError as exc:
                errors.append(str(exc))

        if errors:
            await inter.response.send_message(
                embed=embeds.error_embed("\n".join(errors)), ephemeral=False
            )
            return
        await proceed_to_payment(inter, product, cleaned)

    await collect_dynamic_fields(interaction, fields, on_fields_complete)


async def proceed_to_payment(interaction: discord.Interaction, product, field_values: list) -> None:
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=False, thinking=True)

    db = interaction.client.db  # type: ignore[attr-defined]
    methods = await payments_q.list_payment_methods(db, enabled_only=True)

    if not methods:
        await interaction.followup.send(
            embed=embeds.error_embed(
                "Belum ada metode pembayaran yang diatur. Hubungin staff ya."
            ),
            ephemeral=False,
        )
        return

    if len(methods) == 1:
        await finalize_order(interaction, product, field_values, methods[0])
        return

    embed = embeds.info_embed("Pilih Metode Pembayaran", "Pilih cara kamu mau bayar.")
    view = PaymentSelectView(product, field_values, methods)
    await interaction.followup.send(embed=embed, view=view, ephemeral=False)


class PaymentSelect(discord.ui.Select):
    def __init__(self, product, field_values: list, methods: list):
        self.product = product
        self.field_values = field_values
        self.method_map = {str(m["id"]): m for m in methods}
        options = [
            discord.SelectOption(label=m["name"][:100], value=str(m["id"]))
            for m in methods[:MAX_SELECT_OPTIONS]
        ]
        super().__init__(placeholder="Pilih metode pembayaran...", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        method = self.method_map[self.values[0]]
        await finalize_order(interaction, self.product, self.field_values, method)
        await _delete_source_message(interaction)


class PaymentSelectView(discord.ui.View):
    def __init__(self, product, field_values: list, methods: list) -> None:
        super().__init__(timeout=180)
        self.add_item(PaymentSelect(product, field_values, methods))


async def finalize_order(interaction: discord.Interaction, product, field_values: list, payment) -> None:
    if not interaction.response.is_done():
        await interaction.response.defer(ephemeral=False, thinking=True)

    db = interaction.client.db  # type: ignore[attr-defined]
    unit_price = calculate_final_price(product["base_price"], product["discount_type"], product["discount_value"])

    stock_reserved = False
    if product["stock_type"] == "manual":
        fresh = await products_q.get_product(db, product["id"])
        if fresh["stock_quantity"] <= 0:
            await interaction.followup.send(
                embed=embeds.error_embed("Yah, produk ini baru aja abis stoknya."), ephemeral=False
            )
            return
        await products_q.adjust_stock(db, product["id"], -1)
        stock_reserved = True

    order_id = await orders_q.create_order(
        db,
        interaction.user.id,
        product["id"],
        payment["id"],
        unit_price,
        product["currency_label"],
        stock_reserved,
        payment["timeout_minutes"],
    )

    for fv in field_values:
        await orders_q.add_field_value(db, order_id, fv["label"], fv["field_type"], fv["value"])

    order_row = await orders_q.get_order(db, order_id)
    saved_fields = await orders_q.get_field_values(db, order_id)
    order_embed = embeds.order_summary_embed(order_row, product, payment, saved_fields)

    reply_embeds = [order_embed]
    if payment["instructions"] or payment["image_url"]:
        reply_embeds.append(
            embeds.info_embed(
                f"Pembayaran -- {payment['name']}",
                payment["instructions"] or "Scan QR code di bawah buat bayar.",
                image_url=payment["image_url"],
            )
        )
    reply_embeds.append(
        embeds.info_embed(
            "Udah Bayar?",
            "Kalau udah bayar, kirim bukti bayarnya (screenshot juga oke) "
            "langsung di DM ini -- bakal otomatis diterusin ke staff, "
            "ditandain sama nomor order ini, jadi gak bakal ketuker sama punya orang lain.",
        )
    )

    sent_message = await interaction.followup.send(
        content="Order kamu udah dibuat! Ini detailnya:",
        embeds=reply_embeds,
        ephemeral=False,
        wait=True,
    )
    if sent_message is not None:
        await orders_q.add_dm_message(db, order_id, sent_message.channel.id, sent_message.id)

    # Kabarin staff lewat channel order-log, kalau diatur. Ini jalan di
    # server manapun bot ada, soalnya channel-nya objek tetap bot-wide --
    # gak harus di guild yang sama tempat customer belanja.
    runtime = RuntimeSettings(db)
    log_channel_id = await runtime.order_log_channel_id()
    if log_channel_id:
        log_channel = interaction.client.get_channel(log_channel_id)
        if isinstance(log_channel, discord.TextChannel):
            staff_embed = embeds.order_summary_embed(order_row, product, payment, saved_fields)
            staff_embed.add_field(name="Customer", value=f"<@{interaction.user.id}> ({interaction.user})", inline=False)
            staff_view = discord.ui.View(timeout=None)
            for action in ("mark_paid", "mark_completed", "cancel", "refund"):
                staff_view.add_item(OrderActionButton(action, order_id))
            staff_view.add_item(ReplyButton(order_id))
            try:
                await log_channel.send(embed=staff_embed, view=staff_view)
            except discord.HTTPException:
                logger.exception("Gagal posting order #%s ke channel order-log.", order_id)

# ============================================================================
# KONTROL TICKET (persistent)
# ============================================================================

def _with_claim_field(embed: discord.Embed, claimant_mention: str | None) -> discord.Embed:
    """Return salinan `embed` dengan field "Diambil Oleh" diset (atau
    dihapus, kalau `claimant_mention` None) -- dipake bareng sama callback
    tombol claim/unclaim biar pesan ticket selalu nunjukin siapa yang lagi
    megang."""
    new_embed = embed.copy()
    for index, field in enumerate(new_embed.fields):
        if field.name == "Diambil Oleh":
            new_embed.remove_field(index)
            break
    if claimant_mention:
        new_embed.add_field(name="Diambil Oleh", value=claimant_mention, inline=True)
    return new_embed


def _source_embed(interaction: discord.Interaction) -> discord.Embed:
    """Embed yang lagi nempel di pesan ticket tempat tombol ini berada,
    dengan fallback aman kalau-kalau pesannya somehow gak punya embed."""
    if interaction.message and interaction.message.embeds:
        return interaction.message.embeds[0]
    return embeds.ticket_welcome_embed()


async def _handle_ticket_close(interaction: discord.Interaction) -> None:
    """Dipake bareng sama tombol Close Ticket di TicketControlView dan
    TicketClaimedView -- diambil atau enggak, cara nutupnya sama aja."""
    ticket = await tickets_q.get_ticket_by_channel(interaction.client.db, interaction.channel.id)  # type: ignore[attr-defined]
    if not ticket:
        await interaction.response.send_message(embed=embeds.error_embed("Ini bukan channel ticket."), ephemeral=True)
        return
    if not (await is_staff(interaction) or interaction.user.id == ticket["user_id"]):
        await interaction.response.send_message(
            embed=embeds.error_embed("Cuma staff atau pemilik ticket yang bisa nutup ticket ini."), ephemeral=True
        )
        return

    async def on_reason(inter: discord.Interaction, reason: str) -> None:
        await inter.response.defer(ephemeral=True)
        await ticket_actions.close_ticket(inter.client, inter.channel, str(inter.user), reason or None)
        await inter.followup.send(embed=embeds.success_embed("Ticket udah ditutup."), ephemeral=True)

    await interaction.response.send_modal(ReasonModal("Tutup Ticket", on_reason))


class TicketDeleteConfirmView(discord.ui.View):
    """Konfirmasi sesaat (gak persistent) buat tombol Hapus Channel --
    ngehapus channel itu permanen dan gak bisa di-undo, jadi ini mastiin
    staff emang niat klik sebelum kejadian."""

    def __init__(self, channel_id: int) -> None:
        super().__init__(timeout=20)
        self.channel_id = channel_id

    @discord.ui.button(label="Ya, Hapus Permanen", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        channel = interaction.client.get_channel(self.channel_id)  # type: ignore[attr-defined]
        if isinstance(channel, discord.TextChannel):
            try:
                await channel.delete(reason=f"Ticket dihapus sama {interaction.user}")
            except discord.HTTPException:
                await interaction.response.edit_message(
                    embed=embeds.error_embed("Gagal hapus channel -- cek permission bot ya."), view=None
                )
                return
        else:
            await interaction.response.edit_message(
                embed=embeds.error_embed("Channel udah gak ada."), view=None
            )
            return
        # Channel-nya udah ilang di titik ini, jadi gak ada lagi yang bisa
        # di-edit -- pesan ini cuma nyampe ke interaction ephemeral staff
        # itu sendiri, yang tetep disimpen Discord walau channel-nya udah
        # ilang.
        await interaction.response.edit_message(embed=embeds.success_embed("Channel udah dihapus."), view=None)
        self.stop()

    @discord.ui.button(label="Batal", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(embed=embeds.info_embed("Dibatalin", "Channel gak jadi dihapus."), view=None)
        self.stop()


class TicketReopenView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label="Buka Lagi Ticket", style=discord.ButtonStyle.primary, custom_id="noctra:ticket:reopen")
    async def reopen(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await is_staff(interaction):
            await interaction.response.send_message(
                embed=embeds.error_embed("Cuma staff yang bisa buka lagi ticket."), ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True)
        await ticket_actions.reopen_ticket(interaction.client, interaction.channel, str(interaction.user))
        await interaction.followup.send(embed=embeds.success_embed("Ticket udah dibuka lagi."), ephemeral=True)

    @discord.ui.button(label="Hapus Channel", style=discord.ButtonStyle.danger, custom_id="noctra:ticket:delete")
    async def delete_channel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await is_staff(interaction):
            await interaction.response.send_message(
                embed=embeds.error_embed("Cuma staff yang bisa hapus channel ticket."), ephemeral=True
            )
            return
        await interaction.response.send_message(
            embed=embeds.error_embed(
                "Ini bakal hapus channel ini secara permanen. Transcript-nya udah kesimpen "
                "(kalau log channel diatur), tapi channel-nya sendiri gak bisa balik lagi. Yakin?"
            ),
            view=TicketDeleteConfirmView(interaction.channel.id),
            ephemeral=True,
        )


ticket_actions._ReopenViewRef.set(TicketReopenView())


class TicketControlView(discord.ui.View):
    """Nempel di ticket support umum aja -- aksi khusus order (Mark
    Paid/Completed/Cancel/Refund) sekarang ada di OrderActionButton di
    channel order-log dan/atau command /order, soalnya order gak lagi bikin
    channel ticket per-order (lihat docstring module).

    Ini state *belum diambil*. Begitu staff klik Claim, pesannya ganti ke
    TicketClaimedView -- lihat callback tombol Claim di bawah."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label="Ambil Ticket", style=discord.ButtonStyle.primary, custom_id="noctra:ticket:claim")
    async def claim(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not await is_staff(interaction):
            await interaction.response.send_message(
                embed=embeds.error_embed("Cuma staff yang bisa ngambil ticket."), ephemeral=True
            )
            return
        db = interaction.client.db  # type: ignore[attr-defined]
        ticket = await tickets_q.get_ticket_by_channel(db, interaction.channel.id)
        if not ticket:
            await interaction.response.send_message(embed=embeds.error_embed("Ini bukan channel ticket."), ephemeral=True)
            return
        if ticket["claimed_by"]:
            await interaction.response.send_message(
                embed=embeds.error_embed(f"Ticket ini udah diambil sama <@{ticket['claimed_by']}>."),
                ephemeral=True,
            )
            return

        await tickets_q.set_ticket_claim(db, interaction.channel.id, interaction.user.id)
        new_embed = _with_claim_field(_source_embed(interaction), interaction.user.mention)
        await interaction.response.edit_message(embed=new_embed, view=TicketClaimedView())
        await interaction.followup.send(
            embed=embeds.success_embed(f"Ticket udah diambil sama {interaction.user.mention}."), ephemeral=True
        )

    @discord.ui.button(label="Tutup Ticket", style=discord.ButtonStyle.secondary, custom_id="noctra:ticket:close")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await _handle_ticket_close(interaction)


class TicketClaimedView(discord.ui.View):
    """State *udah diambil* -- muncul abis staff klik Claim Ticket. Tombol
    Claim ganti jadi Unclaim; tombol Close Ticket kerjanya sama aja."""

    def __init__(self) -> None:
        super().__init__(timeout=None)

    @discord.ui.button(label="Lepas Ticket", style=discord.ButtonStyle.secondary, custom_id="noctra:ticket:unclaim")
    async def unclaim(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        db = interaction.client.db  # type: ignore[attr-defined]
        ticket = await tickets_q.get_ticket_by_channel(db, interaction.channel.id)
        if not ticket:
            await interaction.response.send_message(embed=embeds.error_embed("Ini bukan channel ticket."), ephemeral=True)
            return

        is_claimant = ticket["claimed_by"] == interaction.user.id
        is_admin = isinstance(interaction.user, discord.Member) and interaction.user.guild_permissions.administrator
        if not (is_claimant or is_admin):
            await interaction.response.send_message(
                embed=embeds.error_embed(
                    "Cuma staff yang ngambil ticket ini (atau admin) yang bisa lepas ticket ini."
                ),
                ephemeral=True,
            )
            return

        await tickets_q.set_ticket_claim(db, interaction.channel.id, None)
        new_embed = _with_claim_field(_source_embed(interaction), None)
        await interaction.response.edit_message(embed=new_embed, view=TicketControlView())
        await interaction.followup.send(embed=embeds.success_embed("Ticket udah dilepas."), ephemeral=True)

    @discord.ui.button(label="Tutup Ticket", style=discord.ButtonStyle.secondary, custom_id="noctra:ticket:close_claimed")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await _handle_ticket_close(interaction)


# ============================================================================
# AKSI ORDER (persistent, dinamis -- diposting di channel order-log)
# ============================================================================

class OrderActionButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"noctra:order:(?P<action>mark_paid|mark_completed|cancel|refund):(?P<order_id>[0-9]+)",
):
    """Tombol kontrol staff yang order ID-nya ke-encode langsung di
    custom_id-nya. Beda sama persistent View biasa (satu custom_id tetap
    dipake bareng di semua pesan), ini bikin tiap order dapet tombol Mark
    Paid / Mark Completed / Cancel / Refund sendiri-sendiri yang jalan di
    channel order-log bareng, dan tetep jalan abis bot restart tanpa
    bookkeeping ekstra -- discord.py rekonstruksi tombolnya dari custom_id
    doang."""

    LABELS = {
        "mark_paid": "Tandain Lunas",
        "mark_completed": "Tandain Selesai",
        "cancel": "Batalin",
        "refund": "Refund",
    }
    STYLES = {
        "mark_paid": discord.ButtonStyle.success,
        "mark_completed": discord.ButtonStyle.primary,
        "cancel": discord.ButtonStyle.danger,
        "refund": discord.ButtonStyle.danger,
    }

    def __init__(self, action: str, order_id: int) -> None:
        super().__init__(
            discord.ui.Button(
                label=self.LABELS[action],
                style=self.STYLES[action],
                custom_id=f"noctra:order:{action}:{order_id}",
            )
        )
        self.action = action
        self.order_id = order_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):  # noqa: D102
        return cls(match["action"], int(match["order_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await is_staff(interaction):
            await interaction.response.send_message(embed=embeds.error_embed("Khusus staff."), ephemeral=True)
            return

        if self.action in ("mark_paid", "mark_completed"):
            await interaction.response.defer(ephemeral=True)
            func = order_actions.mark_paid if self.action == "mark_paid" else order_actions.mark_completed
            ok, message = await func(interaction.client, self.order_id)
            await interaction.followup.send(
                embed=embeds.success_embed(message) if ok else embeds.error_embed(message), ephemeral=True
            )
            return

        action, order_id = self.action, self.order_id

        async def on_reason(inter: discord.Interaction, reason: str) -> None:
            await inter.response.defer(ephemeral=True)
            if action == "cancel":
                ok, message = await order_actions.cancel_order(inter.client, order_id, reason or None)
            else:
                ok, message = await order_actions.refund_order(inter.client, order_id, reason or None)
            await inter.followup.send(
                embed=embeds.success_embed(message) if ok else embeds.error_embed(message), ephemeral=True
            )

        title = "Batalin Order" if action == "cancel" else "Refund Order"
        await interaction.response.send_modal(ReasonModal(title, on_reason))


class ReplyButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"noctra:order:reply:(?P<order_id>[0-9]+)",
):
    """Ngasih staff cara balesin DM customer sekali klik -- buka modal buat
    ngetik balesan langsung di channel order-log atau di samping pesan
    bukti bayar yang diterusin, gak perlu ngetik /order message tiap kali.
    Trik custom_id restart-safe sama kayak OrderActionButton."""

    def __init__(self, order_id: int) -> None:
        super().__init__(
            discord.ui.Button(
                label="Balas",
                style=discord.ButtonStyle.secondary,
                custom_id=f"noctra:order:reply:{order_id}",
            )
        )
        self.order_id = order_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):  # noqa: D102
        return cls(int(match["order_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        if not await is_staff(interaction):
            await interaction.response.send_message(embed=embeds.error_embed("Khusus staff."), ephemeral=True)
            return

        order_id = self.order_id

        async def on_message(inter: discord.Interaction, text: str) -> None:
            db = inter.client.db  # type: ignore[attr-defined]
            order = await orders_q.get_order(db, order_id)
            if not order:
                await inter.response.send_message(embed=embeds.error_embed("Order gak ketemu."), ephemeral=True)
                return
            embed = embeds.info_embed(f"Pesan soal Order #{order_id}", text)
            sent = await order_actions.send_message_to_customer(inter.client, order["user_id"], embed, order_id)
            await inter.response.send_message(
                embed=embeds.success_embed("Pesan udah dikirim.")
                if sent
                else embeds.error_embed("Gak bisa DM customer -- mungkin DM-nya lagi ditutup."),
                ephemeral=True,
            )

        await interaction.response.send_modal(MessageModal(f"Balas -- Order #{order_id}", on_message))


# ============================================================================
# PANEL SUPPORT TICKET (persistent)
# ============================================================================

class OpenTicketPanelView(discord.ui.View):
    def __init__(self, button_label: str = "Buka Ticket") -> None:
        super().__init__(timeout=None)
        self.open_ticket.label = button_label[:80]

    @discord.ui.button(label="Buka Ticket", style=discord.ButtonStyle.secondary, custom_id="noctra:ticket:open_support")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        channel = await ticket_actions.create_ticket_channel(
            interaction.client, interaction.guild, interaction.user, "support"
        )
        await channel.send(
            content=interaction.user.mention,
            embed=embeds.ticket_welcome_embed(),
            view=TicketControlView(),
        )
        await interaction.followup.send(
            embed=embeds.success_embed(f"Ticket kamu udah dibuat: {channel.mention}"), ephemeral=True
        )


# ============================================================================
# ALUR REVIEW (button-only -- gak perlu /review submit)
# ============================================================================

class RatingButton(discord.ui.Button):
    def __init__(self, order_id: int, rating_value: int) -> None:
        super().__init__(label=str(rating_value), style=discord.ButtonStyle.secondary)
        self.order_id = order_id
        self.rating_value = rating_value

    async def callback(self, interaction: discord.Interaction) -> None:
        rating = self.rating_value
        order_id = self.order_id
        anonymous = self.view.anonymous  # type: ignore[union-attr]

        async def on_text(inter: discord.Interaction, text: str) -> None:
            db = inter.client.db  # type: ignore[attr-defined]
            order = await orders_q.get_order(db, order_id)
            if not order or order["user_id"] != inter.user.id:
                await inter.response.send_message(
                    embed=embeds.error_embed("Prompt ini bukan buat kamu."), ephemeral=True
                )
                return
            if order["status"] != "completed" or order["payment_status"] != "paid":
                await inter.response.send_message(
                    embed=embeds.error_embed("Order ini udah gak bisa direview lagi."), ephemeral=True
                )
                return
            if await reviews_q.get_review_by_order(db, order_id):
                await inter.response.send_message(
                    embed=embeds.error_embed("Kamu udah pernah review order ini."), ephemeral=True
                )
                return

            review_id = await reviews_q.create_review(
                db, order_id, order["product_id"], inter.user.id, rating, text or None, anonymous
            )

            # Prompt "Gimana Belanjanya?" yang awal udah kelar tugasnya --
            # bersihin (dan pesan balesan staff yang nyasar) sebelum nanya
            # soal foto, biar itu juga gak numpuk basi.
            await order_actions.cleanup_dm_messages(inter.client, order_id)

            # Discord Modal cuma dukung field teks -- gak ada cara nerima
            # upload file lewat situ. Jadi daripada maksain field URL di
            # modal rating+teks, attachment foto jadi langkah lanjutan
            # sendiri yang pendek: minta customer kirim aja gambarnya kayak
            # pesan DM biasa.
            await reviews_q.set_awaiting_photo(db, review_id, True)
            prompt_embed = embeds.info_embed(
                "Mau Tambahin Foto? (Opsional)",
                "Punya screenshot buat nemenin review kamu? Kirim aja di sini "
                "kayak chat biasa -- gak perlu link. Atau klik Lewati buat "
                "selesai tanpa foto.",
            )
            await inter.response.send_message(
                embed=prompt_embed, view=PhotoPromptView(review_id), ephemeral=False
            )
            sent = await inter.original_response()
            await orders_q.add_dm_message(db, order_id, sent.channel.id, sent.id)

        await interaction.response.send_modal(ReviewTextModal(f"Kasih Rating {rating}/5 -- Tulis Review", on_text))


class SkipPhotoButton(discord.ui.Button):
    def __init__(self, review_id: int) -> None:
        super().__init__(label="Lewati", style=discord.ButtonStyle.secondary)
        self.review_id = review_id

    async def callback(self, interaction: discord.Interaction) -> None:
        db = interaction.client.db  # type: ignore[attr-defined]
        review = await reviews_q.get_review(db, self.review_id)
        if not review or review["user_id"] != interaction.user.id:
            await interaction.response.send_message(
                embed=embeds.error_embed("Prompt ini bukan buat kamu."), ephemeral=True
            )
            return
        await reviews_q.set_awaiting_photo(db, self.review_id, False)
        join_view = await build_join_server_view(db)
        await interaction.response.send_message(
            embed=embeds.success_embed("Santai -- review kamu udah masuk tanpa foto."),
            view=join_view,
            ephemeral=True,
        )
        await order_actions.cleanup_dm_messages(interaction.client, review["order_id"])


class PhotoPromptView(discord.ui.View):
    def __init__(self, review_id: int) -> None:
        super().__init__(timeout=600)
        self.review_id = review_id
        self.add_item(SkipPhotoButton(review_id))


class AnonymousToggleButton(discord.ui.Button):
    def __init__(self) -> None:
        super().__init__(label="Anonim: Nonaktif", style=discord.ButtonStyle.secondary, row=1)

    async def callback(self, interaction: discord.Interaction) -> None:
        view: RatingPromptView = self.view  # type: ignore[assignment]
        view.anonymous = not view.anonymous
        self.label = f"Anonim: {'Aktif' if view.anonymous else 'Nonaktif'}"
        await interaction.response.edit_message(view=view)


class RatingPromptView(discord.ui.View):
    def __init__(self, order_id: int) -> None:
        super().__init__(timeout=300)
        self.order_id = order_id
        self.anonymous = False
        for value in range(1, 6):
            self.add_item(RatingButton(order_id, value))
        self.add_item(AnonymousToggleButton())


class ReviewStartButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=r"noctra:review:start:(?P<order_id>[0-9]+)",
):
    """Tombol 'Kasih Review' -- di-DM ke customer otomatis begitu staff
    nandain order mereka selesai (lihat bot.utils.order_actions). Order ID
    ke-encode di custom_id-nya jadi ini tetep jalan abis bot restart tanpa
    bookkeeping ekstra, trik yang sama kayak OrderActionButton."""

    def __init__(self, order_id: int) -> None:
        super().__init__(
            discord.ui.Button(
                label="Kasih Review",
                style=discord.ButtonStyle.secondary,
                custom_id=f"noctra:review:start:{order_id}",
            )
        )
        self.order_id = order_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):  # noqa: D102
        return cls(int(match["order_id"]))

    async def callback(self, interaction: discord.Interaction) -> None:
        db = interaction.client.db  # type: ignore[attr-defined]
        order = await orders_q.get_order(db, self.order_id)
        if not order:
            await interaction.response.send_message(embed=embeds.error_embed("Order gak ketemu."), ephemeral=True)
            return
        if order["user_id"] != interaction.user.id:
            await interaction.response.send_message(
                embed=embeds.error_embed("Cuma customer yang mesen ini yang bisa kasih review."),
                ephemeral=True,
            )
            return
        if order["status"] != "completed" or order["payment_status"] != "paid":
            await interaction.response.send_message(
                embed=embeds.error_embed("Order ini belum bisa direview."), ephemeral=True
            )
            return
        if await reviews_q.get_review_by_order(db, self.order_id):
            await interaction.response.send_message(
                embed=embeds.error_embed("Kamu udah pernah review order ini. Pake `/review edit` buat ubah."),
                ephemeral=True,
            )
            return
        embed = embeds.info_embed(
            "Kasih Rating Belanjaan Kamu", "Pilih rating dari 1 sampe 5, terus tulis review (opsional)."
        )
        await interaction.response.send_message(embed=embed, view=RatingPromptView(self.order_id), ephemeral=True)


# ============================================================================
# DISAMBIGUASI BUKTI BAYAR (DM -- dipake kalau customer punya lebih dari
# satu order yang lagi nunggu bayar sekaligus, lihat bot.cogs.payment_proof)
# ============================================================================

class PendingOrderSelect(discord.ui.Select):
    def __init__(self, orders: list, content: str, attachment_urls: list[str]) -> None:
        self.orders_map = {str(o["id"]): o for o in orders}
        self.content = content
        self.attachment_urls = attachment_urls
        options = [
            discord.SelectOption(
                label=f"Order #{o['id']}",
                description=f"{o['total_price']:,.2f} {o['currency_label']}",
                value=str(o["id"]),
            )
            for o in orders[:MAX_SELECT_OPTIONS]
        ]
        super().__init__(placeholder="Pilih ini soal order yang mana...", options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        order = self.orders_map[self.values[0]]
        sent = await order_actions.forward_to_staff(
            interaction.client, order["id"], interaction.user, self.content, self.attachment_urls
        )
        if sent:
            await interaction.response.edit_message(
                embed=embeds.success_embed(f"Udah dikirim ke staff buat Order #{order['id']}."), view=None
            )
        else:
            await interaction.response.edit_message(
                embed=embeds.error_embed(
                    "Staff belum atur channel order-log, jadi ini gak bisa diterusin "
                    "otomatis. Tunggu staff cek order kamu manual ya."
                ),
                view=None,
            )


class PendingOrderSelectView(discord.ui.View):
    def __init__(self, orders: list, content: str, attachment_urls: list[str]) -> None:
        super().__init__(timeout=300)
        self.add_item(PendingOrderSelect(orders, content, attachment_urls))
