"""
Lokal test uchun: botni polling rejimida ishga tushiradi (web dashboardsiz).
Tez sinash uchun qulay. Deployда esa main:app (webhook) ishlatiladi.

Ishga tushirish:  python run_polling.py
"""
import asyncio
import logging

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from app.config import settings
from app.db import init_db
from app import bot as botmod

logging.basicConfig(level=logging.INFO)


async def main():
    await init_db()
    bot = Bot(token=settings.BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = botmod.build_dispatcher()
    await botmod.resolve_channel(bot)
    await bot.delete_webhook(drop_pending_updates=False)
    print("Bot polling rejimida ishga tushdi. To'xtatish uchun Ctrl+C")
    await dp.start_polling(bot, allowed_updates=botmod.ALLOWED_UPDATES)


if __name__ == "__main__":
    asyncio.run(main())
