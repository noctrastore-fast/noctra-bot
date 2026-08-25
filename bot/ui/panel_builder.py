"""
View builder buat command /panel -- edit pesan Components V2 custom di
channel yang sama, live lewat panel kontrol ephemeral.
"""

from __future__ import annotations

import discord

from bot.ui import embeds
from bot.ui.draft_builder_base import BaseDraftBuilderView
from bot.utils.message_draft import render_draft_layout


class PanelBuilderView(BaseDraftBuilderView):
    """Semua tombol edit draft (Title/Description/dst) diwarisin dari
    BaseDraftBuilderView -- di sini nambahin tombol Update, plus override
    `_after_edit()` biar SETIAP perubahan langsung kepush live ke pesan
    target (`target_message_id`) di channel yang sama tempat /panel
    dijalanin -- gak perlu nunggu klik Update dulu buat liat hasilnya."""

    def __init__(self, target_channel_id: int, target_message_id: int) -> None:
        super().__init__(timeout=1800)
        self.target_channel_id = target_channel_id
        self.target_message_id = target_message_id

    async def _after_edit(self, interaction: discord.Interaction) -> None:
        # Response PERTAMA interaction ini WAJIB edit_message -- ini yang
        # ngerefresh pesan panel sendiri (opsi Select dsb).
        await interaction.response.edit_message(view=self)

        # Push live ke pesan TARGET asli -- ini pesan biasa (bukan
        # ephemeral), jadi aman di-edit lewat channel.fetch_message() +
        # .edit() biasa pake kredensial bot, gak perlu lewat mekanisme
        # response interaction sama sekali.
        channel = interaction.client.get_channel(self.target_channel_id)  # type: ignore[attr-defined]
        if not isinstance(channel, discord.TextChannel):
            return
        try:
            target_message = await channel.fetch_message(self.target_message_id)
            await target_message.edit(view=render_draft_layout(self.draft))
        except (discord.NotFound, discord.HTTPException):
            pass  # pesan target kehapus atau lagi ada masalah -- gak fatal, coba lagi pas edit berikutnya

    @discord.ui.button(label="Update", style=discord.ButtonStyle.success, row=4)
    async def update_button(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        # Isinya udah live ke-push tiap ada perubahan (lihat _after_edit di
        # atas) -- tombol ini tetep ada buat konfirmasi eksplisit "beres"
        # dan sekalian re-sync manual kalau-kalau ada push yang gagal
        # sebelumnya (misal pesan target sempet gak ketemu).
        await interaction.response.defer(ephemeral=True)
        channel = interaction.client.get_channel(self.target_channel_id)  # type: ignore[attr-defined]
        if not isinstance(channel, discord.TextChannel):
            await interaction.followup.send(embed=embeds.error_embed("Channel target gak ketemu."), ephemeral=True)
            return
        try:
            target_message = await channel.fetch_message(self.target_message_id)
        except discord.NotFound:
            await interaction.followup.send(
                embed=embeds.error_embed("Pesan target udah kehapus -- jalanin `/panel` lagi buat mulai baru."),
                ephemeral=True,
            )
            return

        try:
            await target_message.edit(view=render_draft_layout(self.draft))
        except discord.HTTPException as exc:
            await interaction.followup.send(embed=embeds.error_embed(f"Gagal update pesan: {exc}"), ephemeral=True)
            return

        await interaction.followup.send(
            embed=embeds.success_embed(f"Berhasil update pesan di {channel.mention}."), ephemeral=True
        )
