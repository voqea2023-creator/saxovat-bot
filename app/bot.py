"""
Telegram bot (aiogram 3).
Asosiy vazifa: gemifikatsion referral tizimi.
- /start  -> ism va telefon so'raydi, keyin unikal taklif havolasini beradi.
- chat_member yangilanishi -> kim kimni qo'shganini aniqlaydi va hisoblaydi.
- Daraja yutilganda -> chegirma kodini beradi.
"""
import os
import re
import asyncio
import logging

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command, ChatMemberUpdatedFilter, JOIN_TRANSITION, LEAVE_TRANSITION
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, ChatMemberUpdated, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, FSInputFile,
)

from .config import settings
from .db import SessionLocal
from . import services as svc
from . import rewards as rw

logger = logging.getLogger(__name__)
router = Router()

# Kanalning raqamli chat ID si (startupda aniqlanadi).
CHANNEL_CHAT_ID: int | None = None

# Welcome banner rasmi
WELCOME_IMAGE = os.path.join(os.path.dirname(__file__), "assets", "welcome.png")


class Reg(StatesGroup):
    """Ro'yxatdan o'tish bosqichlari."""
    name = State()
    phone = State()


def _channel_arg() -> int | str:
    """CHANNEL_ID ni int yoki @username sifatida qaytaradi."""
    val = settings.CHANNEL_ID.strip()
    if val.startswith("@"):
        return val
    try:
        return int(val)
    except ValueError:
        return val


def _full_name(user) -> str:
    parts = [user.first_name or "", user.last_name or ""]
    return " ".join(p for p in parts if p).strip() or (user.username or str(user.id))


def _progress_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📊 Mening natijam", callback_data="my_progress")],
            [InlineKeyboardButton(text="🔗 Havolamni qayta olish", callback_data="my_link")],
        ]
    )


def _phone_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Telefon raqamni yuborish", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


# ----------------- Matnlar -----------------

def _welcome_caption(name: str) -> str:
    tiers = "\n".join(f"🎁 <b>{t.threshold} ta</b> — {t.title}" for t in rw.tiers_sorted())
    return (
        f"Assalomu alaykum, <b>{name}</b>! 👋\n\n"
        f"🏥 <b>{settings.CHANNEL_TITLE}</b> referal dasturiga xush kelibsiz.\n\n"
        "Do'stlaringizni klinikamiz kanaliga taklif qiling va sovrinlar yutib oling:\n\n"
        f"{tiers}\n\n"
        "Quyida — do'stlaringizga yuborish uchun tayyor post 👇"
    )


def _share_post(invite_link: str) -> str:
    """Do'stlarga yuborish uchun toza, ma'noli post (forward qilishga tayyor)."""
    return (
        f"🏥 <b>{settings.CHANNEL_TITLE}</b> — sog'lig'ingiz bizning g'amxo'rligimiz\n\n"
        "Klinikamiz Telegram kanaliga qo'shiling — yillar davomida tajriba to'plagan "
        "shifokorlarimizdan doimiy yo'l-yo'riq oling:\n\n"
        "🩻 <b>UZD (UZI) mutaxassislari</b> — 20+ yil tajriba\n"
        "👶 <b>Pediatr</b> — 32+ yil tajriba\n"
        "👩 <b>Ginekolog</b> — 25+ yil tajriba\n"
        "🧠 <b>Nevropatolog</b> — 20+ yil tajriba\n"
        "🎀 <b>Mammolog</b> — ko'krak salomatligi va erta tashxis\n\n"
        "Kanalda sizni kutmoqda:\n"
        "✅ Bepul foydali maslahatlar\n"
        "🔴 Haftalik jonli efirlar (savol-javob)\n"
        "💬 Savollaringizga shifokordan video javoblar\n\n"
        f"👉 Qo'shilish: {invite_link}\n"
        "📞 95-515-19-50 · 91-770-05-32\n"
        "📍 Nurafshon shahar, Toshkent viloyati"
    )


async def ensure_invite_link(bot: Bot, user_id: int) -> str:
    """Foydalanuvchi uchun unikal taklif havolasi mavjudligini ta'minlaydi."""
    from .models import Referrer
    async with SessionLocal() as session:
        ref = await session.get(Referrer, user_id)
        if ref and ref.invite_link:
            return ref.invite_link

    name = f"ref-{user_id}"
    link_obj = await bot.create_chat_invite_link(chat_id=_channel_arg(), name=name)
    async with SessionLocal() as session:
        await svc.set_invite_link(session, user_id, link_obj.invite_link, name)
    return link_obj.invite_link


