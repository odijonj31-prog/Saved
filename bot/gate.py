import logging

from aiogram import Bot, BaseMiddleware
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from . import config, db

log = logging.getLogger(__name__)


async def missing_channels(bot: Bot, uid: int) -> list:
    missing = []
    for ch in await db.list_channels():
        try:
            m = await bot.get_chat_member(ch["chat_id"], uid)
            if m.status in ("left", "kicked"):
                missing.append(ch)
        except Exception:
            log.warning("Obunani tekshirib bo'lmadi: %s", ch["chat_id"])
    return missing


def sub_keyboard(channels) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=f"📢 {c['title']}", url=c["link"])] for c in channels]
    rows.append([InlineKeyboardButton(text="✅ Tekshirish", callback_data="chk")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


class Gate(BaseMiddleware):
    """Foydalanuvchini saqlaydi, ban va majburiy obunani tekshiradi."""

    async def __call__(self, handler, event, data):
        user = event.from_user
        if user is None or user.is_bot:
            return await handler(event, data)

        row = await db.upsert_user(user)
        data["db_user"] = row
        if user.id in config.ADMIN_IDS:
            return await handler(event, data)

        msg = event if isinstance(event, Message) else event.message
        if row["banned"]:
            if isinstance(event, CallbackQuery):
                await event.answer("🚫 Siz bloklangansiz.", show_alert=True)
            else:
                await msg.answer("🚫 Siz bloklangansiz.")
            return

        if isinstance(event, CallbackQuery) and event.data == "chk":
            return await handler(event, data)

        missing = await missing_channels(data["bot"], user.id)
        if missing:
            if isinstance(event, CallbackQuery):
                await event.answer()
            await msg.answer("📌 Botdan foydalanish uchun kanallarga obuna bo'ling:",
                             reply_markup=sub_keyboard(missing))
            return
        return await handler(event, data)
