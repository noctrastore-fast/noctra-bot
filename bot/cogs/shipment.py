"""
Command staff: /shipment.

Bukti pengiriman barang -- staff post MANUAL ke channel yang udah diatur,
foto langsung dilampirin di command (discord.Attachment, staff upload
sendiri, BEDA sama payment_proof yang nunggu customer kirim lewat DM).
Card-nya Components V2, pola SAMA PERSIS kayak testi_proof_container
(lihat bot.ui.components.shipment_proof_container) -- tiap field (judul,
tanggal pengiriman, customer, status pengiriman) punya emoji sendiri yang
staff atur lewat /shipment emoji. Emoji itu boleh dari SERVER LAIN
sekalipun (asal bot ini juga ada di server itu) -- disimpen apa adanya
sebagai kode emoji mentah, gak divalidasi harus emoji milik server ini.

Settings per-server (guild_scoped_key(), pola sama kayak /welcome & /boost).
Ini command staff-only murni -- gak ada tombol/interaksi publik apapun,
sekali diposting ya udah final (dicatat ke tabel shipment_proofs buat
riwayat lewat /shipment log).
"""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from bot.core.theme import COLOR_ACCENT, COLOR_SUCCESS
from bot.database.queries import settings as settings_q
from bot.database.queries import shipment as shipment_q
from bot.ui import components, embeds
from bot.utils.helpers import RuntimeSettings, guild_scoped_key
from bot.utils.permissions import staff_only

DEFAULT_EMOJI_TITLE = "\U0001F4E6"     # 📦
DEFAULT_EMOJI_DATE = "\U0001F4C5"      # 📅
DEFAULT_EMOJI_CUSTOMER = "\U0001F464"  # 👤
DEFAULT_EMOJI_STATUS = "\U0001F69A"    # 🚚

COLOR_CANCELLED = 0xE74C3C

# (value, label, warna aksen kartu) -- warnanya beda-beda sesuai status
# biar staff bisa liat sekilas dari warna doang, gak perlu baca teksnya.
STATUS_CHOICES = [
    ("processing", "Sedang Diproses", COLOR_ACCENT),
    ("shipped", "Sedang Dikirim", COLOR_ACCENT),
    ("delivered", "Sudah Sampai", COLOR_SUCCESS),
    ("cancelled", "Dibatalkan", COLOR_CANCELLED),
]
STATUS_LABELS = {key: label for key, label, _ in STATUS_CHOICES}
STATUS_COLORS = {key: color for key, _, color in STATUS_CHOICES}


class ShipmentEmojiModal(discord.ui.Modal, title="Atur Emoji Bukti Pengiriman"):
    """4 field, satu per bagian kartu -- nilai yang lagi aktif di-prefill
    biar staff gak perlu ngetik ulang dari nol tiap mau ganti satu doang."""

    def __init__(self, current: dict[str, str | None], on_submit_callback) -> None:
        super().__init__(timeout=600)
        self._on_submit_callback = on_submit_callback

        self.title_emoji_input = discord.ui.TextInput(
            label="Emoji Judul",
            style=discord.TextStyle.short,
            required=False,
            max_length=100,
            placeholder=DEFAULT_EMOJI_TITLE,
            default=current.get("title") or "",
        )
        self.date_emoji_input = discord.ui.TextInput(
            label="Emoji Tanggal Pengiriman",
            style=discord.TextStyle.short,
            required=False,
            max_length=100,
            placeholder=DEFAULT_EMOJI_DATE,
            default=current.get("date") or "",
        )
        self.customer_emoji_input = discord.ui.TextInput(
            label="Emoji Customer",
            style=discord.TextStyle.short,
            required=False,
            max_length=100,
            placeholder=DEFAULT_EMOJI_CUSTOMER,
            default=current.get("customer") or "",
        )
        self.status_emoji_input = discord.ui.TextInput(
            label="Emoji Status Pengiriman",
            style=discord.TextStyle.short,
            required=False,
            max_length=100,
            placeholder=DEFAULT_EMOJI_STATUS,
            default=current.get("status") or "",
        )
        for item in (
            self.title_emoji_input, self.date_emoji_input,
            self.customer_emoji_input, self.status_emoji_input,
        ):
            self.add_item(item)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        values = {
            "title": self.title_emoji_input.value.strip(),
            "date": self.date_emoji_input.value.strip(),
            "customer": self.customer_emoji_input.value.strip(),
            "status": self.status_emoji_input.value.strip(),
        }
        await self._on_submit_callback(interaction, values)


