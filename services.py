import asyncio
import logging
import uuid
from pathlib import Path

from shazamio import Shazam
from yt_dlp import YoutubeDL
from yt_dlp.utils import match_filter_func

from . import config

log = logging.getLogger(__name__)
JOBS = asyncio.Semaphore(config.MAX_JOBS)
_shazam = Shazam()


def tmp(suffix: str) -> Path:
    config.TMP_DIR.mkdir(parents=True, exist_ok=True)
    return config.TMP_DIR / f"{uuid.uuid4().hex}{suffix}"


async def ffmpeg(*args: str) -> bool:
    proc = await asyncio.create_subprocess_exec(
        "ffmpeg", "-y", "-loglevel", "error", *args,
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    try:
        return await asyncio.wait_for(proc.wait(), 300) == 0
    except asyncio.TimeoutError:
        proc.kill()
        return False


async def make_circle(src: Path) -> Path | None:
    out = tmp(".mp4")
    ok = await ffmpeg(
        "-i", str(src), "-t", "60",
        "-vf", "crop=min(iw\\,ih):min(iw\\,ih),scale=640:640",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "26",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k",
        "-movflags", "+faststart", str(out))
    if ok and out.exists() and out.stat().st_size <= config.MAX_UPLOAD:
        return out
    out.unlink(missing_ok=True)
    return None


async def to_mp3(src: Path) -> Path | None:
    out = tmp(".mp3")
    ok = await ffmpeg("-i", str(src), "-vn", "-b:a", "192k", str(out))
    if ok and out.exists() and out.stat().st_size <= config.MAX_UPLOAD:
        return out
    out.unlink(missing_ok=True)
    return None


async def recognize(src: Path) -> dict | None:
    """Musiqani aniqlaydi. Topilmasa None, audio bo'lmasa RuntimeError."""
    sample = tmp(".mp3")
    try:
        ok = await ffmpeg("-i", str(src), "-t", "40", "-vn", "-ac", "1",
                          "-ar", "44100", str(sample))
        if not ok:
            raise RuntimeError("audio yo'q")
        fn = getattr(_shazam, "recognize", None) or _shazam.recognize_song
        res = await fn(str(sample))
    finally:
        sample.unlink(missing_ok=True)
    track = res.get("track")
    if not track:
        return None
    return {
        "title": track.get("title", "?"),
        "artist": track.get("subtitle", "?"),
        "url": track.get("url"),
        "cover": (track.get("images") or {}).get("coverart"),
    }


def _base_opts() -> dict:
    opts = {"quiet": True, "no_warnings": True, "socket_timeout": 30,
            "max_filesize": config.MAX_UPLOAD}
    if config.COOKIES_FILE:
        opts["cookiefile"] = config.COOKIES_FILE
    return opts


def _paths(info: dict) -> list[Path]:
    out = []
    for entry in info.get("entries") or [info]:
        for item in (entry or {}).get("requested_downloads") or []:
            p = Path(item["filepath"])
            if p.exists():
                out.append(p)
    return out


def _download(url: str) -> list[Path]:
    config.TMP_DIR.mkdir(parents=True, exist_ok=True)
    opts = _base_opts() | {
        "outtmpl": str(config.TMP_DIR / f"{uuid.uuid4().hex[:8]}_%(id).60s.%(ext)s"),
        "format": "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b",
        "merge_output_format": "mp4",
        "playlist_items": "1-10",
    }
    with YoutubeDL(opts) as ydl:
        return _paths(ydl.extract_info(url, download=True))


def _fetch_song(query: str) -> Path | None:
    config.TMP_DIR.mkdir(parents=True, exist_ok=True)
    opts = _base_opts() | {
        "outtmpl": str(config.TMP_DIR / f"song_{uuid.uuid4().hex[:8]}.%(ext)s"),
        "format": "bestaudio[ext=m4a]/bestaudio",
        "noplaylist": True,
        "match_filter": match_filter_func("duration < 600"),
    }
    with YoutubeDL(opts) as ydl:
        paths = _paths(ydl.extract_info(f"ytsearch1:{query}", download=True))
    return paths[0] if paths else None


async def download(url: str) -> list[Path]:
    return await asyncio.to_thread(_download, url)


async def fetch_song(query: str) -> Path | None:
    try:
        return await asyncio.to_thread(_fetch_song, query)
    except Exception:
        log.exception("Qo'shiqni yuklab bo'lmadi")
        return None
