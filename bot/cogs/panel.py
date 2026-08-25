"""Command admin: /panel -- panel builder buat bikin/edit pesan custom Components V2."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from bot.ui import embeds
from bot.ui.panel_builder import PanelBuilderView
from bot.utils.message_draft import MessageDraft, render_draft_layout
from bot.utils.permissions import staff_only


class PanelCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="panel", description="Buka panel builder buat bikin pesan custom di channel ini.")
    @app_commands.guild_only()
    @staff_only()
    async def panel(self, interaction: discord.Interaction) -> None:
        layout = render_draft_layout(MessageDraft())
        target_message = await interaction.channel.send(view=layout)

        panel_view = PanelBuilderView(target_channel_id=interaction.channel.id, target_message_id=target_message.id)
        await interaction.response.send_message(
            embed=embeds.info_embed(
                "Panel Builder",
                f"Lagi bangun pesan [ini]({target_message.jump_url}). Pake tombol di bawah "
                "buat ngedit, terus klik **Update** abis selesai biar keapply ke pesannya.",
            ),
            view=panel_view,
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(PanelCog(bot))
