"""
Cek izin staff.

"Staff" artinya: punya permission Administrator di Discord, ATAU pegang
role yang diatur lewat /settings (fallback ke STAFF_ROLE_ID di .env).
"""

from __future__ import annotations

import discord
from discord import app_commands

from bot.utils.helpers import RuntimeSettings


async def is_staff(interaction: discord.Interaction) -> bool:
    if not isinstance(interaction.user, discord.Member):
        return False
    if interaction.user.guild_permissions.administrator:
        return True

    db = interaction.client.db  # type: ignore[attr-defined]
    runtime = RuntimeSettings(db)
    staff_role_id = await runtime.staff_role_id()
    if staff_role_id is None:
        return False
    return any(role.id == staff_role_id for role in interaction.user.roles)


def staff_only():
    async def predicate(interaction: discord.Interaction) -> bool:
        ok = await is_staff(interaction)
        if not ok:
            raise app_commands.CheckFailure(
                "Kamu butuh izin staff buat pake command ini."
            )
        return True

    return app_commands.check(predicate)
