"""
Deploy uchun asosiy kirish nuqtasi (webhook rejimi).
FastAPI ham admin dashboardni, ham Telegram webhookni boshqaradi.

Ishga tushirish (deploy):  uvicorn main:app --host 0.0.0.0 --port $PORT
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from starlette.middleware.sessions import SessionMiddleware

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Update

from app.config import settings
from app.db import init_db
from app import bot as botmod
from app.web import router as web_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("main")

bot = Bot(token=settings.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = botmod.build_dispatcher()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await botmod.resolve_channel(bot)
    if settings.RUN_MODE == "webhook":
        if not settings.WEBHOOK_BASE_URL:
            logger.warning("WEBHOOK_BASE_URL bo'sh — webhook o'rnatilmadi.")
        else:
            await bot.set_webhook(
                url=settings.webhook_url,
                allowed_updates=botmod.ALLOWED_UPDATES,
                drop_pending_updates=False,
            )
            logger.info("Webhook o'rnatildi: %s", settings.webhook_url)
    yield
    await bot.session.close()


app = FastAPI(title="Sahovat Shifo Bot", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=settings.SESSION_SECRET, max_age=60 * 60 * 12)
app.state.bot = bot  # web route'lar (broadcast) shu bot orqali xabar yuboradi
app.include_router(web_router)


@app.post(settings.webhook_path)
async def telegram_webhook(request: Request):
    data = await request.json()
    update = Update.model_validate(data, context={"bot": bot})
    await dp.feed_update(bot, update)
    return JSONResponse({"ok": True})


@app.get("/ping", response_class=PlainTextResponse)
async def ping():
    return "pong"
