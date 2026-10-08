import asyncio
import csv
import io
import logging
import time

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (BufferedInputFile, CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message)

from .. import config, db

log = logging.getLogger(__name__)
router = Router()
router.message.filter(F.from_user.id.in_(config.ADMIN_IDS))
router.callback_query.filter(F.from_user.id.in_(config.ADMIN_IDS))

BC = {"running": False, "stop": False}
_tasks: set[asyncio.Task] = set()


class Bc(StatesGroup):
    msg = State()
    button = State()
    confirm = State()


class Ch(StatesGroup):
    wait = State()


class Ban(StatesGroup):
    wait = State()


def kb(*rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t, callback_data=d) for t, d in row] for row in rows])


PANEL = kb(
    [("📊 Statistika", "adm:stats"), ("📢 Reklama", "adm:bc")],
    [("📌 Majburiy obuna", "adm:ch"), ("🚫 Ban / Unban", "adm:ban")],
    [("👥 Foydalanuvchilar (CSV)", "adm:csv")],
)
BACK = kb([("⬅️ Panel", "adm:home")])


async def show_panel(target: Message | CallbackQuery) -> None:
    text = "🛠 <b>Admin panel</b>"
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=PANEL)
        await target.answer()
    else:
        await target.answer(text, reply_markup=PANEL)


@router.message(Command("admin"))
async def admin_cmd(message: Message, state: FSMContext):
    await state.clear()
    await show_panel(message)


@router.message(Command("cancel"))
async def cancel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Bekor qilindi.")
    await show_panel(message)


@router.callback_query(F.data == "adm:home")
async def home(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await show_panel(call)


# ---------- statistika ----------
@router.callback_query(F.data == "adm:stats")
async def stats(call: CallbackQuery):
    s = await db.summary()
    text = (
        "📊 <b>Statistika</b>\n\n"
        f"👥 Jami: <b>{s['users']}</b>  (faol: {s['active']}, ban: {s['banned']})\n"
        f"🆕 Bugun qo'shilgan: <b>{s['new_today']}</b>\n"
        f"🟢 So'nggi 24 soat: <b>{s['online_24h']}</b>\n\n"
        f"📥 Yuklashlar: bugun <b>{s['download_today']}</b> / jami {s['download_total']}\n"
        f"⭕ Krujochka: bugun <b>{s['circle_today']}</b> / jami {s['circle_total']}\n"
        f"🎵 Shazam: bugun <b>{s['shazam_today']}</b> / jami {s['shazam_total']}"
    )
    await call.message.edit_text(text, reply_markup=BACK)
    await call.answer()


@router.callback_query(F.data == "adm:csv")
async def users_csv(call: CallbackQuery):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "username", "first_name", "joined", "last_seen",
                "banned", "active", "downloads"])
    fmt = lambda t: time.strftime("%Y-%m-%d %H:%M", time.gmtime(t or 0))
    for u in await db.all_users():
        w.writerow([u["id"], u["username"], u["first_name"], fmt(u["joined_at"]),
                    fmt(u["last_seen"]), u["banned"], u["active"], u["downloads"]])
    await call.message.answer_document(
        BufferedInputFile(buf.getvalue().encode("utf-8-sig"), "users.csv"))
    await call.answer()


# ---------- reklama (broadcast) ----------
@router.callback_query(F.data == "adm:bc")
async def bc_start(call: CallbackQuery, state: FSMContext):
    if BC["running"]:
        await call.answer("Hozir boshqa reklama yuborilmoqda.", show_alert=True)
        return
    await state.set_state(Bc.msg)
    await call.message.edit_text(
        "📢 Reklama xabarini yuboring (matn, rasm, video, forward — istalgani).\n"
        "Bekor qilish: /cancel", reply_markup=BACK)
    await call.answer()


@router.message(Bc.msg)
async def bc_msg(message: Message, state: FSMContext):
    await state.update_data(chat=message.chat.id, mid=message.message_id)
    await state.set_state(Bc.button)
    await message.answer(
        "🔘 Xabar tagiga tugma qo'shasizmi?\n"
        "Format: <code>Matn - https://link.uz</code>\n"
        "Tugmasiz yuborish uchun /skip")


def _markup(data: dict):
    if data.get("btn_text"):
        return InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=data["btn_text"], url=data["btn_url"])]])
    return None


@router.message(Bc.button)
async def bc_button(message: Message, state: FSMContext, bot: Bot):
    text = (message.text or "").strip()
    if text != "/skip":
        if " - " not in text or not text.split(" - ", 1)[1].strip().startswith("http"):
            await message.answer("❌ Format noto'g'ri. Masalan: <code>Kanalga o'tish - https://t.me/kanal</code>")
            return
        t, u = text.split(" - ", 1)
        await state.update_data(btn_text=t.strip(), btn_url=u.strip())
    data = await state.get_data()
    n = len(await db.active_user_ids())
    await message.answer("👀 Ko'rinishi:")
    await bot.copy_message(message.chat.id, data["chat"], data["mid"], reply_markup=_markup(data))
    await state.set_state(Bc.confirm)
    await message.answer(f"Yuboramizmi? Qabul qiluvchilar: <b>{n}</b>",
                         reply_markup=kb([("✅ Yuborish", "bc:go"), ("❌ Bekor", "adm:home")]))


