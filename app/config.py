"""
Konfiguratsiya. Barcha sozlamalar muhit (environment) o'zgaruvchilaridan olinadi.
Lokal ishlash uchun .env faylidan o'qiydi (.env.example dan nusxa oling).
"""
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Telegram ---
    # BotFather bergan token. HECH QACHON kodga yozilmaydi, faqat env orqali keladi.
    BOT_TOKEN: str

    # Kanal ID si. Raqamli (-100xxxxxxxxxx) yoki ommaviy kanal uchun "@username".
    # Bot shu kanalga ADMIN bo'lishi va "Taklif havolalari" huquqiga ega bo'lishi shart.
    CHANNEL_ID: str

    # Ko'rsatish uchun kanal nomi (ixtiyoriy), masalan "Sahovat Shifo".
    CHANNEL_TITLE: str = "Sahovat Shifo"

    # Bot @username (ixtiyoriy zaxira). Bo'sh bo'lsa, startupda get_me orqali avtomatik aniqlanadi.
    BOT_USERNAME: str = ""

    # Bot ichida admin hisoblanadigan Telegram user ID lar (vergul bilan).
    ADMIN_IDS: str = ""

    # --- Web / deploy ---
    # Webhook uchun tashqi URL (deploydan keyin to'ldiriladi), masalan https://xxx.onrender.com
    WEBHOOK_BASE_URL: str = ""

    # Webhook yo'lining maxfiy qismi (URL ni topib bo'lmasligi uchun).
    WEBHOOK_SECRET: str = "change-me-webhook-secret"

    # Ishlash rejimi: "webhook" (deploy uchun) yoki "polling" (lokal test uchun).
    RUN_MODE: str = "webhook"

    # Admin dashboard paroli.
    ADMIN_PASSWORD: str = "change-me-admin-password"

    # Cookie/sessiyani imzolash kaliti (tasodifiy uzun satr qo'ying).
    SESSION_SECRET: str = "change-me-session-secret"

    # Ma'lumotlar bazasi. Lokal: SQLite. Deploy (Postgres): postgresql+asyncpg://...
    DATABASE_URL: str = "sqlite+aiosqlite:///./data.db"

    @property
    def admin_ids(self) -> List[int]:
        out = []
        for part in self.ADMIN_IDS.replace(" ", "").split(","):
            if part:
                try:
                    out.append(int(part))
                except ValueError:
                    pass
        return out

    @property
    def webhook_path(self) -> str:
        return f"/webhook/{self.WEBHOOK_SECRET}"

    @property
    def webhook_url(self) -> str:
        return f"{self.WEBHOOK_BASE_URL.rstrip('/')}{self.webhook_path}"


settings = Settings()
