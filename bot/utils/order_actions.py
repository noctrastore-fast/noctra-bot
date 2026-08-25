"""
Logic transisi status order yang dipakai bareng: notifikasi DM ke customer,
restock stok pas cancel/refund, dan mulai prompt review button-only pas
order selesai.

Dipakai BARENG sama command admin `/order` dan tombol OrderActionButton di
channel order-log, jadi customer dapet notifikasi yang sama persis gak
peduli staff pake cara yang mana buat update order.
"""

from __future__ import annotations

import discord

from bot.core.logger import logger
from bot.database.queries import category_types as category_types_q
from bot.database.queries import orders as orders_q
from bot.database.queries import payments as payments_q
from bot.database.queries import products as products_q
from bot.database.queries import reviews as reviews_q
from bot.ui import components, embeds
from bot.utils.helpers import RuntimeSettings


async def _notify_customer(
    bot,
    user_id: int,
    embed: discord.Embed | None = None,
    view: discord.ui.View | None = None,
    *,
    order_id: int | None = None,
    track: bool = False,
    layout: discord.ui.LayoutView | None = None,
) -> bool:
    """Kirim DM ke customer. Kalau `track` True (dan `order_id` diisi),
    pesan yang terkirim dicatat di order_dm_messages biar bisa dihapus
    belakangan -- dipakai buat pesan kerja yang sementara (notif status,
    prompt review, balesan staff), beda sama invoice final yang emang
    didesain buat nempel permanen.

    `layout` dipake buat pesan Components V2 (LayoutView) -- gak bisa
    dicampur sama `embed`/`view` biasa dalam satu pesan Discord, jadi kalau
    `layout` diisi, itu satu-satunya yang dikirim."""
    try:
        user = bot.get_user(user_id) or await bot.fetch_user(user_id)
        if layout is not None:
            sent = await user.send(view=layout)
        elif view is not None:
            sent = await user.send(embed=embed, view=view)
        else:
            sent = await user.send(embed=embed)
        if track and order_id is not None:
            await orders_q.add_dm_message(bot.db, order_id, sent.channel.id, sent.id)
        return True
    except discord.HTTPException:
        logger.warning("Gagal DM user %s -- kemungkinan DM-nya ditutup.", user_id)
        return False


async def send_message_to_customer(
    bot, user_id: int, embed: discord.Embed, order_id: int | None = None
) -> bool:
    """Wrapper publik buat staff kirim DM ke customer (dipakai /order message
    dan tombol Reply di order-log). Ke-track buat dibersihin belakangan
    kalau `order_id` diisi, sama kayak pesan checkout lainnya."""
    return await _notify_customer(bot, user_id, embed, order_id=order_id, track=True)


async def forward_to_staff(
    bot, order_id: int, user: discord.abc.User, content: str, attachment_urls: list[str]
) -> bool:
    """Neruskan DM customer (misal screenshot bukti bayar) ke channel
    order-log, ditandain order ID dan customer-nya, jadi staff tau persis
    siapa yang bayar buat apa tanpa customer perlu buka ticket. Return
    False kalau channel order-log belum diatur."""
    db = bot.db
    runtime = RuntimeSettings(db)
    log_channel_id = await runtime.order_log_channel_id()
    if not log_channel_id:
        return False
    channel = bot.get_channel(log_channel_id)
    if not isinstance(channel, discord.TextChannel):
        return False

    embed = embeds.info_embed(
        f"Pesan dari Customer -- Order #{order_id}",
        content if content else "*(gak ada teks -- lihat lampiran)*",
    )
    embed.add_field(name="Customer", value=f"<@{user.id}> ({user})", inline=False)
    if attachment_urls:
        embed.set_image(url=attachment_urls[0])
        if len(attachment_urls) > 1:
            embed.add_field(
                name="Lampiran Lainnya", value="\n".join(attachment_urls[1:]), inline=False
            )

    # Import ditunda: bot.ui.views ngimport module ini di level atas (buat
    # OrderActionButton/ReplyButton), jadi kalau di-import balik di sini di
    # level module bakal circular. Pas fungsi ini beneran jalan, views udah
    # ke-load penuh, jadi import lazy ini aman.
    from bot.ui.views import ReplyButton

    view = discord.ui.View(timeout=None)
    view.add_item(ReplyButton(order_id))

    try:
        await channel.send(embed=embed, view=view)
        return True
    except discord.HTTPException:
        logger.exception("Gagal forward pesan customer buat order #%s.", order_id)
        return False