async def send_welcome_sequence(bot: Bot, chat_id: int, user_id: int, name: str):
    """Welcome ketma-ketligi: avval rasm+matn, keyin (gap bilan) tayyor post."""
    try:
        link = await ensure_invite_link(bot, user_id)
    except Exception:
        logger.exception("Invite link yaratib bo'lmadi")
        await bot.send_message(
            chat_id,
            "Kechirasiz, hozir havola yaratib bo'lmadi. Iltimos keyinroq qayta urinib ko'ring "
            "yoki klinika administratoriga murojaat qiling.",
        )
        return

    # 1-xabar: rasm + chiroyli matn
    await bot.send_chat_action(chat_id, "upload_photo")
    caption = _welcome_caption(name)
    try:
        await bot.send_photo(
            chat_id, FSInputFile(WELCOME_IMAGE), caption=caption,
            reply_markup=_progress_keyboard(),
        )
    except Exception:
        # rasm topilmasa, faqat matn yuboramiz
        logger.warning("Welcome rasm yuborilmadi, matn yuborilmoqda")
        await bot.send_message(chat_id, caption, reply_markup=_progress_keyboard(),
                               disable_web_page_preview=True)

    # 2-xabar: gap bilan, tayyor post
    await asyncio.sleep(1.4)
    await bot.send_chat_action(chat_id, "typing")
    await asyncio.sleep(0.6)
    await bot.send_message(chat_id, _share_post(link), disable_web_page_preview=True)


# ----------------- /start va ro'yxatdan o'tish -----------------

@router.message(Command("start"))
async def cmd_start(message: Message, bot: Bot, state: FSMContext):
    await state.clear()
    user = message.from_user
    async with SessionLocal() as session:
        await svc.get_or_create_referrer(session, user.id, user.username, _full_name(user))
        registered = await svc.is_registered(session, user.id)

    if registered:
        async with SessionLocal() as session:
            ref = await svc.get_or_create_referrer(session, user.id, user.username, _full_name(user))
        await send_welcome_sequence(bot, message.chat.id, user.id, ref.reg_name or _full_name(user))
        return

    # Ro'yxatdan o'tish: ism so'raymiz
    await state.set_state(Reg.name)
    await message.answer(
        f"Assalomu alaykum! 👋\n\n"
        f"🏥 <b>{settings.CHANNEL_TITLE}</b> referal dasturiga xush kelibsiz.\n\n"
        "Ro'yxatdan o'tish uchun, iltimos, <b>ism va familiyangizni</b> yozing:"
    )


@router.message(Reg.name)
async def reg_name(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    if not text or text.startswith("/") or len(text) < 2:
        await message.answer("Iltimos, ism va familiyangizni matn ko'rinishida yozing:")
        return
    async with SessionLocal() as session:
        await svc.set_registration(session, message.from_user.id, name=text[:255])
    await state.set_state(Reg.phone)
    await message.answer(
        f"Rahmat, <b>{text}</b>! 📱\n\n"
        "Endi <b>telefon raqamingizni</b> yuboring. Pastdagi tugmani bossangiz — avtomatik yuboriladi, "
        "yoki raqamni qo'lda yozing:",
        reply_markup=_phone_keyboard(),
    )


@router.message(Reg.phone)
async def reg_phone(message: Message, bot: Bot, state: FSMContext):
    phone = None
    if message.contact and message.contact.phone_number:
        phone = message.contact.phone_number
    elif message.text:
        digits = re.sub(r"[^\d+]", "", message.text)
        if len(re.sub(r"\D", "", digits)) >= 7:
            phone = digits

    if not phone:
        await message.answer(
            "Telefon raqami noto'g'ri. Iltimos, pastdagi tugma orqali yuboring yoki "
            "raqamni to'liq yozing (masalan: +998901234567):",
            reply_markup=_phone_keyboard(),
        )
        return

    user = message.from_user
    async with SessionLocal() as session:
        await svc.set_registration(session, user.id, phone=phone[:32])
        ref = await svc.get_or_create_referrer(session, user.id, user.username, _full_name(user))
    await state.clear()
    await message.answer("✅ Ro'yxatdan o'tdingiz! Rahmat.", reply_markup=ReplyKeyboardRemove())
    await send_welcome_sequence(bot, message.chat.id, user.id, ref.reg_name or _full_name(user))


# ----------------- /help -----------------

@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "ℹ️ <b>Qanday ishlaydi?</b>\n\n"
        "1. /start bosing — ism va telefoningizni kiritasiz, sizga shaxsiy havola beriladi.\n"
        "2. Havolani do'stlaringizga ulashing.\n"
        "3. Ular havola orqali kanalga qo'shilsa, avtomatik hisoblanadi.\n"
        "4. Belgilangan songa yetganda chegirma kodini olasiz.\n"
        "5. Kodni klinikada ko'rsating.\n\n"
        "📊 Natijani ko'rish: /progress"
    )


# ----------------- /progress -----------------

