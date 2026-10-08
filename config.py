import os
import tempfile
from pathlib import Path


def _ids(raw: str) -> set[int]:
    return {int(x) for x in raw.replace(" ", "").split(",") if x.lstrip("-").isdigit()}


BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_IDS = _ids(os.getenv("ADMIN_IDS", ""))
DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
DB_PATH = DATA_DIR / "bot.db"
TMP_DIR = Path(tempfile.gettempdir()) / "tgbot"
COOKIES_FILE = os.getenv("COOKIES_FILE") or None
MAX_JOBS = int(os.getenv("MAX_JOBS", "3"))

MAX_UPLOAD = 50 * 1024 * 1024          # botdan yuborish limiti
MAX_DOWNLOAD_FROM_TG = 20 * 1024 * 1024  # botga yuborilgan fayl limiti
FILE_TTL = 3600                        # vaqtinchalik fayllar 1 soat
