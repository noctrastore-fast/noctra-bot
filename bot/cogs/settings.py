"""Command admin: /settings"""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from bot.database.queries import settings as settings_q
from bot.ui import embeds
from bot.ui.views import ShopPanelView
from bot.utils.helpers import RuntimeSettings
from bot.utils.leaderboard import refresh_leaderboard
from bot.utils.permissions import staff_only


class SettingsCog(commands.Cog):
    """Atur staff role, kategori/channel ticket, mata uang, dan auto-archive."""

    settings_group = app_commands.Group(
        name="settings", description="Atur NOCTRA.", guild_only=True
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @settings_group.command(name="shop_panel", description="Posting panel tombol Browse Store di channel ini.")
    @app_commands.describe(
        title="Judul panel",
        description="Isi teks panel",
        image_url="Gambar banner full-width di bawah teks (PNG/JPG/WebP)",
        thumbnail_url="Logo/thumbnail kecil di kanan atas (PNG/JPG/WebP)",
        button_label="Teks yang muncul di tombol",
    )
    @staff_only()
    async def shop_panel(
        self,
        interaction: discord.Interaction,
        title: str = "NOCTRA STORE",
        description: str = "Klik di bawah buat jelajahin katalog dan pesen -- gak perlu command.",
        image_url: str | None = None,
        thumbnail_url: str | None = None,
        button_label: str = "Jelajahi Toko",
    ) -> None:
        view = ShopPanelView(
            title=title, description=description, image_url=image_url,
            thumbnail_url=thumbnail_url, button_label=button_label,
        )
        await interaction.channel.send(view=view)
        await interaction.response.send_message(embed=embeds.success_embed("Panel toko udah diposting."), ephemeral=True)

    @settings_group.command(
        name="order_log_channel",
        description="Atur channel tempat order baru diposting sama kontrol staff (Mark Paid/Completed/Cancel/Refund).",
    )
    @app_commands.describe(channel="Channel buat notifikasi order dan kontrol staff")
    @staff_only()
    async def order_log_channel(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        await settings_q.set_setting(self.bot.db, "order_log_channel_id", str(channel.id))
        await interaction.response.send_message(
            embed=embeds.success_embed(f"Channel order-log diatur ke {channel.mention}."), ephemeral=True
        )

    @settings_group.command(
        name="reviews_channel",
        description="Atur channel publik tempat review customer yang di-approve diposting (buat reputasi toko).",
    )
    @app_commands.describe(channel="Channel publik buat showcase review")
    @staff_only()
    async def reviews_channel(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        await settings_q.set_setting(self.bot.db, "reviews_channel_id", str(channel.id))
        await interaction.response.send_message(
            embed=embeds.success_embed(f"Channel review diatur ke {channel.mention}."), ephemeral=True
        )

    @settings_group.command(
        name="purchase_feed_channel",
        description="Atur channel tempat pengumuman 'Si X baru aja beli Y' diposting.",
    )
    @app_commands.describe(channel="Channel publik buat pengumuman pembelian")
    @staff_only()
    async def purchase_feed_channel(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        await settings_q.set_setting(self.bot.db, "purchase_feed_channel_id", str(channel.id))
        await interaction.response.send_message(
            embed=embeds.success_embed(f"Pengumuman pembelian bakal diposting di {channel.mention}."),
            ephemeral=True,
        )

    @settings_group.command(
        name="ad_channel",
        description="Atur channel default buat /iklan kalau parameter channel-nya gak diisi.",
    )
    @app_commands.describe(channel="Channel default buat posting iklan")
    @staff_only()
    async def ad_channel(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        await settings_q.set_setting(self.bot.db, "ad_channel_id", str(channel.id))
        await interaction.response.send_message(
            embed=embeds.success_embed(
                f"Channel default iklan diatur ke {channel.mention}. "
                "Pake `/iklan` kapan aja -- kalau parameter `channel`-nya gak diisi, otomatis kesitu."
            ),
            ephemeral=True,
        )

    @settings_group.command(
        name="main_server_invite",
        description="Atur link invite server utama -- muncul jadi tombol 'Gabung Server' abis customer selesai review.",
    )
    @app_commands.describe(invite_url="Link invite Discord server utama kamu, contoh https://discord.gg/xxxxx")
    @staff_only()
    async def main_server_invite(self, interaction: discord.Interaction, invite_url: str) -> None:
        await settings_q.set_setting(self.bot.db, "main_server_invite_url", invite_url)
        await interaction.response.send_message(
            embed=embeds.success_embed("Link invite server utama udah diatur."), ephemeral=True
        )

    @settings_group.command(
        name="review_banner_image",
        description="Atur gambar banner default buat kartu review yang customer-nya gak nyertain foto.",
    )
    @app_commands.describe(image_url="URL gambar banner default (PNG/JPG/WebP)")
    @staff_only()
    async def review_banner_image(self, interaction: discord.Interaction, image_url: str) -> None:
        await settings_q.set_setting(self.bot.db, "review_banner_url", image_url)
        await interaction.response.send_message(
            embed=embeds.success_embed("Banner default buat review udah diatur.").set_thumbnail(url=image_url),
            ephemeral=True,
        )

    @settings_group.command(
        name="leaderboard_channel",
        description="Atur channel buat gambar leaderboard Top Spenders.",
    )
    @app_commands.describe(channel="Channel khusus buat gambar leaderboard")
    @staff_only()
    async def leaderboard_channel(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        await settings_q.set_setting(self.bot.db, "leaderboard_channel_id", str(channel.id))
        await settings_q.set_setting(self.bot.db, "leaderboard_message_id", "")
        await interaction.response.send_message(
            embed=embeds.success_embed(
                f"Channel leaderboard diatur ke {channel.mention}. "
                "Pake `/settings leaderboard_refresh` buat posting gambar pertamanya."
            ),
            ephemeral=True,
        )

    @settings_group.command(
        name="leaderboard_refresh",
        description="Posting atau refresh gambar leaderboard manual sekarang juga.",
    )
    @staff_only()
    async def leaderboard_refresh(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        ok = await refresh_leaderboard(self.bot)
        if ok:
            await interaction.followup.send(embed=embeds.success_embed("Leaderboard udah di-refresh."), ephemeral=True)
        else:
            await interaction.followup.send(
                embed=embeds.error_embed(
                    "Gak bisa refresh leaderboard. Pastiin "
                    "`/settings leaderboard_channel` udah diatur dan ada minimal satu order yang selesai."
                ),
                ephemeral=True,
            )

    @settings_group.command(
        name="leaderboard_exclude",
        description="Sembunyiin spend user dari leaderboard Top Spenders (misal akun tester).",
    )
    @app_commands.describe(user="User yang mau disembunyiin dari leaderboard")
    @staff_only()
    async def leaderboard_exclude(self, interaction: discord.Interaction, user: discord.User) -> None:
        runtime = RuntimeSettings(self.bot.db)
        excluded = await runtime.leaderboard_excluded_user_ids()
        if user.id in excluded:
            await interaction.response.send_message(
                embed=embeds.error_embed(f"{user.mention} udah disembunyiin dari leaderboard."),
                ephemeral=True,
            )
            return
        excluded.append(user.id)
        await settings_q.set_setting(
            self.bot.db, "leaderboard_excluded_users", ",".join(str(uid) for uid in excluded)
        )
        await interaction.response.defer(ephemeral=True)
        await refresh_leaderboard(self.bot)
        await interaction.followup.send(
            embed=embeds.success_embed(
                f"{user.mention} sekarang disembunyiin dari leaderboard. Order lama mereka gak diapa-apain -- "
                "cuma gak kehitung di sini aja. Leaderboard udah di-refresh."
            ),
            ephemeral=True,
        )

    @settings_group.command(
        name="leaderboard_include",
        description="Balikin lagi user yang sebelumnya disembunyiin dari leaderboard.",
    )
    @app_commands.describe(user="User yang mau dimasukin lagi ke leaderboard")
    @staff_only()
    async def leaderboard_include(self, interaction: discord.Interaction, user: discord.User) -> None:
        runtime = RuntimeSettings(self.bot.db)
        excluded = await runtime.leaderboard_excluded_user_ids()
        if user.id not in excluded:
            await interaction.response.send_message(
                embed=embeds.error_embed(f"{user.mention} lagi gak disembunyiin kok."), ephemeral=True
            )
            return
        excluded.remove(user.id)
        await settings_q.set_setting(
            self.bot.db, "leaderboard_excluded_users", ",".join(str(uid) for uid in excluded)
        )
        await interaction.response.defer(ephemeral=True)
        await refresh_leaderboard(self.bot)
        await interaction.followup.send(
            embed=embeds.success_embed(f"{user.mention} udah gak disembunyiin lagi. Leaderboard udah di-refresh."),
            ephemeral=True,
        )

    @settings_group.command(
        name="leaderboard_excluded_list",
        description="Liat daftar user yang lagi disembunyiin dari leaderboard.",
    )
    @staff_only()
    async def leaderboard_excluded_list(self, interaction: discord.Interaction) -> None:
        runtime = RuntimeSettings(self.bot.db)
        excluded = await runtime.leaderboard_excluded_user_ids()
        if not excluded:
            await interaction.response.send_message(
                embed=embeds.info_embed("Disembunyiin dari Leaderboard", "Belum ada user yang disembunyiin."),
                ephemeral=True,
            )
            return
        lines = "\n".join(f"<@{uid}> (`{uid}`)" for uid in excluded)
        await interaction.response.send_message(
            embed=embeds.info_embed("Disembunyiin dari Leaderboard", lines), ephemeral=True
        )

    @settings_group.command(name="view", description="Liat pengaturan yang lagi aktif.")
    @staff_only()
    async def view(self, interaction: discord.Interaction) -> None:
        runtime = RuntimeSettings(self.bot.db)
        excluded_count = len(await runtime.leaderboard_excluded_user_ids())
        values = {
            "staff_role_id": await runtime.staff_role_id(),
            "order_log_channel_id": await runtime.order_log_channel_id(),
            "reviews_channel_id": await runtime.reviews_channel_id(),
            "purchase_feed_channel_id": await runtime.purchase_feed_channel_id(),
            "ad_channel_id": await runtime.ad_channel_id(),
            "main_server_invite_url": await runtime.main_server_invite_url(),
            "review_banner_url": await runtime.review_banner_url(),
            "leaderboard_channel_id": await runtime.leaderboard_channel_id(),
            "leaderboard_excluded_users": excluded_count or "Gak ada",
            "ticket_category_id": await runtime.ticket_category_id(),
            "ticket_archive_category_id": await runtime.ticket_archive_category_id(),
            "ticket_log_channel_id": await runtime.ticket_log_channel_id(),
            "ticket_auto_archive_hours": await runtime.ticket_auto_archive_hours(),
            "default_currency": await runtime.default_currency(),
        }
        await interaction.response.send_message(embed=embeds.settings_embed(values), ephemeral=True)

    @settings_group.command(name="staff_role", description="Atur role staff buat command admin dan ticket.")
    @app_commands.describe(role="Role yang bakal dianggep staff")
    @staff_only()
    async def staff_role(self, interaction: discord.Interaction, role: discord.Role) -> None:
        await settings_q.set_setting(self.bot.db, "staff_role_id", str(role.id))
        await interaction.response.send_message(
            embed=embeds.success_embed(f"Role staff diatur ke {role.mention}."), ephemeral=True
        )

    @settings_group.command(name="ticket_category", description="Atur kategori tempat channel ticket baru dibuat.")
    @app_commands.describe(category="Category channel buat ticket baru")
    @staff_only()
    async def ticket_category(self, interaction: discord.Interaction, category: discord.CategoryChannel) -> None:
        await settings_q.set_setting(self.bot.db, "ticket_category_id", str(category.id))
        await interaction.response.send_message(
            embed=embeds.success_embed(f"Kategori ticket diatur ke **{category.name}**."), ephemeral=True
        )

    @settings_group.command(name="archive_category", description="Atur kategori tempat ticket yang di-auto-archive dipindahin.")
    @app_commands.describe(category="Category channel buat ticket yang diarsipin")
    @staff_only()
    async def archive_category(self, interaction: discord.Interaction, category: discord.CategoryChannel) -> None:
        await settings_q.set_setting(self.bot.db, "ticket_archive_category_id", str(category.id))
        await interaction.response.send_message(
            embed=embeds.success_embed(f"Kategori archive diatur ke **{category.name}**."), ephemeral=True
        )

    @settings_group.command(name="log_channel", description="Atur channel tempat transcript ticket diposting.")
    @app_commands.describe(channel="Channel buat transcript dan log ticket")
    @staff_only()
    async def log_channel(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        await settings_q.set_setting(self.bot.db, "ticket_log_channel_id", str(channel.id))
        await interaction.response.send_message(
            embed=embeds.success_embed(f"Log channel diatur ke {channel.mention}."), ephemeral=True
        )

    @settings_group.command(name="auto_archive_hours", description="Jam inaktif sebelum ticket di-auto-archive.")
    @app_commands.describe(hours="Jumlah jam")
    @staff_only()
    async def auto_archive_hours(
        self, interaction: discord.Interaction, hours: app_commands.Range[int, 1, 720]
    ) -> None:
        await settings_q.set_setting(self.bot.db, "ticket_auto_archive_hours", str(hours))
        await interaction.response.send_message(
            embed=embeds.success_embed(f"Ticket bakal auto-archive abis {hours} jam gak ada aktivitas."),
            ephemeral=True,
        )

    @settings_group.command(name="currency", description="Atur label mata uang default buat produk baru.")
    @app_commands.describe(currency_label="contoh: USD, IDR, Robux")
    @staff_only()
    async def currency(self, interaction: discord.Interaction, currency_label: str) -> None:
        await settings_q.set_setting(self.bot.db, "default_currency", currency_label)
        await interaction.response.send_message(
            embed=embeds.success_embed(f"Mata uang default diatur ke **{currency_label}**."), ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SettingsCog(bot))