async def _send_progress(target: Message, user_id: int):
    async with SessionLocal() as session:
        count = await svc.active_count(session, user_id)
        rewards_list = await svc.list_rewards(session, user_id)
    nxt = rw.next_tier(count)

    lines = [f"📊 <b>Sizning natijangiz:</b> {count} ta faol a'zo\n"]
    if nxt:
        left = nxt.threshold - count
        lines.append(f"➡️ Keyingi daraja: <b>{nxt.threshold} ta</b> ({left} ta qoldi)\n   {nxt.title}\n")
    else:
        lines.append("🏆 Barcha darajalarni yutib oldingiz! Tabriklaymiz!\n")

    if rewards_list:
        lines.append("🎁 <b>Yutib olingan chegirmalaringiz:</b>")
        for r in rewards_list:
            status = "✅ ishlatilgan" if r.status == "redeemed" else "🟢 aktiv"
            lines.append(f"• <code>{r.code}</code> — {r.title} [{status}]")
    await target.answer("\n".join(lines))


@router.message(Command("progress"))
async def cmd_progress(message: Message):
    await _send_progress(message, message.from_user.id)


@router.callback_query(F.data == "my_progress")
async def cb_progress(call: CallbackQuery):
    await _send_progress(call.message, call.from_user.id)
    await call.answer()


@router.callback_query(F.data == "my_link")
async def cb_link(call: CallbackQuery, bot: Bot):
    link = await ensure_invite_link(bot, call.from_user.id)
    await call.message.answer(_share_post(link), disable_web_page_preview=True)
    await call.answer()


# ----------------- /stats (faqat admin) -----------------

@router.message(Command("stats"))
async def cmd_stats(message: Message):
    if message.from_user.id not in settings.admin_ids:
        return
    async with SessionLocal() as session:
        t = await svc.totals(session)
        board = await svc.leaderboard(session, limit=10)
    lines = [
        "📈 <b>Umumiy statistika</b>",
        f"Referrerlar: {t['referrers']}",
        f"Faol qo'shilganlar: {t['active_members']}",
        f"Aktiv chegirmalar: {t['rewards_earned']}",
        f"Ishlatilgan chegirmalar: {t['rewards_redeemed']}",
        "",
        "🏆 <b>TOP-10:</b>",
    ]
    for i, (ref, cnt) in enumerate(board, 1):
        name = ref.reg_name or ref.full_name or (f"@{ref.username}" if ref.username else str(ref.id))
        lines.append(f"{i}. {name} — {cnt} ta")
    await message.answer("\n".join(lines))


# ----------------- chat_member: QO'SHILISH -----------------

@router.chat_member(ChatMemberUpdatedFilter(member_status_changed=JOIN_TRANSITION))
async def on_join(event: ChatMemberUpdated, bot: Bot):
    if CHANNEL_CHAT_ID is not None and event.chat.id != CHANNEL_CHAT_ID:
        return

    invite = event.invite_link
    if invite is None:
        return

    joined = event.new_chat_member.user
    if joined.is_bot:
        return

    async with SessionLocal() as session:
        referrer = await svc.find_referrer_by_link(session, invite.invite_link)
        if referrer is None and invite.name:
            referrer = await svc.find_referrer_by_link_name(session, invite.name)
        if referrer is None:
            logger.info("Noma'lum havola orqali qo'shilish: %s", invite.invite_link)
            return

        is_new = await svc.record_join(
            session, referrer.id, joined.id, joined.username, _full_name(joined)
        )
        if not is_new:
            return

        new_rewards = await svc.award_new_rewards(session, referrer.id)
        count = await svc.active_count(session, referrer.id)

    try:
        await bot.send_message(
            referrer.id,
            f"🎉 Yangi a'zo qo'shildi! Sizning natijangiz: <b>{count} ta</b>.",
        )
        for r in new_rewards:
            await bot.send_message(
                referrer.id,
                f"🏆 <b>Tabriklaymiz!</b> Siz yangi darajani yutib oldingiz!\n\n"
                f"🎁 {r.title}\n"
                f"🔑 Chegirma kodingiz: <code>{r.code}</code>\n\n"
                "Ushbu kodni klinikada ko'rsating.",
            )
    except Exception:
        logger.warning("Referrerga (%s) xabar yuborib bo'lmadi", referrer.id)


# ----------------- chat_member: CHIQISH -----------------

@router.chat_member(ChatMemberUpdatedFilter(member_status_changed=LEAVE_TRANSITION))
async def on_leave(event: ChatMemberUpdated):
    if CHANNEL_CHAT_ID is not None and event.chat.id != CHANNEL_CHAT_ID:
        return
    left_user = event.new_chat_member.user
    async with SessionLocal() as session:
        await svc.record_leave(session, left_user.id)


# ----------------- Setup -----------------

def build_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.include_router(router)
    return dp


async def resolve_channel(bot: Bot) -> None:
    """Kanalning raqamli ID sini aniqlab, modul o'zgaruvchisiga saqlaydi."""
    global CHANNEL_CHAT_ID
    try:
        chat = await bot.get_chat(_channel_arg())
        CHANNEL_CHAT_ID = chat.id
        logger.info("Kanal aniqlandi: %s (%s)", chat.title, chat.id)
    except Exception:
        logger.exception("Kanalni aniqlab bo'lmadi — CHANNEL_ID va bot admin huquqini tekshiring")


ALLOWED_UPDATES = ["message", "callback_query", "chat_member", "my_chat_member"]
