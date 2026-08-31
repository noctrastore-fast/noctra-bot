"""
Dengerin customer yang ngirim foto buat dilampirin ke review mereka.

Discord Modal cuma dukung field input teks -- gak ada komponen yang nerima
upload file -- jadi masukin foto ke review gak bisa lewat modal
rating/teks itu sendiri. Sebagai gantinya, abis modal itu disubmit, NOCTRA
minta customer buat kirim aja gambarnya sebagai pesan DM biasa (gak perlu
link, gak perlu command), dan listener ini yang nangkep.

Begitu fotonya masuk, ada 2 hal yang kejadian: (1) customer dapet DM
konfirmasi kayak biasa, dan (2) notifikasi internal "TESTI MONEY" (lihat
_notify_testi_proof) kekirim ke channel staff terpisah
(/settings testi_proof_channel) -- BEDA dari kartu review publik yang baru
muncul abis staff approve lewat /review admin approve.
"""

from __future__ import annotations

import discord
from discord.ext import commands

from bot.database.queries import orders as orders_q
from bot.database.queries import products as products_q
from bot.database.queries import reviews as reviews_q
from bot.ui import components, embeds
from bot.ui.views import build_join_server_view
from bot.utils import order_actions
from bot.utils.helpers import RuntimeSettings, format_price


class ReviewPhotoCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is not None:
            return  # cuma perhatiin DM dari user asli

        db = self.bot.db
        review = await reviews_q.get_awaiting_photo_review_for_user(db, message.author.id)
        if not review:
            return  # customer ini gak lagi diharapin ngirim foto review sekarang

        image_attachment = next(
            (a for a in message.attachments if (a.content_type or "").startswith("image/")), None
        )
        if not image_attachment:
            # Mereka lagi ngobrol soal hal lain (atau ngirim file bukan
            # gambar) -- jangan diem-diem dianggep "gak ada foto" dan
            # dilewatin; tunggu aja sampe ada gambar beneran atau tombol
            # Lewati diklik.
            return

        await reviews_q.update_review(db, review["id"], image_url=image_attachment.url)
        await reviews_q.set_awaiting_photo(db, review["id"], False)

        try:
            join_view = await build_join_server_view(db)
            await message.channel.send(
                embed=embeds.success_embed("Foto udah ditambahin ke review kamu. Makasih ya udah berbagi!"),
                view=join_view,
            )
        except discord.HTTPException:
            pass

        # Bersihin pesan prompt "Mau Tambahin Foto?" sekarang tugasnya udah kelar.
        await order_actions.cleanup_dm_messages(self.bot, review["order_id"])

        await self._notify_testi_proof(review, message.author, image_attachment.url)

    async def _notify_testi_proof(
        self, review, buyer: discord.User, photo_url: str
    ) -> None:
        """Notifikasi INTERNAL ke staff begitu foto bukti review masuk --
        BEDA dari bot.utils.review_actions.post_review_publicly() yang
        nge-post ke channel showcase publik abis staff approve; ini
        langsung kekirim ke channel terpisah (/settings testi_proof_channel)
        pas fotonya baru aja masuk, gak nunggu approval sama sekali. Gagal
        diem-diem aja (channel belum diatur, order/product gak ketemu,
        dst) -- jangan sampe nge-block alur konfirmasi DM ke customer di
        atas, itu prioritas utama."""
        db = self.bot.db
        runtime = RuntimeSettings(db)
        channel_id = await runtime.testi_proof_channel_id()
        if not channel_id:
            return
        channel = self.bot.get_channel(channel_id)
        if not isinstance(channel, discord.TextChannel):
            return

        order = await orders_q.get_order(db, review["order_id"])
        product = await products_q.get_product(db, review["product_id"])
        if not order or not product:
            return
        price_text = format_price(order["total_price"], order["currency_label"])

        container = components.testi_proof_container(
            buyer_display=buyer.mention,
            product_name=product["name"],
            price_text=price_text,
            testi_number=review["id"],
            photo_url=photo_url,
            emoji_title=await runtime.testi_proof_emoji_title(),
            emoji_buyer=await runtime.testi_proof_emoji_buyer(),
            emoji_product=await runtime.testi_proof_emoji_product(),
            emoji_price=await runtime.testi_proof_emoji_price(),
            emoji_testi=await runtime.testi_proof_emoji_testi(),
        )
        try:
            # allowed_mentions=none() SENGAJA -- buyer_display pake
            # buyer.mention biar tampilannya kayak chip mention di
            # referensi (highlight biru), tapi ini notif ke STAFF, jadi
            # gak boleh ikut nge-ping customer-nya di channel internal ini.
            await channel.send(
                view=components.NoctraLayout(container, timeout=None),
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException:
            pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ReviewPhotoCog(bot))
