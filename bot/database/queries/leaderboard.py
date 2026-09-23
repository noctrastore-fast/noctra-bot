"""Queries buat badge custom leaderboard (Top Spenders)."""

from __future__ import annotations

from bot.database.core import Database


async def get_badge(db: Database, user_id: int):
    return await db.fetchone("SELECT * FROM leaderboard_badges WHERE user_id = ?", (user_id,))


async def set_badge(db: Database, user_id: int, text: str, color_from: str, color_to: str) -> None:
    await db.execute(
        """
        INSERT INTO leaderboard_badges (user_id, text, color_from, color_to, updated_at)
        VALUES (?, ?, ?, ?, datetime('now'))
        ON CONFLICT(user_id) DO UPDATE SET
            text = excluded.text,
            color_from = excluded.color_from,
            color_to = excluded.color_to,
            updated_at = datetime('now')
        """,
        (user_id, text, color_from, color_to),
    )


async def delete_badge(db: Database, user_id: int) -> bool:
    """Return True kalau ada row yang beneran kehapus (dipake caller buat
    ngasih tau user kalau dia emang belum punya badge yang keset)."""
    row = await get_badge(db, user_id)
    if row is None:
        return False
    await db.execute("DELETE FROM leaderboard_badges WHERE user_id = ?", (user_id,))
    return True


async def list_badges(db: Database):
    return await db.fetchall("SELECT * FROM leaderboard_badges ORDER BY updated_at DESC")
