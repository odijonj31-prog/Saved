import time
from pathlib import Path

import aiosqlite

_db: aiosqlite.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY,
  username TEXT, first_name TEXT,
  joined_at INTEGER, last_seen INTEGER,
  banned INTEGER DEFAULT 0, active INTEGER DEFAULT 1,
  auto_circle INTEGER DEFAULT 1, auto_music INTEGER DEFAULT 1,
  downloads INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS channels(chat_id INTEGER PRIMARY KEY, title TEXT, link TEXT);
CREATE TABLE IF NOT EXISTS stats(day TEXT, key TEXT, n INTEGER DEFAULT 0, PRIMARY KEY(day, key));
"""

FLAGS = {"auto_circle", "auto_music"}


async def init(path: Path) -> None:
    global _db
    path.parent.mkdir(parents=True, exist_ok=True)
    _db = await aiosqlite.connect(path)
    _db.row_factory = aiosqlite.Row
    await _db.executescript(SCHEMA)
    await _db.commit()


def _today() -> str:
    return time.strftime("%Y-%m-%d", time.gmtime())


async def upsert_user(u) -> aiosqlite.Row:
    now = int(time.time())
    await _db.execute(
        "INSERT INTO users(id,username,first_name,joined_at,last_seen) VALUES(?,?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET username=excluded.username, "
        "first_name=excluded.first_name, last_seen=excluded.last_seen, active=1",
        (u.id, u.username, u.first_name, now, now),
    )
    await _db.commit()
    return await get_user(u.id)


async def get_user(uid: int):
    cur = await _db.execute("SELECT * FROM users WHERE id=?", (uid,))
    return await cur.fetchone()


async def set_flag(uid: int, field: str, value: int) -> None:
    if field not in FLAGS:
        return
    await _db.execute(f"UPDATE users SET {field}=? WHERE id=?", (value, uid))
    await _db.commit()


async def set_banned(uid: int, value: int) -> None:
    await _db.execute("UPDATE users SET banned=? WHERE id=?", (value, uid))
    await _db.commit()


async def set_active(uid: int, value: int) -> None:
    await _db.execute("UPDATE users SET active=? WHERE id=?", (value, uid))
    await _db.commit()


async def add_download(uid: int) -> None:
    await _db.execute("UPDATE users SET downloads=downloads+1 WHERE id=?", (uid,))
    await _db.commit()


async def incr(key: str) -> None:
    await _db.execute(
        "INSERT INTO stats(day,key,n) VALUES(?,?,1) "
        "ON CONFLICT(day,key) DO UPDATE SET n=n+1",
        (_today(), key),
    )
    await _db.commit()


async def _one(sql: str, *args) -> int:
    cur = await _db.execute(sql, args)
    row = await cur.fetchone()
    return row[0] or 0


async def summary() -> dict:
    now = int(time.time())
    midnight = now // 86400 * 86400
    s = {
        "users": await _one("SELECT COUNT(*) FROM users"),
        "active": await _one("SELECT COUNT(*) FROM users WHERE active=1 AND banned=0"),
        "banned": await _one("SELECT COUNT(*) FROM users WHERE banned=1"),
        "new_today": await _one("SELECT COUNT(*) FROM users WHERE joined_at>=?", midnight),
        "online_24h": await _one("SELECT COUNT(*) FROM users WHERE last_seen>=?", now - 86400),
    }
    for key in ("download", "circle", "shazam"):
        s[f"{key}_today"] = await _one(
            "SELECT n FROM stats WHERE day=? AND key=?", _today(), key)
        s[f"{key}_total"] = await _one("SELECT SUM(n) FROM stats WHERE key=?", key)
    return s


async def active_user_ids() -> list[int]:
    cur = await _db.execute("SELECT id FROM users WHERE active=1 AND banned=0")
    return [r[0] for r in await cur.fetchall()]


async def all_users():
    cur = await _db.execute("SELECT * FROM users ORDER BY joined_at")
    return await cur.fetchall()


async def add_channel(chat_id: int, title: str, link: str) -> None:
    await _db.execute(
        "INSERT OR REPLACE INTO channels(chat_id,title,link) VALUES(?,?,?)",
        (chat_id, title, link))
    await _db.commit()


async def del_channel(chat_id: int) -> None:
    await _db.execute("DELETE FROM channels WHERE chat_id=?", (chat_id,))
    await _db.commit()


async def list_channels():
    cur = await _db.execute("SELECT * FROM channels")
    return await cur.fetchall()
