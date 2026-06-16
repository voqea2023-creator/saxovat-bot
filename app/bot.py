"""
Telegram bot (aiogram 3).
Asosiy vazifa: gemifikatsion referral tizimi.
- /start  -> foydalanuvchini ro'yxatga oladi, unikal taklif havolasini beradi.
- chat_member yangilanishi -> kim kimni qo'shganini aniqlaydi va hisoblaydi.
- Daraja yutilganda -> chegirma kodini beradi.
"""
import logging
from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command, ChatMemberUpdatedFilter, JOIN_TRANSITION, LEAVE_TRANSITION
from aiogram.types import (
    Message, ChatMemberUpdated, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery,
)

from .config import settings
from .db import SessionLocal
from . import services as svc
from . import rewards as rw

logger = logging.getLogger(__name__)
router = Router()

# Kanalning raqamli chat ID si (startupda aniqlanadi).
CHANNEL_CHAT_ID: int | None = None


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


def _share_post(invite_link: str) -> str:
    """Foydalanuvchi tarqatadigan tayyor post matni."""
    return (
        f"🏥 <b>{settings.CHANNEL_TITLE}</b> klinikasi kanaliga qo'shiling!\n\n"
        "👶 Pediatr · 🧠 Nevropatolog · 🤰 Ginekolog · 🎀 Mammolog\n"
        "Bepul maslahatlar, jonli efirlar va savol-javoblar.\n\n"
        f"👉 Qo'shilish: {invite_link}"
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


# ----------------- /start -----------------

@router.message(Command("start"))
async def cmd_start(message: Message, bot: Bot):
    user = message.from_user
    async with SessionLocal() as session:
        await svc.get_or_create_referrer(session, user.id, user.username, _full_name(user))

    try:
        link = await ensure_invite_link(bot, user.id)
    except Exception as e:  # bot admin emasligi yoki kanal noto'g'ri
        logger.exception("Invite link yaratib bo'lmadi")
        await message.answer(
            "Kechirasiz, hozir havola yaratib bo'lmadi. Iltimos keyinroq qayta urinib ko'ring "
            "yoki klinika administratoriga murojaat qiling."
        )
        return

    tiers_text = "\n".join(
        f"• <b>{t.threshold} ta</b> — {t.title}" for t in rw.tiers_sorted()
    )

    text = (
        f"Assalomu alaykum, <b>{_full_name(user)}</b>! 👋\n\n"
        f"<b>{settings.CHANNEL_TITLE}</b> referal dasturiga xush kelibsiz.\n"
        "Do'stlaringizni kanalimizga qo'shing va chegirmalar yutib oling!\n\n"
        "🎁 <b>Mukofotlar:</b>\n"
        f"{tiers_text}\n\n"
        "🔗 <b>Sizning shaxsiy havolangiz:</b>\n"
        f"{link}\n\n"
        "Quyidagi tayyor postni do'stlaringizga yuboring 👇"
    )
    await message.answer(text, reply_markup=_progress_keyboard(), disable_web_page_preview=True)
    await message.answer(_share_post(link), disable_web_page_preview=True)


# ----------------- /help -----------------

@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "ℹ️ <b>Qanday ishlaydi?</b>\n\n"
        "1. /start bosing — sizga shaxsiy taklif havolasi beriladi.\n"
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
    await call.message.answer(f"🔗 Sizning havolangiz:\n{link}", disable_web_page_preview=True)
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
        name = ref.full_name or (f"@{ref.username}" if ref.username else str(ref.id))
        lines.append(f"{i}. {name} — {cnt} ta")
    await message.answer("\n".join(lines))


# ----------------- chat_member: QO'SHILISH -----------------

@router.chat_member(ChatMemberUpdatedFilter(member_status_changed=JOIN_TRANSITION))
async def on_join(event: ChatMemberUpdated, bot: Bot):
    # Faqat bizning kanalimiz
    if CHANNEL_CHAT_ID is not None and event.chat.id != CHANNEL_CHAT_ID:
        return

    invite = event.invite_link
    if invite is None:
        # Havolasiz qo'shilgan (to'g'ridan-to'g'ri) — referralga sanalmaydi
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

    # Referrerga xabar
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
