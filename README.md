# Sahovat Shifo — Gemifikatsion Referral Bot

Telegram bot + admin web dashboard. Vazifasi: kim kanalga necha kishi qo'shganini
**ishonchli** hisoblash va gemifikatsiya darajalariga ko'ra chegirma kodlari berish.

## Qanday ishlaydi (mexanizm)

1. Foydalanuvchi botda `/start` bosadi → unga **shaxsiy unikal taklif havolasi** beriladi
   (`createChatInviteLink`).
2. U havolani do'stlariga ulashadi. Do'st havola orqali kanalga qo'shilganda, Telegram botga
   `chat_member` yangilanishini yuboradi — unda **qaysi havola** ishlatilgani ko'rsatiladi.
3. Bot havola egasini topadi, qo'shilishni yozadi (dublikat va o'z-o'zini qo'shish sanalmaydi).
4. Faol a'zolar soni darajaga yetganda, bot avtomatik **chegirma kodi** beradi.
5. Mijoz klinikaga kelganda kodni ko'rsatadi; xodim admin paneldan kodni "band qildim" deb belgilaydi.

## Gemifikatsiya darajalari

| A'zo soni | Mukofot |
|-----------|---------|
| 5 ta  | Doktor ko'rigiga 50% chegirma (bir martalik) |
| 10 ta | Doktor ko'rigiga 100% chegirma + bepul umumiy qon tahlili va qondagi qand |
| 20 ta | 2 ta doktor ko'rigiga 100% chegirma + bepul qon tahlili va qand |

Darajalarni o'zgartirish/qo'shish: faqat `app/rewards.py` dagi `TIERS` ro'yxatini tahrirlang.

---

## 1-QADAM. Telegram kanalni tayyorlash (siz bajarasiz)

1. Botni (`@...`) kanalingizga **admin** qiling.
2. Admin huquqlarida quyidagilarni yoqing:
   - **Taklif havolalari orqali a'zo qo'shish** (Invite users via link) — MAJBURIY.
   - Xabar yuborish (ixtiyoriy).
3. Kanal **yopiq (private)** bo'lsa, `CHANNEL_ID` raqamli bo'ladi (`-100xxxxxxxxxx`).
   Kanal **ommaviy (public)** bo'lsa, `CHANNEL_ID = @username`.
   - Raqamli ID ni bilish: kanaldan biror postni `@userinfobot` ga forward qiling,
     yoki bot loglarida deploydan keyin ko'rinadi.

> Diqqat: bot kanalga admin bo'lmasa, havola yaratolmaydi va qo'shilishlarни ko'rmaydi.

---

## 2-QADAM. Deploy — Render.com (BEPUL, tavsiya)

Render bepul tarifda web servis + bepul Postgres beradi. `render.yaml` allaqachon tayyor.

### a) Kodni GitHub'ga joylash
```bash
cd saxovat-bot
git init && git add . && git commit -m "init"
# GitHub'da yangi (private) repo oching va:
git remote add origin https://github.com/SIZNING_AKKAUNT/saxovat-bot.git
git push -u origin main
```

### b) Render'da deploy
1. https://render.com → ro'yxatdan o'ting (GitHub bilan).
2. **New → Blueprint** → repongizni tanlang. Render `render.yaml` ni o'qiydi va
   web servis + Postgres yaratadi.
3. **Environment** bo'limida quyidagi maxfiy qiymatlarni kiriting:
   - `BOT_TOKEN` — BotFather tokeni
   - `CHANNEL_ID` — `@username` yoki `-100...`
   - `ADMIN_PASSWORD` — admin panel uchun kuchli parol
   - `ADMIN_IDS` — (ixtiyoriy) bot ichida `/stats` ko'ra oladigan Telegram ID lar
   - `WEBHOOK_SECRET`, `SESSION_SECRET` — Render avtomatik generatsiya qiladi
   - `DATABASE_URL` — Postgres'dan avtomatik ulanadi
4. Birinchi deploydan keyin Render sizga URL beradi, masalan
   `https://saxovat-bot.onrender.com`.
5. Shu URL ni `WEBHOOK_BASE_URL` env'ga yozing va servisni **qayta deploy** qiling.
   Endi bot webhookni o'rnatadi va ishlaydi.