class ShipmentCog(commands.Cog):
    """Bukti pengiriman barang -- staff-only."""

    shipment_group = app_commands.Group(
        name="shipment", description="Atur & kirim bukti pengiriman barang.", guild_only=True
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _save_emoji(self, interaction: discord.Interaction, values: dict[str, str]) -> None:
        db = self.bot.db
        guild_id = interaction.guild_id
        # String kosong SENGAJA disimpen apa adanya -- itu yang bikin staff
        # bisa "reset ke default" cukup dengan ngosongin field-nya di modal.
        await settings_q.set_setting(db, guild_scoped_key("shipment_emoji_title", guild_id), values["title"])
        await settings_q.set_setting(db, guild_scoped_key("shipment_emoji_date", guild_id), values["date"])
        await settings_q.set_setting(db, guild_scoped_key("shipment_emoji_customer", guild_id), values["customer"])
        await settings_q.set_setting(db, guild_scoped_key("shipment_emoji_status", guild_id), values["status"])
        await interaction.response.send_message(
            embed=embeds.success_embed("Emoji bukti pengiriman berhasil disimpen."), ephemeral=True
        )

    @shipment_group.command(name="emoji", description="Atur emoji tiap field di kartu bukti pengiriman.")
    @staff_only()
    async def emoji(self, interaction: discord.Interaction) -> None:
        runtime = RuntimeSettings(self.bot.db)
        guild_id = interaction.guild_id
        current = {
            "title": await runtime.shipment_emoji_title(guild_id),
            "date": await runtime.shipment_emoji_date(guild_id),
            "customer": await runtime.shipment_emoji_customer(guild_id),
            "status": await runtime.shipment_emoji_status(guild_id),
        }
        await interaction.response.send_modal(ShipmentEmojiModal(current, self._save_emoji))

    @shipment_group.command(name="channel", description="Atur channel tempat bukti pengiriman diposting.")
    @app_commands.describe(channel="Channel buat posting bukti pengiriman")
    @staff_only()
    async def channel(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        await settings_q.set_setting(
            self.bot.db, guild_scoped_key("shipment_channel_id", interaction.guild_id), str(channel.id)
        )
        await interaction.response.send_message(
            embed=embeds.success_embed(f"Channel bukti pengiriman diatur ke {channel.mention}."),
            ephemeral=True,
        )

    @shipment_group.command(name="kirim", description="Posting bukti pengiriman barang ke channel yang diatur.")
    @app_commands.describe(
        customer="Customer yang barangnya dikirim",
        foto="Foto bukti pengiriman (wajib, harus gambar)",
        status="Status pengiriman saat ini",
        tanggal="Tanggal pengiriman (opsional, default hari ini) -- format bebas, misal '20 September 2026'",
    )
    @app_commands.choices(
        status=[app_commands.Choice(name=label, value=key) for key, label, _ in STATUS_CHOICES]
    )
    @staff_only()
    async def kirim(
        self,
        interaction: discord.Interaction,
        customer: discord.Member,
        foto: discord.Attachment,
        status: app_commands.Choice[str],
        tanggal: str | None = None,
    ) -> None:
        if not foto.content_type or not foto.content_type.startswith("image/"):
            await interaction.response.send_message(
                embed=embeds.error_embed("File yang dilampirin harus berupa gambar (foto bukti pengiriman)."),
                ephemeral=True,
            )
            return

        runtime = RuntimeSettings(self.bot.db)
        guild_id = interaction.guild_id
        channel_id = await runtime.shipment_channel_id(guild_id)
        if not channel_id:
            await interaction.response.send_message(
                embed=embeds.error_embed("Channel bukti pengiriman belum diatur. Pake `/shipment channel` dulu."),
                ephemeral=True,
            )
            return
        channel = self.bot.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message(
                embed=embeds.error_embed("Channel bukti pengiriman gak ketemu -- mungkin udah kehapus."),
                ephemeral=True,
            )
            return

        emoji_title = await runtime.shipment_emoji_title(guild_id) or DEFAULT_EMOJI_TITLE
        emoji_date = await runtime.shipment_emoji_date(guild_id) or DEFAULT_EMOJI_DATE
        emoji_customer = await runtime.shipment_emoji_customer(guild_id) or DEFAULT_EMOJI_CUSTOMER
        emoji_status = await runtime.shipment_emoji_status(guild_id) or DEFAULT_EMOJI_STATUS

        shipped_date = (tanggal or "").strip() or discord.utils.utcnow().strftime("%d %B %Y")
        status_label = STATUS_LABELS[status.value]
        color = STATUS_COLORS[status.value]

        container = components.shipment_proof_container(
            customer_display=customer.mention,
            shipped_date=shipped_date,
            status_label=status_label,
            photo_url=foto.url,
            emoji_title=emoji_title,
            emoji_date=emoji_date,
            emoji_customer=emoji_customer,
            emoji_status=emoji_status,
            color=color,
        )
        view = discord.ui.LayoutView(timeout=None)
        view.add_item(container)

        try:
            message = await channel.send(view=view)
        except discord.HTTPException:
            await interaction.response.send_message(
                embed=embeds.error_embed("Gagal kirim bukti pengiriman -- cek izin NOCTRA buat kirim pesan di sana."),
                ephemeral=True,
            )
            return

        proof_id = await shipment_q.create_proof(
            self.bot.db,
            guild_id=guild_id,
            channel_id=channel.id,
            staff_user_id=interaction.user.id,
            customer_user_id=customer.id,
            shipped_date=shipped_date,
            status=status_label,
            photo_url=foto.url,
        )
        await shipment_q.set_message_id(self.bot.db, proof_id, message.id)

        await interaction.response.send_message(
            embed=embeds.success_embed(f"Bukti pengiriman #{proof_id} berhasil diposting ke {channel.mention}."),
            ephemeral=True,
        )

    @shipment_group.command(name="log", description="Liat riwayat bukti pengiriman terakhir di server ini.")
    @staff_only()
    async def log(self, interaction: discord.Interaction) -> None:
        recent = await shipment_q.list_recent(self.bot.db, interaction.guild_id)
        if not recent:
            await interaction.response.send_message(
                embed=embeds.info_embed("Riwayat Bukti Pengiriman", "Belum ada bukti pengiriman yang diposting."),
                ephemeral=True,
            )
            return
        lines = [
            f"**#{row['id']}** -- <@{row['customer_user_id']}> {chr(0x2022)} {row['status']} "
            f"{chr(0x2022)} {row['shipped_date']}"
            for row in recent
        ]
        await interaction.response.send_message(
            embed=embeds.info_embed("Riwayat Bukti Pengiriman (10 Terakhir)", "\n".join(lines)),
            ephemeral=True,
        )

    @shipment_group.command(name="view", description="Liat pengaturan bukti pengiriman yang lagi aktif.")
    @staff_only()
    async def view_settings(self, interaction: discord.Interaction) -> None:
        runtime = RuntimeSettings(self.bot.db)
        guild_id = interaction.guild_id
        channel_id = await runtime.shipment_channel_id(guild_id)
        lines = [
            f"▸ **Channel:** {f'<#{channel_id}>' if channel_id else 'Belum diatur'}",
            f"▸ **Emoji Judul:** {await runtime.shipment_emoji_title(guild_id) or DEFAULT_EMOJI_TITLE}",
            f"▸ **Emoji Tanggal:** {await runtime.shipment_emoji_date(guild_id) or DEFAULT_EMOJI_DATE}",
            f"▸ **Emoji Customer:** {await runtime.shipment_emoji_customer(guild_id) or DEFAULT_EMOJI_CUSTOMER}",
            f"▸ **Emoji Status:** {await runtime.shipment_emoji_status(guild_id) or DEFAULT_EMOJI_STATUS}",
        ]
        await interaction.response.send_message(
            embed=embeds.info_embed("Pengaturan Bukti Pengiriman", "\n".join(lines)), ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ShipmentCog(bot))
