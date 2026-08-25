"""Query helpers for the store leaderboard."""

from __future__ import annotations

from bot.database.core import Database


async def get_top_spenders(
    db: Database, limit: int = 10, excluded_user_ids: list[int] | None = None
) -> list[dict]:
    """Only counts orders with status='completed' AND payment_status='paid'
    -- cancelled/refunded orders never show up here regardless of
    `excluded_user_ids`. `excluded_user_ids` is an additional manual
    exclusion list (e.g. staff/tester accounts used to test checkout) kept
    in settings via /settings leaderboard_exclude, separate from the
    completed/paid filter."""
    excluded_user_ids = [uid for uid in (excluded_user_ids or []) if uid is not None]

    query = """
        SELECT
            user_id,
            SUM(total_price)   AS total_spent,
            COUNT(*)           AS total_orders,
            currency_label
        FROM orders
        WHERE status = 'completed' AND payment_status = 'paid'
    """
    params: list = []
    if excluded_user_ids:
        placeholders = ",".join("?" for _ in excluded_user_ids)
        query += f" AND user_id NOT IN ({placeholders})"
        params.extend(excluded_user_ids)
    query += """
        GROUP BY user_id
        ORDER BY total_spent DESC
        LIMIT ?
    """
    params.append(limit)

    rows = await db.fetchall(query, tuple(params))
    return [dict(r) for r in rows]


async def get_leaderboard_message_id(db: Database) -> int | None:
    from bot.database.queries.settings import get_setting
    value = await get_setting(db, "leaderboard_message_id")
    return int(value) if value else None


async def set_leaderboard_message_id(db: Database, message_id: int) -> None:
    from bot.database.queries.settings import set_setting
    await set_setting(db, "leaderboard_message_id", str(message_id))