async def cleanup_dm_messages(bot, order_id: int) -> None:
    """Hapus pesan-pesan checkout (ringkasan order, instruksi bayar, dst)
    yang NOCTRA kirim ke DM customer buat order ini, biar order yang udah
    selesai gak numpuk terus di riwayat DM mereka. Pake channel_id +
    message_id langsung (get_partial_message) daripada nyimpen objek pesan
    aslinya, soalnya ini bisa jalan berhari-hari setelah pesannya dikirim --
    jauh lewat masa berlaku webhook token apapun."""
    db = bot.db
    tracked = await orders_q.list_dm_messages(db, order_id)
    for row in tracked:
        try:
            channel = bot.get_channel(row["channel_id"]) or await bot.fetch_channel(row["channel_id"])
            await channel.get_partial_message(row["message_id"]).delete()
        except discord.HTTPException:
            pass  # udah kehapus, DM ketutup, atau kelamaan -- aman diabaikan
    await orders_q.clear_dm_messages(db, order_id)


async def _post_purchase_announcement(bot, order, product) -> None:
    """Posting kartu publik "Si X baru aja beli Y" ke channel purchase-feed
    yang diatur -- lihat /settings purchase_feed_channel. Diem-diem gak
    ngapa-ngapain kalau channel-nya belum diatur atau customer-nya gak bisa
    ditemuin; ini cuma pemanis, bukan sesuatu yang boleh nge-block atau
    gagalin alur completion order yang sesungguhnya."""
    if not product:
        return

    db = bot.db
    runtime = RuntimeSettings(db)
    channel_id = await runtime.purchase_feed_channel_id()
    if not channel_id:
        return

    channel = bot.get_channel(channel_id)
    if not isinstance(channel, discord.TextChannel):
        return

    try:
        user = bot.get_user(order["user_id"]) or await bot.fetch_user(order["user_id"])
        buyer_display = user.display_name
        buyer_avatar_url = user.display_avatar.url
    except discord.HTTPException:
        buyer_display = f"User {order['user_id']}"
        buyer_avatar_url = None

    category_type = await category_types_q.get_category_type(db, product["category_type_id"])
    embed = embeds.purchase_announcement_embed(buyer_display, buyer_avatar_url, product, category_type, order)

    try:
        await channel.send(embed=embed)
    except discord.HTTPException:
        logger.exception("Gagal posting pengumuman pembelian buat order #%s.", order["id"])


async def mark_paid(bot, order_id: int) -> tuple[bool, str]:
    db = bot.db
    order = await orders_q.get_order(db, order_id)
    if not order:
        return False, "Order gak ketemu."

    await orders_q.set_payment_status(db, order_id, "paid")
    if order["status"] == "pending":
        await orders_q.set_order_status(db, order_id, "processing")

    await _notify_customer(
        bot,
        order["user_id"],
        embeds.success_embed(
            f"Order kamu #{order_id} udah ditandain **lunas** dan lagi diproses."
        ),
        order_id=order_id,
        track=True,
    )
    return True, f"Order #{order_id} ditandain lunas."


