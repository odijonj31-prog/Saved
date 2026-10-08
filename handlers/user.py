import asyncio
import html
import logging
import re
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandStart
from aiogram.types import (CallbackQuery, FSInputFile, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message)

from .. import config, db, services
from ..gate import missing_channels

log = logging.getLogger(__name__)
router = Router()
router.message.filter(F.chat.type == "private")

URL_RE = re.compile(r"https?://\S+")
VIDEO_EXT = {".mp4", ".mov", ".webm", ".mkv"}
IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp"}
AUDIO_EXT = {".mp3", ".m4a", ".ogg", ".opus", ".aac"}
ACTIONS = {"circle", "music", "mp3"}

CACHE: dict[str, Path] = {}   # tugma kaliti -> mahalliy fayl
BUSY: set[int] = set()        # bir vaqtda bitta so'rov


@asynccontextmanager
async def job(uid: int):
    if uid in BUSY:
        yield False
        return
    BUSY.add(uid)
    try:
        async with services.JOBS:
            yield True
    finally:
        BUSY.discard(uid)


def has_url(text: str) -> bool:
    return bool(URL_RE.search(text))


def remember(path: Path) -> str:
    key = uuid.uuid4().hex[:10]
    CACHE[key] = path
    return key


def actions_kb(key: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭕ Krujochka", callback_data=f"circle:{key}"),
         InlineKeyboardButton(text="🎵 Musiqa topish", callback_data=f"music:{key}")],
        [InlineKeyboardButton(text="🎧 MP3", callback_data=f"mp3:{key}")],
    ])


def settings_kb(u) -> InlineKeyboardMarkup:
    def mark(v): return "✅" if v else "❌"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"⭕ Avto-krujochka: {mark(u['auto_circle'])}",
                              callback_data="set:auto_circle")],
        [InlineKeyboardButton(text=f"🎵 Avto-musiqa: {mark(u['auto_music'])}",
                              callback_data="set:auto_music")],
    ])


HELP = (
    "🔗 <b>Link</b> yuboring (Instagram, TikTok, YouTube, X, Pinterest va b.) — "
    "video yoki fotoni yuklab beraman.\n"
    "🎬 <b>Video</b> yuboring — avtomatik krujochka qilaman va musiqasini topaman.\n"
    "🎤 <b>Audio / ovozli xabar</b> yuboring — qo'shiqni aniqlayman.\n"
    "⚙️ /settings — avtomatik funksiyalarni yoqish/o'chirish."
)


# ---------- yordamchilar ----------
async def send_file(message: Message, path: Path) -> None:
    if path.stat().st_size > config.MAX_UPLOAD:
        await message.answer("⚠️ Fayl 50 MB dan katta, Telegram yubora olmaydi.")
        path.unlink(missing_ok=True)
        return
    ext, file = path.suffix.lower(), FSInputFile(path)
    if ext in VIDEO_EXT:
        await message.answer_video(file, supports_streaming=True,
                                   reply_markup=actions_kb(remember(path)))
        return  # fayl tugmalar uchun saqlanadi
    if ext in IMAGE_EXT:
        try:
            await message.answer_photo(file)
        except TelegramBadRequest:
            await message.answer_document(file)
    elif ext in AUDIO_EXT:
        await message.answer_audio(file)
    else:
        await message.answer_document(file)
    path.unlink(missing_ok=True)


async def send_circle(message: Message, src: Path) -> None:
    status = await message.answer("⭕ Krujochka tayyorlanmoqda...")
    out = await services.make_circle(src)
    if out:
        await message.answer_video_note(FSInputFile(out), length=640)
        out.unlink(missing_ok=True)
        await db.incr("circle")
    else:
        await message.answer("❌ Krujochka qilib bo'lmadi.")
    await status.delete()


async def identify(message: Message, src: Path) -> None:
    status = await message.answer("🔎 Musiqa qidirilmoqda...")
    try:
        info = await services.recognize(src)
    except Exception:
        log.exception("Shazam xatosi")
        await status.edit_text("❌ Audio topilmadi yoki Shazam javob bermadi.")
        return
    if not info:
        await status.edit_text("😕 Musiqa topilmadi. Aniqroq yoki uzunroq qism yuboring.")
        return

    await db.incr("shazam")
    title, artist = html.escape(info["title"]), html.escape(info["artist"])
    text = f"🎵 <b>{title}</b>\n👤 {artist}"
    if info["url"]:
        text += f'\n🔗 <a href="{info["url"]}">Shazam</a>'
    await status.delete()
    if info["cover"]:
        await message.answer_photo(info["cover"], caption=text)
    else:
        await message.answer(text)

    song = await services.fetch_song(f"{info['artist']} - {info['title']}")
    if song:
        try:
            if song.stat().st_size <= config.MAX_UPLOAD:
                await message.answer_audio(FSInputFile(song), title=info["title"],
                                           performer=info["artist"])
        finally:
            song.unlink(missing_ok=True)


async def get_source(call: CallbackQuery, key: str, bot: Bot) -> Path | None:
    path = CACHE.get(key)
    if path and path.exists():
        return path
    m = call.message
    media = (m.video or m.video_note) if m else None
    if media and (media.file_size or 0) <= config.MAX_DOWNLOAD_FROM_TG:
        path = services.tmp(".mp4")
        await bot.download(media, destination=path)
        CACHE[key] = path
        return path
    return None


