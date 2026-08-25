"""Posts or refreshes the leaderboard image in the configured channel."""

from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO

import aiohttp
import discord

from bot.core.logger import logger
from bot.database.queries import leaderboard as lb_q
from bot.utils.helpers import RuntimeSettings
from bot.utils.leaderboard_image import generate_leaderboard_image


async def _fetch_bytes(session: aiohttp.ClientSession, url: str) -> bytes | None:
    try:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=4)) as resp:
            if resp.status == 200:
                return await resp.read()
    except Exception:
        pass
    return None


async def refresh_leaderboard(bot) -> bool:
    db = bot.db
    runtime = RuntimeSettings(db)

    channel_id = await runtime.leaderboard_channel_id()
    if not channel_id:
        return False

    channel = bot.get_channel(channel_id)
    if not isinstance(channel, discord.TextChannel):
        return False

    # get_top_spenders only counts orders with status='completed' AND
    # payment_status='paid' -- cancelled/refunded orders never show up here
    # in the first place. On top of that, anyone manually excluded via
    # /settings leaderboard_exclude (e.g. staff/tester accounts) is dropped
    # too, so test orders don't show up on the public leaderboard.
    excluded = await runtime.leaderboard_excluded_user_ids()
    rows = await lb_q.get_top_spenders(db, limit=10, excluded_user_ids=excluded)
    if not rows:
        return False

    entries = []
    async with aiohttp.ClientSession() as session:
        for i, row in enumerate(rows):
            display_name = f"User {row['user_id']}"
            avatar_img = None
            try:
                user = bot.get_user(row["user_id"]) or await bot.fetch_user(row["user_id"])
                display_name = user.display_name
                av_data = await _fetch_bytes(session, str(user.display_avatar.url))
                if av_data:
                    from PIL import Image
                    avatar_img = Image.open(BytesIO(av_data)).convert("RGBA")
            except Exception:
                pass

            entries.append({
                "rank":           i,
                "display_name":   display_name,
                "total_spent":    row["total_spent"],
                "total_orders":   row["total_orders"],
                "currency_label": row["currency_label"],
                "avatar":         avatar_img,
            })

    ts = datetime.now(timezone.utc).strftime("Updated %d %b %Y, %H:%M UTC")
    buf = generate_leaderboard_image(
        entries,
        title="NOCTRA STORE",
        subtitle="TOP SPENDERS",
        timestamp=ts,
    )

    existing_id = await lb_q.get_leaderboard_message_id(db)
    if existing_id:
        try:
            msg = await channel.fetch_message(existing_id)
            buf.seek(0)
            await msg.edit(attachments=[discord.File(buf, filename="leaderboard.png")])
            logger.info("Leaderboard refreshed (edited message %s).", existing_id)
            return True
        except discord.NotFound:
            pass
        except discord.HTTPException:
            logger.exception("Failed to edit leaderboard, reposting.")

    try:
        buf.seek(0)
        new_msg = await channel.send(file=discord.File(buf, filename="leaderboard.png"))
        await lb_q.set_leaderboard_message_id(db, new_msg.id)
        logger.info("Leaderboard posted (new message %s).", new_msg.id)
        return True
    except discord.HTTPException:
        logger.exception("Failed to post leaderboard.")
        return False
