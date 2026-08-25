"""Command admin & user: /ticket"""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from bot.database.queries import tickets as tickets_q
from bot.ui import embeds
from bot.ui.modals import ReasonModal
from bot.ui.views import OpenTicketPanelView, TicketControlView
from bot.utils import ticket_actions
from bot.utils.permissions import is_staff, staff_only


class TicketCog(commands.Cog):
    """Setup panel ticket plus command open/close/reopen."""

    ticket_group = app_commands.Group(name="ticket", description="Kelola ticket support.", guild_only=True)

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.guild:
            return
        ticket = await tickets_q.get_ticket_by_channel(self.bot.db, message.channel.id)
        if ticket and ticket["status"] == "open":
            await tickets_q.touch_activity(self.bot.db, message.channel.id)

    @ticket_group.command(name="panel", description="Posting panel Open Ticket di channel ini.")
    @app_commands.describe(
        title="Judul panel",
        description="Isi teks panel",
        image_url="Gambar banner full-width di bawah teks (PNG/JPG/WebP)",
        thumbnail_url="Logo/thumbnail kecil di kanan atas (PNG/JPG/WebP)",
        button_label="Teks yang muncul di tombol",
    )
    @staff_only()
    async def panel(
        self,
        interaction: discord.Interaction,
        title: str = "NOCTRA -- Support",
        description: str = (
            "Butuh bantuan soal order atau ada pertanyaan buat staff? "
            "Klik di bawah buat buka ticket pribadi."
        ),
        image_url: str | None = None,
        thumbnail_url: str | None = None,
        button_label: str = "Buka Ticket",
    ) -> None:
        embed = embeds.base_embed(title, description, image_url=image_url, thumbnail_url=thumbnail_url)
        await interaction.channel.send(embed=embed, view=OpenTicketPanelView(button_label=button_label))
        await interaction.response.send_message(embed=embeds.success_embed("Panel ticket udah diposting."), ephemeral=True)

    @ticket_group.command(name="open", description="Buka ticket support baru.")
    @app_commands.guild_only()
    async def open_ticket(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        channel = await ticket_actions.create_ticket_channel(
            self.bot, interaction.guild, interaction.user, "support"
        )
        await channel.send(
            content=interaction.user.mention,
            embed=embeds.ticket_welcome_embed(),
            view=TicketControlView(),
        )
        await interaction.followup.send(
            embed=embeds.success_embed(f"Ticket kamu udah dibuat: {channel.mention}"), ephemeral=True
        )

    @ticket_group.command(name="close", description="Tutup ticket yang lagi dibuka ini.")
    @app_commands.describe(reason="Alasan penutupan")
    async def close(self, interaction: discord.Interaction, reason: str | None = None) -> None:
        ticket = await tickets_q.get_ticket_by_channel(self.bot.db, interaction.channel.id)
        if not ticket:
            await interaction.response.send_message(embed=embeds.error_embed("Ini bukan channel ticket."), ephemeral=True)
            return
        if not (await is_staff(interaction) or interaction.user.id == ticket["user_id"]):
            await interaction.response.send_message(
                embed=embeds.error_embed("Cuma staff atau pemilik ticket yang bisa nutup ticket ini."), ephemeral=True
            )
            return

        if reason is not None:
            await interaction.response.defer(ephemeral=True)
            await ticket_actions.close_ticket(self.bot, interaction.channel, str(interaction.user), reason)
            await interaction.followup.send(embed=embeds.success_embed("Ticket udah ditutup."), ephemeral=True)
            return

        async def on_reason(inter: discord.Interaction, typed_reason: str) -> None:
            await inter.response.defer(ephemeral=True)
            await ticket_actions.close_ticket(self.bot, inter.channel, str(inter.user), typed_reason or None)
            await inter.followup.send(embed=embeds.success_embed("Ticket udah ditutup."), ephemeral=True)

        await interaction.response.send_modal(ReasonModal("Tutup Ticket", on_reason))

    @ticket_group.command(name="reopen", description="Buka lagi ticket yang lagi dibuka ini.")
    @staff_only()
    async def reopen(self, interaction: discord.Interaction) -> None:
        ticket = await tickets_q.get_ticket_by_channel(self.bot.db, interaction.channel.id)
        if not ticket:
            await interaction.response.send_message(embed=embeds.error_embed("Ini bukan channel ticket."), ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        await ticket_actions.reopen_ticket(self.bot, interaction.channel, str(interaction.user))
        await interaction.followup.send(embed=embeds.success_embed("Ticket udah dibuka lagi."), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TicketCog(bot))