# ---------- buyruqlar ----------
@router.message(CommandStart())
async def start(message: Message):
    await message.answer(f"👋 <b>Salom, {html.escape(message.from_user.first_name)}!</b>\n\n{HELP}")


@router.message(Command("help"))
async def help_cmd(message: Message):
    await message.answer(HELP)


@router.message(Command("settings"))
async def settings(message: Message):
    u = await db.get_user(message.from_user.id)
    await message.answer("⚙️ <b>Sozlamalar</b>\nVideo yuborganingizda nima qilinsin:",
                         reply_markup=settings_kb(u))


@router.callback_query(F.data.startswith("set:"))
async def toggle(call: CallbackQuery):
    field = call.data.split(":", 1)[1]
    u = await db.get_user(call.from_user.id)
    if field in db.FLAGS:
        await db.set_flag(u["id"], field, 0 if u[field] else 1)
    u = await db.get_user(call.from_user.id)
    await call.message.edit_reply_markup(reply_markup=settings_kb(u))
    await call.answer("Saqlandi ✅")


@router.callback_query(F.data == "chk")
async def check_sub(call: CallbackQuery, bot: Bot):
    if await missing_channels(bot, call.from_user.id):
        await call.answer("Hali hamma kanalga obuna bo'lmadingiz ❗", show_alert=True)
        return
    await call.message.delete()
    await call.message.answer("✅ Rahmat! Endi link yoki video yuboring.")


# ---------- link ----------
@router.message(F.text.func(has_url))
async def on_link(message: Message):
    url = URL_RE.search(message.text).group(0)
    uid = message.from_user.id
    async with job(uid) as ok:
        if not ok:
            await message.answer("⏳ Oldingi so'rovingiz tugasin.")
            return
        status = await message.answer("⏳ Yuklanmoqda...")
        try:
            files = await services.download(url)
        except Exception:
            log.exception("Yuklashda xato: %s", url)
            await status.edit_text("❌ Yuklab bo'lmadi. Link noto'g'ri, profil yopiq "
                                   "yoki fayl 50 MB dan katta bo'lishi mumkin.")
            return
        if not files:
            await status.edit_text("❌ Hech narsa topilmadi.")
            return
        await status.delete()
        for path in files:
            await send_file(message, path)
        await db.incr("download")
        await db.add_download(uid)


# ---------- foydalanuvchi yuborgan video ----------
@router.message(F.video | F.video_note)
async def on_video(message: Message, bot: Bot, db_user):
    media = message.video or message.video_note
    if (media.file_size or 0) > config.MAX_DOWNLOAD_FROM_TG:
        await message.reply("⚠️ Telegram botlarga 20 MB gacha fayl yuklashga ruxsat beradi. "
                            "Kichikroq video yuboring yoki uning linkini tashlang.")
        return
    async with job(message.from_user.id) as ok:
        if not ok:
            await message.answer("⏳ Oldingi so'rovingiz tugasin.")
            return
        src = services.tmp(".mp4")
        await bot.download(media, destination=src)
        keep = False
        try:
            do_circle = bool(db_user["auto_circle"]) and not message.video_note
            do_music = bool(db_user["auto_music"])
            if not do_circle and not do_music:
                keep = True
                await message.reply("Nima qilay?", reply_markup=actions_kb(remember(src)))
                return
            if do_circle:
                if (getattr(media, "duration", 0) or 0) > 60:
                    await message.answer("ℹ️ Krujochka uchun faqat birinchi 60 soniya olinadi.")
                await send_circle(message, src)
            if do_music:
                await identify(message, src)
        finally:
            if not keep:
                src.unlink(missing_ok=True)


@router.message(F.audio | F.voice)
async def on_audio(message: Message, bot: Bot):
    media = message.audio or message.voice
    if (media.file_size or 0) > config.MAX_DOWNLOAD_FROM_TG:
        await message.reply("⚠️ Fayl 20 MB dan katta.")
        return
    async with job(message.from_user.id) as ok:
        if not ok:
            await message.answer("⏳ Oldingi so'rovingiz tugasin.")
            return
        src = services.tmp(".ogg")
        await bot.download(media, destination=src)
        try:
            await identify(message, src)
        finally:
            src.unlink(missing_ok=True)


# ---------- tugmalar ----------
@router.callback_query(F.data.func(lambda d: d.split(":")[0] in ACTIONS))
async def on_action(call: CallbackQuery, bot: Bot):
    action, key = call.data.split(":", 1)
    async with job(call.from_user.id) as ok:
        if not ok:
            await call.answer("⏳ Oldingi so'rovingiz tugasin.", show_alert=True)
            return
        src = await get_source(call, key, bot)
        if not src:
            await call.answer("Fayl eskirgan. Videoni qaytadan yuboring.", show_alert=True)
            return
        await call.answer("⏳ Ishlanmoqda...")
        msg = call.message
        if action == "circle":
            await send_circle(msg, src)
        elif action == "music":
            await identify(msg, src)
        elif action == "mp3":
            out = await services.to_mp3(src)
            if out:
                await msg.answer_audio(FSInputFile(out))
                out.unlink(missing_ok=True)
            else:
                await msg.answer("❌ MP3 ga o'tkazib bo'lmadi.")


@router.message(F.text & ~F.text.startswith("/"))
async def fallback(message: Message):
    await message.answer("🔗 Video/foto linkini yoki 🎬 video yuboring.")