@router.callback_query(Bc.confirm, F.data == "bc:go")
async def bc_go(call: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    await state.clear()
    await call.message.edit_text("🚀 Yuborish boshlandi...")
    task = asyncio.create_task(run_broadcast(
        bot, call.from_user.id, data["chat"], data["mid"], _markup(data)))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    await call.answer()


@router.callback_query(F.data == "bc:stop")
async def bc_stop(call: CallbackQuery):
    BC["stop"] = True
    await call.answer("To'xtatilmoqda...")


async def run_broadcast(bot: Bot, admin_id: int, src_chat: int, src_msg: int, markup):
    BC.update(running=True, stop=False)
    ids = await db.active_user_ids()
    total, ok, blocked, failed = len(ids), 0, 0, 0
    stop_kb = kb([("⏹ To'xtatish", "bc:stop")])
    progress = await bot.send_message(admin_id, f"📤 0 / {total}", reply_markup=stop_kb)
    try:
        for i, uid in enumerate(ids, 1):
            if BC["stop"]:
                break
            for _ in range(2):
                try:
                    await bot.copy_message(uid, src_chat, src_msg, reply_markup=markup)
                    ok += 1
                    break
                except TelegramRetryAfter as e:
                    await asyncio.sleep(e.retry_after + 1)
                except TelegramForbiddenError:
                    blocked += 1
                    await db.set_active(uid, 0)
                    break
                except Exception:
                    failed += 1
                    break
            else:
                failed += 1
            if i % 25 == 0:
                try:
                    await progress.edit_text(f"📤 {i} / {total}", reply_markup=stop_kb)
                except Exception:
                    pass
            await asyncio.sleep(0.05)
    finally:
        stopped = BC["stop"]
        BC.update(running=False, stop=False)
    await progress.edit_text(
        f"{'⏹ To‘xtatildi' if stopped else '✅ Yakunlandi'}\n\n"
        f"📨 Yetkazildi: <b>{ok}</b>\n🚫 Botni bloklagan: <b>{blocked}</b>\n"
        f"⚠️ Xato: <b>{failed}</b>", reply_markup=BACK)


# ---------- majburiy obuna ----------
async def channels_view(target: Message | CallbackQuery):
    rows = [[InlineKeyboardButton(text=f"🗑 {c['title']}", callback_data=f"ch:del:{c['chat_id']}")]
            for c in await db.list_channels()]
    rows.append([InlineKeyboardButton(text="➕ Kanal qo'shish", callback_data="ch:add")])
    rows.append([InlineKeyboardButton(text="⬅️ Panel", callback_data="adm:home")])
    text = "📌 <b>Majburiy obuna kanallari</b>\n(Botni kanalga admin qilib qo'shing)"
    markup = InlineKeyboardMarkup(inline_keyboard=rows)
    if isinstance(target, CallbackQuery):
        await target.message.edit_text(text, reply_markup=markup)
        await target.answer()
    else:
        await target.answer(text, reply_markup=markup)


@router.callback_query(F.data == "adm:ch")
async def ch_list(call: CallbackQuery):
    await channels_view(call)


@router.callback_query(F.data == "ch:add")
async def ch_add(call: CallbackQuery, state: FSMContext):
    await state.set_state(Ch.wait)
    await call.message.edit_text(
        "Kanal <code>@username</code> yoki ID raqamini yuboring.\n"
        "Avval botni o'sha kanalga <b>admin</b> qiling. Bekor: /cancel")
    await call.answer()


@router.message(Ch.wait)
async def ch_save(message: Message, state: FSMContext, bot: Bot):
    raw = (message.text or "").strip().replace("https://t.me/", "@")
    ref = int(raw) if raw.lstrip("-").isdigit() else (raw if raw.startswith("@") else f"@{raw}")
    try:
        chat = await bot.get_chat(ref)
        me = await bot.get_chat_member(chat.id, bot.id)
        if me.status not in ("administrator", "creator"):
            raise ValueError("bot admin emas")
        link = (f"https://t.me/{chat.username}" if chat.username
                else chat.invite_link or await bot.export_chat_invite_link(chat.id))
    except Exception as e:
        await message.answer(f"❌ Bo'lmadi: {e}\nBot kanalda admin ekanini tekshiring.")
        return
    await db.add_channel(chat.id, chat.title or str(chat.id), link)
    await state.clear()
    await message.answer(f"✅ Qo'shildi: {chat.title}")
    await channels_view(message)


@router.callback_query(F.data.startswith("ch:del:"))
async def ch_del(call: CallbackQuery):
    await db.del_channel(int(call.data.split(":")[2]))
    await channels_view(call)


# ---------- ban ----------
@router.callback_query(F.data == "adm:ban")
async def ban_start(call: CallbackQuery, state: FSMContext):
    await state.set_state(Ban.wait)
    await call.message.edit_text(
        "Foydalanuvchi ID raqamini yuboring — ban bo'lmasa ban qilinadi, "
        "ban bo'lsa ochiladi. Bekor: /cancel")
    await call.answer()


@router.message(Ban.wait)
async def ban_toggle(message: Message, state: FSMContext):
    if not (message.text or "").strip().isdigit():
        await message.answer("❌ Faqat raqam yuboring.")
        return
    uid = int(message.text.strip())
    u = await db.get_user(uid)
    if not u:
        await message.answer("❌ Bunday foydalanuvchi topilmadi.")
        return
    new = 0 if u["banned"] else 1
    await db.set_banned(uid, new)
    await state.clear()
    await message.answer(f"{'🚫 Ban qilindi' if new else '✅ Ban ochildi'}: {uid}")
    await show_panel(message)
