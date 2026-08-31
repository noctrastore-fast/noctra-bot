"""Helper serbaguna yang dipakai bareng di semua cog: kalkulasi harga,
format mata uang, dan resolver runtime-settings yang nge-gabungin setting
dari DB di atas default dari `.env`.
"""

from __future__ import annotations

from bot.core.config import config
from bot.database.core import Database
from bot.database.queries import settings as settings_q


def guild_scoped_key(base: str, guild_id: int) -> str:
    """Namespace-in key setting per-guild -- dipake KHUSUS /welcome & /joinrole
    (lihat bot.cogs.welcome) biar tiap server yang bot ini nemplok punya
    pesan sambutan & auto join-role sendiri-sendiri, TANPA ubah skema tabel
    `settings` yang masih global apa adanya buat semua fitur toko lainnya
    (category/product/order/ticket/settings/dst -- itu semua SENGAJA tetep
    satu-toko-satu-config, gak per-guild, soalnya NOCTRA emang didesain
    satu toko yang kebetulan bot-nya numpang di beberapa server lain).

    Formatnya "{base}:{guild_id}". PENTING: ini beda dari key lama yang
    dipake sebelum per-guild scoping ini ada (misal "welcome_channel_id"
    polos tanpa suffix) -- key lama otomatis kebaca "belum diatur" di
    server manapun, TERMASUK server utama yang udah pernah di-setup
    sebelumnya. Staff perlu `/welcome setup` + `/welcome channel` ulang
    sekali buat server utama abis migrasi ini (data lama gak kehapus,
    cuma gak kebaca lagi)."""
    return f"{base}:{guild_id}"


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

    async def _get_id_list(self, key: str) -> list[int]:
        """Parse setting yang nyimpen list ID sebagai string dipisah koma
        (dipake buat leaderboard_excluded_users, join_role_user_ids,
        join_role_bot_ids, dst)."""
        value = await self._get(key, "")
        if not value:
            return []
        ids: list[int] = []
        for piece in str(value).split(","):
            piece = piece.strip()
            if piece.isdigit():
                ids.append(int(piece))
        return ids

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
        return await self._get_id_list("leaderboard_excluded_users")

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

    # -- Pesan sambutan member baru (/welcome) ---------------------------------
    # Method di bawah ini SEMUANYA per-guild (parameter guild_id wajib) --
    # beda dari method lain di kelas ini yang masih global. Lihat docstring
    # guild_scoped_key() di atas buat alasannya.

    async def welcome_enabled(self, guild_id: int) -> bool:
        value = await self._get(guild_scoped_key("welcome_enabled", guild_id), "1")
        return str(value) == "1"

    async def welcome_mention_enabled(self, guild_id: int) -> bool:
        """Apakah member yang baru gabung di-ping (lewat message content)
        pas pesan sambutan diposting -- default nyala, diatur lewat
        /welcome mention."""
        value = await self._get(guild_scoped_key("welcome_mention_enabled", guild_id), "1")
        return str(value) == "1"

    async def welcome_channel_id(self, guild_id: int) -> int | None:
        value = await self._get(guild_scoped_key("welcome_channel_id", guild_id), None)
        return int(value) if value else None

    async def welcome_title(self, guild_id: int) -> str | None:
        """Template judul embed sambutan -- None berarti belum diatur,
        caller fallback ke default bawaan. String kosong (hasil ngosongin
        field pas /welcome setup) DIANGGEP sama kayak belum diatur, biar
        staff bisa "reset ke default" cukup dengan ngosongin field-nya."""
        value = await self._get(guild_scoped_key("welcome_title", guild_id), None)
        return value or None

    async def welcome_description(self, guild_id: int) -> str | None:
        value = await self._get(guild_scoped_key("welcome_description", guild_id), None)
        return value or None

    async def welcome_banner_url(self, guild_id: int) -> str | None:
        """URL gambar banner full-width buat pesan sambutan -- HARUS URL
        yang udah di-hosting (bukan upload attachment), soalnya pesan ini
        diposting otomatis berkali-kali setiap ada yang gabung, gak kayak
        /iklan yang cuma sekali kirim manual."""
        value = await self._get(guild_scoped_key("welcome_banner_url", guild_id), None)
        return value or None

    async def welcome_footer_text(self, guild_id: int) -> str | None:
        value = await self._get(guild_scoped_key("welcome_footer_text", guild_id), None)
        return value or None

    async def welcome_color(self, guild_id: int) -> int | None:
        value = await self._get(guild_scoped_key("welcome_color", guild_id), None)
        if not value:
            return None
        try:
            return int(str(value))
        except ValueError:
            return None

    # -- Auto join-role (/joinrole) --------------------------------------------
    # Sama kayak /welcome di atas -- per-guild, lihat guild_scoped_key().

    async def join_role_user_ids(self, guild_id: int) -> list[int]:
        """Role yang otomatis kepasang ke MEMBER BIASA (bukan bot) pas
        gabung -- diatur lewat /joinrole add target:user."""
        return await self._get_id_list(guild_scoped_key("join_role_user_ids", guild_id))

    async def join_role_bot_ids(self, guild_id: int) -> list[int]:
        """Role yang otomatis kepasang ke BOT pas ditambahin ke server --
        diatur lewat /joinrole add target:bot."""
        return await self._get_id_list(guild_scoped_key("join_role_bot_ids", guild_id))

    # -- Status toko (/storestatus) -------------------------------------------

    async def store_status_channel_id(self) -> int | None:
        """Channel tempat embed status toko diposting/di-update --
        diatur lewat /storestatus channel."""
        value = await self._get("store_status_channel_id", None)
        return int(value) if value else None

    async def store_status_message_id(self) -> int | None:
        """ID pesan embed status toko yang lagi aktif, dipake buat edit-in-place
        pas staff toggle buka/tutup (bukan kirim pesan baru tiap kali) --
        di-reset ke kosong kalau channel-nya diganti."""
        value = await self._get("store_status_message_id", None)
        return int(value) if value else None

    async def store_status_state(self) -> str:
        """State toko sekarang: 'open' atau 'closed'. Default 'closed'
        sampe staff toggle manual lewat /storestatus open|close -- gak ada
        jadwal otomatis, semuanya manual."""
        value = await self._get("store_status_state", "closed")
        return str(value) if value in ("open", "closed") else "closed"

    async def store_status_note(self) -> str | None:
        """Catetan opsional yang nempel di bawah status (misal 'balik lagi
        jam 9 pagi WIB') -- diisi tiap kali /storestatus open|close dipanggil,
        kosong kalau staff gak ngisi parameter catatan."""
        return await self._get("store_status_note", None)

    async def store_status_emoji_open(self) -> str:
        """Emoji custom buat indikator status BUKA -- diatur lewat
        /storestatus emoji, default emoji bulet hijau bawaan Discord."""
        value = await self._get("store_status_emoji_open", "\U0001F7E2")
        return str(value)

    async def store_status_emoji_closed(self) -> str:
        """Emoji custom buat indikator status TUTUP -- diatur lewat
        /storestatus emoji, default emoji bulet merah bawaan Discord."""
        value = await self._get("store_status_emoji_closed", "\U0001F534")
        return str(value)

    async def store_status_thumbnail_url(self) -> str | None:
        """URL gambar thumbnail kecil di pojok kanan atas embed status toko --
        diatur lewat /storestatus thumbnail. HARUS URL yang udah di-hosting
        (bukan upload attachment), soalnya pesan ini diedit berkali-kali tiap
        staff toggle, sama alasannya kayak welcome_banner_url."""
        value = await self._get("store_status_thumbnail_url", None)
        return value or None

    # -- Kartu review publik (/settings review_emoji) --------------------------
    # Dipake components.review_card_container() -- diposting ke
    # /settings reviews_channel abis staff approve review.

    async def review_card_emoji_title(self) -> str:
        return str(await self._get("review_card_emoji_title", "\U0001F31F"))

    async def review_card_emoji_user(self) -> str:
        return str(await self._get("review_card_emoji_user", "\U0001F464"))

    async def review_card_emoji_product(self) -> str:
        return str(await self._get("review_card_emoji_product", "\U0001F4E6"))

    async def review_card_emoji_star_filled(self) -> str:
        return str(await self._get("review_card_emoji_star_filled", "\u2b50"))

    async def review_card_emoji_star_empty(self) -> str:
        return str(await self._get("review_card_emoji_star_empty", "\u2606"))

    async def review_card_emoji_message(self) -> str:
        return str(await self._get("review_card_emoji_message", "\U0001F4AC"))

    # -- Notifikasi bukti foto review (/settings testi_proof_channel) ----------
    # Dipake bot.cogs.review_photo -- BEDA dari reviews_channel di atas: ini
    # notif INTERNAL staff langsung begitu foto masuk, bukan showcase publik
    # yang nunggu approve.

    async def testi_proof_channel_id(self) -> int | None:
        value = await self._get("testi_proof_channel_id", None)
        return int(value) if value else None

    async def testi_proof_emoji_title(self) -> str:
        return str(await self._get("testi_proof_emoji_title", "\U0001F4B0"))

    async def testi_proof_emoji_buyer(self) -> str:
        return str(await self._get("testi_proof_emoji_buyer", "\U0001F464"))

    async def testi_proof_emoji_product(self) -> str:
        return str(await self._get("testi_proof_emoji_product", "\U0001F4E6"))

    async def testi_proof_emoji_price(self) -> str:
        return str(await self._get("testi_proof_emoji_price", "\U0001F4B5"))

    async def testi_proof_emoji_testi(self) -> str:
        return str(await self._get("testi_proof_emoji_testi", "\U0001F31F"))