### c) Tekshirish
- Brauzerda `https://saxovat-bot.onrender.com/healthz` → `{"ok": true}` ko'rinsa, server tirik.
- Botga `/start` yozing → havola va tayyor post kelishi kerak.
- Boshqa akkaunt bilan havola orqali kanalga qo'shiling → birinchi akkauntga "yangi a'zo" xabari keladi.

> **Bepul tarif eslatmasi:** Render bepul web servisi 15 daqiqa harakatsizlikdan keyin "uxlaydi".
> Webhook kelganda u uyg'onadi (Telegram qayta yuboradi), lekin bir necha soniya kechikishi mumkin.
> Yuqori ishonchlilik kerak bo'lsa, Railway yoki $7/oy "always-on" tarif yoki VPS tavsiya etiladi.

---

## Muqobil: VPS + Docker

```bash
# serverda
git clone <repo> && cd saxovat-bot
cp .env.example .env   # .env ni to'ldiring (BOT_TOKEN, CHANNEL_ID, WEBHOOK_BASE_URL, ...)
docker build -t saxovat-bot .
docker run -d --name saxovat-bot --env-file .env -p 8000:8000 saxovat-bot
```
WEBHOOK_BASE_URL — domeningiz (HTTPS shart, masalan Caddy/Nginx orqali).
Postgres ishlatish tavsiya etiladi; SQLite ishlatsangiz, faylni doimiy diskka (volume) ulang.

---

## Lokal test (kompyuterda)

```bash
cd saxovat-bot
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env       # BOT_TOKEN va CHANNEL_ID ni yozing, RUN_MODE=polling

# Botni polling rejimida ishga tushirish (dashboardsiz):
python run_polling.py

# Yoki to'liq (bot webhook + dashboard) — webhook uchun ngrok kerak.
```

Mantiqiy testlar (Telegramsiz):
```bash
python -m tests.test_logic
```

---

## Admin web dashboard

- Manzil: `https://SIZNING-URL/admin`  (parol = `ADMIN_PASSWORD`)
- **Reyting** — kim necha kishi qo'shgani, keyingi darajagacha qancha qolgani.
- **Chegirmalar** — barcha yutilgan kodlar; kod bo'yicha qidirish; "Band qildim" tugmasi bilan
  chegirmani ishlatilgan deb belgilash (qayta ishlatib bo'lmaydi).

---

## Muhim eslatmalar

- **Token xavfsizligi:** token chatda ochiq yuborilgan edi. Ishonch uchun BotFather'da
  `/revoke` qilib yangi token oling va uni faqat env'ga qo'ying.
- **Firibgarlikka qarshi:** tizim dublikat va o'z-o'zini qo'shishni sanamaydi; a'zo chiqib ketsa
  faol soni kamayadi. Lekin soxta akkauntlar bilan suiiste'molni to'liq to'sib bo'lmaydi —
  kerak bo'lsa "a'zo kamida N kun qolsa sanaladi" qoidasini qo'shish mumkin (ayting, qo'shaman).
- **Yutilgan kod doimiy:** daraja yutilgach, a'zo keyin chiqib ketsa ham kod bekor bo'lmaydi
  (nizolarni oldini olish uchun). Buni o'zgartirish mumkin.

## Loyiha tuzilishi

```
saxovat-bot/
├─ main.py            # deploy kirish nuqtasi (FastAPI: webhook + dashboard)
├─ run_polling.py     # lokal test uchun (polling)
├─ requirements.txt
├─ Dockerfile
├─ render.yaml        # Render blueprint
├─ .env.example
├─ app/
│  ├─ config.py       # env sozlamalari
│  ├─ db.py           # baza ulanishi
│  ├─ models.py       # Referrer, Referral, Reward
│  ├─ rewards.py      # gemifikatsiya darajalari (shu yerni tahrirlang)
│  ├─ services.py     # biznes-logika
│  ├─ bot.py          # aiogram handlerlar (/start, chat_member, ...)
│  ├─ web.py          # admin dashboard yo'nalishlari
│  └─ templates/      # login, dashboard, rewards (HTML)
└─ tests/test_logic.py
```
