# 🤖 Media Bot — yuklovchi + krujochka + Shazam + admin panel

## Imkoniyatlar
- 🔗 Link orqali video/foto yuklash (yt-dlp: Instagram, TikTok, YouTube, X, Pinterest va yana 1000+ sayt)
- 🎬 Foydalanuvchi video yuborsa — avtomatik **krujochka** + **musiqa topish** (+ to'liq qo'shiq)
- 🎤 Audio / ovozli xabardan Shazam
- ⚙️ `/settings` — har kim avto-funksiyalarni o'zi yoqadi/o'chiradi
- 🛠 `/admin` — statistika, reklama (tugma bilan, to'xtatish mumkin), majburiy obuna, ban, CSV
- 🧹 Vaqtinchalik fayllar avtomatik tozalanadi, bir vaqtda ishlov limiti bor

## Lokal ishga tushirish
```bash
pip install -r requirements.txt   # ffmpeg ham kerak
cp .env.example .env              # keyin o'zgaruvchilarni export qiling
export BOT_TOKEN=... ADMIN_IDS=...
python -m bot.main
```

## GitHub
```bash
git init && git add . && git commit -m "Media bot"
git branch -M main
git remote add origin https://github.com/<username>/<repo>.git
git push -u origin main
```

## Railway
1. railway.com → **New Project → Deploy from GitHub repo** → reponi tanlang (Dockerfile avtomatik topiladi).
2. **Variables**: `BOT_TOKEN`, `ADMIN_IDS`, `DATA_DIR=/data`.
3. **Volume** qo'shing va mount path `/data` qiling (baza restartda o'chib ketmasligi uchun).
4. Deploy. Har `git push` avtomatik qayta deploy qiladi.

## Eslatmalar
- Instagram/YouTube ba'zan cookies talab qiladi: `cookies.txt` ni volume'ga qo'yib `COOKIES_FILE=/data/cookies.txt` bering.
- Telegram limiti: botdan 50 MB gacha yuboriladi, botga 20 MB gacha qabul qilinadi.
- Majburiy obuna uchun botni kanalga **admin** qiling.