async def mark_completed(bot, order_id: int) -> tuple[bool, str]:
    db = bot.db
    order = await orders_q.get_order(db, order_id)
    if not order:
        return False, "Order gak ketemu."

    await orders_q.set_order_status(db, order_id, "completed")
    if order["payment_status"] != "paid":
        # Order yang selesai otomatis berarti udah lunas -- tanpa ini,
        # staff yang klik "Mark Completed" tanpa klik "Mark Paid" duluan
        # bakal bikin payment_status nyangkut di "pending" selamanya, yang
        # diem-diem ngeblokir tombol review customer (butuh dua-duanya).
        await orders_q.set_payment_status(db, order_id, "paid")

    # Bersihin semua pesan kerja sementara buat order ini (alur checkout,
    # notif "udah lunas", balesan staff yang ada) sebelum kirim invoice
    # permanen -- biar invoice jadi awal yang bersih dari sisa DM customer,
    # bukan ketimbun di bawah yang lain.
    await cleanup_dm_messages(bot, order_id)

    product = await products_q.get_product(db, order["product_id"])
    product_name = product["name"] if product else "pembelian kamu"
    payment = (
        await payments_q.get_payment_method(db, order["payment_method_id"])
        if order["payment_method_id"]
        else None
    )

    # Ambil avatar bot langsung -- jadi kalau icon bot diganti, invoice ini
    # otomatis ikut sync tanpa perlu setting manual apapun.
    bot_avatar_url = bot.user.display_avatar.url if bot.user else None
    invoice_layout = components.invoice_view(order, product, payment, bot_avatar_url=bot_avatar_url)
    # Gak di-track -- invoice ini emang didesain buat nempel permanen
    # sebagai bukti pembelian customer, beda sama pesan lain di alur ini.
    await _notify_customer(bot, order["user_id"], layout=invoice_layout)

    existing_review = await reviews_q.get_review_by_order(db, order_id)
    if not existing_review:
        # Import ditunda: bot.ui.views ngimport module ini di level atas
        # (buat OrderActionButton), jadi kalau di-import balik di sini di
        # level module bakal circular. Pas fungsi ini beneran jalan, views
        # udah ke-load penuh, jadi import lazy ini aman dan murah.
        from bot.ui.views import ReviewStartButton

        review_view = discord.ui.View(timeout=None)
        review_view.add_item(ReviewStartButton(order_id))
        review_embed = embeds.info_embed(
            "Gimana Belanjanya?",
            f"Kasih tau orang lain gimana pendapat kamu soal **{product_name}**. "
            "Klik di bawah buat kasih rating -- gak perlu command apa-apa.",
        )
        # Di-track: begitu customer beneran submit review, prompt ini (dan
        # tombolnya) otomatis dibersihin -- lihat RatingButton di
        # bot.ui.views.
        await _notify_customer(bot, order["user_id"], review_embed, review_view, order_id=order_id, track=True)

    # Posting pengumuman pembelian ke channel purchase-feed, kalau diatur.
    try:
        await _post_purchase_announcement(bot, order, product)
    except Exception:  # noqa: BLE001
        logger.warning("Pengumuman pembelian gagal diem-diem abis order #%s.", order_id)

    # Refresh gambar leaderboard -- import lazy, fire-and-forget.
    try:
        from bot.utils.leaderboard import refresh_leaderboard
        await refresh_leaderboard(bot)
    except Exception:  # noqa: BLE001
        logger.warning("Refresh leaderboard gagal diem-diem abis order #%s.", order_id)

    return True, f"Order #{order_id} ditandain selesai."


async def cancel_order(bot, order_id: int, reason: str | None) -> tuple[bool, str]:
    db = bot.db
    order = await orders_q.get_order(db, order_id)
    if not order:
        return False, "Order gak ketemu."

    await orders_q.set_order_status(db, order_id, "cancelled")
    await orders_q.set_payment_status(db, order_id, "cancelled")
    if order["stock_reserved"]:
        await products_q.adjust_stock(db, order["product_id"], 1)
        await orders_q.clear_stock_reserved(db, order_id)

    text = f"Order kamu #{order_id} udah **dibatalin**."
    if reason:
        text += f"\nAlasan: {reason}"
    await _notify_customer(bot, order["user_id"], embeds.error_embed(text))

    # Jaga leaderboard tetep akurat langsung saat itu juga. get_top_spenders
    # emang udah nge-filter yang bukan status='completed', tapi kalau order
    # ini sempet ditandain selesai sebelumnya dan baru sekarang dibatalin,
    # gambar leaderboard yang udah keposting gak bakal ngedrop spend-nya
    # sampe ada yang trigger refresh -- jadi langsung trigger di sini aja.
    try:
        from bot.utils.leaderboard import refresh_leaderboard
        await refresh_leaderboard(bot)
    except Exception:  # noqa: BLE001
        logger.warning("Refresh leaderboard gagal diem-diem abis batalin order #%s.", order_id)

    return True, f"Order #{order_id} dibatalin."


async def refund_order(bot, order_id: int, reason: str | None) -> tuple[bool, str]:
    db = bot.db
    order = await orders_q.get_order(db, order_id)
    if not order:
        return False, "Order gak ketemu."

    await orders_q.set_order_status(db, order_id, "refunded")
    if order["stock_reserved"]:
        await products_q.adjust_stock(db, order["product_id"], 1)
        await orders_q.clear_stock_reserved(db, order_id)

    text = f"Order kamu #{order_id} udah **di-refund**."
    if reason:
        text += f"\nAlasan: {reason}"
    await _notify_customer(bot, order["user_id"], embeds.error_embed(text))

    # Alasan sama kayak cancel_order -- refund bisa aja kejadian abis order
    # udah sempet selesai dan kehitung, jadi langsung refresh aja.
    try:
        from bot.utils.leaderboard import refresh_leaderboard
        await refresh_leaderboard(bot)
    except Exception:  # noqa: BLE001
        logger.warning("Refresh leaderboard gagal diem-diem abis refund order #%s.", order_id)

    return True, f"Order #{order_id} di-refund."
