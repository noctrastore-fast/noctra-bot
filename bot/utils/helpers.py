"""Helper serbaguna yang dipakai bareng di semua cog: kalkulasi harga,
format mata uang, dan resolver runtime-settings yang nge-gabungin setting
dari DB di atas default dari `.env`.
"""

from __future__ import annotations

from bot.core.config import config
from bot.database.core import Database
from bot.database.queries import settings as settings_q


def calculate_final_price(
    base_price: float, discount_type: str | None, discount_value: float
) -> float:
    """Terapin diskon ke harga dasar. Selalu return float yang gak minus."""
    if not discount_type or discount_value <= 0:
        return round(max(0.0, base_price), 2)
    if discount_type == "percent":
        final = base_price - (base_price * (discount_value / 100))
    elif discount_type == "flat":
        final = base_price - discount_value
    else:
        final = base_price
    return round(max(0.0, final), 2)


def format_price(amount: float, currency_label: str) -> str:
    return f"{amount:,.2f} {currency_label}"


def discount_label(discount_type: str | None, discount_value: float) -> str | None:
    if not discount_type or discount_value <= 0:
        return None
    if discount_type == "percent":
        return f"-{discount_value:g}%"
    if discount_type == "flat":
        return f"-{discount_value:g}"
    return None


class RuntimeSettings:
    """Resolve setting yang efektif: override DB -> default .env."""

    def __init__(self, db: Database) -> None:
        self.db = db

    async def _get(self, key: str, env_default):
        value = await settings_q.get_setting(self.db, key)
        if value is None:
            return env_default
        return value

    async def staff_role_id(self) -> int | None:
        value = await self._get("staff_role_id", config.staff_role_id)
        return int(value) if value else None

    async def order_log_channel_id(self) -> int | None:
        value = await self._get("order_log_channel_id", None)
        return int(value) if value else None

    async def reviews_channel_id(self) -> int | None:
        """Channel publik tempat review yang udah di-approve otomatis
        diposting buat semua orang liat -- reputasi toko / social proof,
        bukan antrian moderasi staff."""
        value = await self._get("reviews_channel_id", None)
        return int(value) if value else None

    async def leaderboard_channel_id(self) -> int | None:
        value = await self._get("leaderboard_channel_id", None)
        return int(value) if value else None

    async def leaderboard_excluded_user_ids(self) -> list[int]:
        """User ID yang manual disembunyiin dari leaderboard Top Spenders
        lewat /settings leaderboard_exclude -- misal akun staff/tester yang
        dipake buat nyoba checkout, yang spend-nya gak seharusnya kehitung
        di leaderboard publik. Disimpan sebagai string ID dipisah koma."""
        value = await self._get("leaderboard_excluded_users", "")
        if not value:
            return []
        ids: list[int] = []
        for piece in str(value).split(","):
            piece = piece.strip()
            if piece.isdigit():
                ids.append(int(piece))
        return ids

    async def purchase_feed_channel_id(self) -> int | None:
        """Channel publik tempat kartu "Si X baru aja beli Y" diposting
        tiap ada order yang ditandain selesai -- diatur lewat
        /settings purchase_feed_channel."""
        value = await self._get("purchase_feed_channel_id", None)
        return int(value) if value else None

    async def ad_channel_id(self) -> int | None:
        """Channel default buat /iklan kalau parameter channel-nya gak
        diisi -- diatur lewat /settings ad_channel. Staff tetep bisa
        override channel tujuan tiap kali posting iklan lewat parameter
        `channel` di command itu sendiri."""
        value = await self._get("ad_channel_id", None)
        return int(value) if value else None

    async def main_server_invite_url(self) -> str | None:
        """Link invite server utama, ditampilin sebagai tombol "Join
        Server" abis customer selesai kasih review -- diatur lewat
        /settings main_server_invite."""
        return await self._get("main_server_invite_url", None)

    async def review_banner_url(self) -> str | None:
        """Gambar banner default buat kartu review publik, dipake kalau
        customer gak nyertain foto review sendiri -- diatur lewat
        /settings review_banner_image. Kalau belum diatur, kartu review
        tanpa foto ya tampil tanpa banner sama sekali (gak fallback ke
        apapun)."""
        return await self._get("review_banner_url", None)

    async def ticket_category_id(self) -> int | None:
        value = await self._get("ticket_category_id", config.ticket_category_id)
        return int(value) if value else None

    async def ticket_archive_category_id(self) -> int | None:
        value = await self._get(
            "ticket_archive_category_id", config.ticket_archive_category_id
        )
        return int(value) if value else None

    async def ticket_log_channel_id(self) -> int | None:
        value = await self._get("ticket_log_channel_id", config.ticket_log_channel_id)
        return int(value) if value else None

    async def ticket_auto_archive_hours(self) -> int:
        value = await self._get(
            "ticket_auto_archive_hours", config.ticket_auto_archive_hours
        )
        return int(value)

    async def default_currency(self) -> str:
        value = await self._get("default_currency", config.default_currency)
        return str(value)
