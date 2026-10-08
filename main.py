import asyncio
import logging
import shutil
import time

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

from . import config, db
from .gate import Gate
from .handlers import admin, user


async def cleanup_loop() -> None:
    while True:
        now = time.time()
        for p in config.TMP_DIR.glob("*"):
            try:
                if p.is_file() and now - p.stat().st_mtime > config.FILE_TTL:
                    p.unlink()
            except OSError:
                pass
        for key, path in list(user.CACHE.items()):
            if not path.exists():
                user.CACHE.pop(key, None)
        await asyncio.sleep(600)


async def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not config.BOT_TOKEN:
        raise SystemExit("BOT_TOKEN o'rnatilmagan!")
    if not shutil.which("ffmpeg"):
        raise SystemExit("ffmpeg o'rnatilmagan!")
    if not config.ADMIN_IDS:
        logging.warning("ADMIN_IDS bo'sh — admin panel ishlamaydi.")

    shutil.rmtree(config.TMP_DIR, ignore_errors=True)
    config.TMP_DIR.mkdir(parents=True, exist_ok=True)
    await db.init(config.DB_PATH)

    bot = Bot(config.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    gate = Gate()
    dp.message.outer_middleware(gate)
    dp.callback_query.outer_middleware(gate)
    dp.include_router(admin.router)  # admin birinchi: FSM holatlari ustun
    dp.include_router(user.router)

    await bot.set_my_commands([
        BotCommand(command="start", description="Boshlash"),
        BotCommand(command="help", description="Yordam"),
        BotCommand(command="settings", description="Sozlamalar"),
    ])
    cleaner = asyncio.create_task(cleanup_loop())
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        cleaner.cancel()


if __name__ == "__main__":
    asyncio.run(main())
