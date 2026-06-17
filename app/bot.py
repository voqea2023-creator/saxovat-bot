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
from aiogram.filters import (
    Command, CommandObject, ChatMemberUpdatedFilter, JOIN_TRANSITION, LEAVE_TRANSITION,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    Message, ChatMemberUpdated, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery,
    ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, FSInputFile, BufferedInputFile,
)

from .config import settings
from .db import SessionLocal
from . import services as svc
from . import rewards as rw

logger = logging.getLogger(__name__)
router = Router()

# Kanalning raqamli chat ID si (startupda aniqlanadi).
CHANNEL_CHAT_ID: int | None = None
# Botning @username (deep-link havola yasash uchun, startupda aniqlanadi).
BOT_USERNAME: str | None = None

# Welcome banner rasmi
WELCOME_IMAGE = os.path.join(os.path.dirname(__file__), "assets", "welcome.png")


def channel_url() -> str:
    """Kanalga obuna bo'lish havolasi (ommaviy kanal uchun t.me/username)."""
    val = settings.CHANNEL_ID.strip()
    if val.startswith("@"):
        return f"https://t.me/{val[1:]}"
    return val  # raqamli ID bo'lsa, kanal sozlamasida ommaviy havola ko'rsatilsin


def referral_link(user_id: int) -> str:
    """Foydalanuvchining shaxsiy taklif havolasi — botga deep-link."""
    uname = BOT_USERNAME or settings.BOT_USERNAME or "your_bot"
    return f"https://t.me/{uname}?start=ref{user_id}"


class Reg(StatesGroup):
    """Ro'yxatdan o'tish bosqichlari."""
    name = State()
    phone = State()


class Broadcast(StatesGroup):
    """Broadcast (hammaga xabar) bosqichlari."""
    content = State()


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
            [InlineKeyboardButton(text="📢 Kanalga obuna bo'lish", url=channel_url())],
            [InlineKeyboardButton(text="📊 Mening natijam", callback_data="my_progress")],
            [InlineKeyboardButton(text="🔗 Taklif havolam", callback_data="my_link")],
        ]
    )


def _phone_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Telefon raqamni yuborish", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
    )


# Asosiy menyu tugmalari (doimiy pastki klaviatura)
BTN_RESULTS = "📄 Diagnostika javoblarim"
BTN_PROGRESS = "📊 Mening natijam"
BTN_LINK = "🔗 Taklif havolam"


def _main_menu_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_RESULTS)],
            [KeyboardButton(text=BTN_PROGRESS), KeyboardButton(text=BTN_LINK)],
        ],
        resize_keyboard=True,
    )


# ----------------- Matnlar -----------------

def _welcome_caption(name: str) -> str:
    tiers = "\n".join(f"🎁 <b>{t.threshold} ta</b> — {t.title}" for t in rw.tiers_sorted())
    return (
        f"Assalomu alaykum, <b>{name}</b>! 👋\n\n"
        f"🏥 <b>{settings.CHANNEL_TITLE}</b> referal dasturiga xush kelibsiz.\n\n"
        "📌 <b>Ikki oddiy qadam:</b>\n"
        "1️⃣ Klinikamiz kanaliga obuna bo'ling (pastdagi tugma).\n"
        "2️⃣ Do'stlaringizni shaxsiy havolangiz orqali taklif qiling.\n\n"
        "Do'stingiz havola orqali botga kirib, kanalga obuna bo'lsa — sizga ball! "
        "Belgilangan songa yetganda chegirma yutasiz:\n\n"
        f"{tiers}\n\n"
        "Quyida — do'stlaringizga yuborish uchun tayyor post 👇"
    )


def _share_post(referral: str) -> str:
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
        f"👉 Qo'shilish: {referral}\n"
        "📞 95-515-19-50 · 91-770-05-32\n"
        "📍 Nurafshon shahar, Toshkent viloyati"
    )


async def send_welcome_sequence(bot: Bot, chat_id: int, user_id: int, name: str):
    """Welcome ketma-ketligi: avval rasm+matn (kanal tugmasi bilan), keyin (gap bilan) tayyor post."""
    link = referral_link(user_id)

    # 1-xabar: rasm + chiroyli matn + kanal/havola tugmalari
    await bot.send_chat_action(chat_id, "upload_photo")
    caption = _welcome_caption(name)
    try:
        await bot.send_photo(
            chat_id, FSInputFile(WELCOME_IMAGE), caption=caption,
            reply_markup=_progress_keyboard(),
        )
    except Exception:
        logger.warning("Welcome rasm yuborilmadi, matn yuborilmoqda")
        await bot.send_message(chat_id, caption, reply_markup=_progress_keyboard(),
                               disable_web_page_preview=True)

    # 2-xabar: gap bilan, do'stlarga yuborish uchun tayyor post (botga deep-link bilan)
    await asyncio.sleep(1.4)
    await bot.send_chat_action(chat_id, "typing")
    await asyncio.sleep(0.6)
    await bot.send_message(
        chat_id, _share_post(link),
        disable_web_page_preview=True, reply_markup=_main_menu_kb(),
    )


# ----------------- Diagnostika natijalari (yetkazish) -----------------

async def deliver_result(bot: Bot, chat_id: int, r) -> bool:
    """Bitta natijani bemorga yuboradi (matn / file_id / blob)."""
    cap = f"📄 <b>{r.result_type}</b>"
    if r.title:
        cap += f"\n{r.title}"
    try:
        if r.content_text:
            await bot.send_message(chat_id, cap + "\n\n" + r.content_text)
        elif r.file_id:
            if r.is_photo:
                await bot.send_photo(chat_id, r.file_id, caption=cap)
            else:
                await bot.send_document(chat_id, r.file_id, caption=cap)
        elif r.file_blob:
            f = BufferedInputFile(r.file_blob, filename=r.file_name or "natija")
            if r.is_photo:
                await bot.send_photo(chat_id, f, caption=cap)
            else:
                await bot.send_document(chat_id, f, caption=cap)
        else:
            return False
        return True
    except Exception:
        logger.warning("Natijani yuborib bo'lmadi: chat=%s", chat_id)
        return False


def _extract_phone(text: str) -> str | None:
    m = re.search(r"\+?\d[\d\s\-]{6,}\d", text or "")
    return m.group(0).strip() if m else None


# ----------------- /start va ro'yxatdan o'tish -----------------

@router.message(Command("start"))
async def cmd_start(message: Message, bot: Bot, state: FSMContext, command: CommandObject):
    await state.clear()
    user = message.from_user
    async with SessionLocal() as session:
        await svc.get_or_create_referrer(session, user.id, user.username, _full_name(user))
        # Deep-link payloadini o'qiymiz: "refKTKTK" -> kim taklif qilgani
        payload = (command.args or "").strip()
        if payload.startswith("ref"):
            try:
                referrer_id = int(payload[3:])
                await svc.set_referred_by(session, user.id, referrer_id)
            except ValueError:
                pass
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
        # CRM kartasini avtomatik yaratamiz
        await svc.seed_lead_from_user(session, user.id, ref.reg_name, ref.phone)
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
    link = referral_link(call.from_user.id)
    await call.message.answer(
        f"🔗 Sizning shaxsiy taklif havolangiz:\n{link}\n\n"
        "Do'stlaringizga quyidagi postni yuboring 👇",
        disable_web_page_preview=True,
    )
    await call.message.answer(_share_post(link), disable_web_page_preview=True)
    await call.answer()


# ----------------- Diagnostika javoblarim (bemor) -----------------

async def _send_results(message: Message, bot: Bot):
    from .models import Referrer
    uid = message.from_user.id
    async with SessionLocal() as session:
        ref = await session.get(Referrer, uid)
        phone = ref.phone if ref else None
        results = list(await svc.results_by_phone(session, phone)) if phone else []
    if not phone:
        await message.answer("Avval /start bosib ro'yxatdan o'ting — natijalar telefon raqamingiz orqali topiladi.")
        return
    if not results:
        await message.answer(
            "📭 Hozircha siz uchun diagnostika natijasi yo'q.\n"
            "Natija tayyor bo'lganda shu yerga avtomatik keladi."
        )
        return
    await message.answer(f"📄 Siz uchun {len(results)} ta natija topildi:")
    for r in results:
        await deliver_result(bot, message.chat.id, r)


@router.message(Command("natijalarim"))
async def cmd_results(message: Message, bot: Bot):
    await _send_results(message, bot)


@router.message(F.text == BTN_RESULTS)
async def btn_results(message: Message, bot: Bot):
    await _send_results(message, bot)


@router.message(F.text == BTN_PROGRESS)
async def btn_progress(message: Message):
    await _send_progress(message, message.from_user.id)


@router.message(F.text == BTN_LINK)
async def btn_link(message: Message):
    link = referral_link(message.from_user.id)
    await message.answer(
        f"🔗 Sizning shaxsiy taklif havolangiz:\n{link}\n\nDo'stlaringizga quyidagi postni yuboring 👇",
        disable_web_page_preview=True,
    )
    await message.answer(_share_post(link), disable_web_page_preview=True)


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


# ----------------- /myid (Telegram ID ni bilish) -----------------

@router.message(Command("myid"))
async def cmd_myid(message: Message):
    await message.answer(
        f"Sizning Telegram ID raqamingiz: <code>{message.from_user.id}</code>\n\n"
        "Admin huquqi uchun shu ID ni ADMIN_IDS sozlamasiga qo'shing."
    )


# ----------------- /broadcast (faqat admin) -----------------

def _broadcast_confirm_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(text="✅ Hammaga yuborish", callback_data="bc_send"),
            InlineKeyboardButton(text="❌ Bekor qilish", callback_data="bc_cancel"),
        ]]
    )


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext):
    if message.from_user.id not in settings.admin_ids:
        return
    await state.set_state(Broadcast.content)
    await message.answer(
        "📢 <b>Broadcast</b>\n\n"
        "Barcha foydalanuvchilarga yubormoqchi bo'lgan xabaringizni yuboring "
        "(matn, rasm, video — istalgan ko'rinishda).\n\n"
        "Bekor qilish uchun: /bekor"
    )


@router.message(Command("bekor"))
async def cmd_bekor(message: Message, state: FSMContext):
    cur = await state.get_state()
    if cur is not None:
        await state.clear()
        await message.answer("Bekor qilindi.", reply_markup=ReplyKeyboardRemove())


@router.message(Broadcast.content)
async def broadcast_content(message: Message, state: FSMContext):
    if message.text and message.text.strip() in ("/bekor", "/cancel"):
        await state.clear()
        await message.answer("Bekor qilindi.")
        return
    await state.update_data(from_chat=message.chat.id, msg_id=message.message_id)
    async with SessionLocal() as session:
        count = len(await svc.all_user_ids(session))
    await message.answer(
        f"Yuqoridagi xabar <b>{count} ta</b> foydalanuvchiga yuboriladi. Tasdiqlaysizmi?",
        reply_markup=_broadcast_confirm_kb(),
    )


@router.callback_query(F.data == "bc_cancel")
async def bc_cancel(call: CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("❌ Broadcast bekor qilindi.")
    await call.answer()


@router.callback_query(F.data == "bc_send")
async def bc_send(call: CallbackQuery, bot: Bot, state: FSMContext):
    if call.from_user.id not in settings.admin_ids:
        await call.answer("Ruxsat yo'q", show_alert=True)
        return
    data = await state.get_data()
    await state.clear()
    from_chat = data.get("from_chat")
    msg_id = data.get("msg_id")
    if not from_chat or not msg_id:
        await call.answer("Xabar topilmadi", show_alert=True)
        return

    async with SessionLocal() as session:
        ids = await svc.all_user_ids(session)

    await call.message.edit_text(f"📤 Yuborilmoqda... (0/{len(ids)})")
    sent = failed = 0
    for i, uid in enumerate(ids, 1):
        try:
            await bot.copy_message(chat_id=uid, from_chat_id=from_chat, message_id=msg_id)
            sent += 1
        except Exception:
            failed += 1
        if i % 25 == 0:
            try:
                await call.message.edit_text(f"📤 Yuborilmoqda... ({i}/{len(ids)})")
            except Exception:
                pass
        await asyncio.sleep(0.05)  # flud-limitдан saqlanish

    await call.message.edit_text(
        f"✅ Broadcast yakunlandi.\n\nYuborildi: <b>{sent}</b>\nYuborilmadi: <b>{failed}</b> "
        "(botni bloklaganlar)"
    )
    await call.answer()


# ----------------- Admin: bot orqali natija yuklash -----------------

@router.message(F.document | F.photo)
async def admin_upload_result(message: Message, bot: Bot):
    # Faqat adminlar fayl yubora oladi (telefon raqami caption'da bo'lishi shart)
    if message.from_user.id not in settings.admin_ids:
        return
    caption = (message.caption or "").strip()
    phone = _extract_phone(caption)
    if not phone:
        await message.answer(
            "📎 Natija yuklash uchun faylni telefon raqami bilan izoh (caption) qilib yuboring.\n"
            "Masalan: <code>+998901234567 UZD natijasi</code>"
        )
        return
    title = caption.replace(phone, "").strip(" |-—\n") or None

    if message.photo:
        file_id = message.photo[-1].file_id
        is_photo = True
        file_name = None
    else:
        file_id = message.document.file_id
        is_photo = False
        file_name = message.document.file_name

    async with SessionLocal() as session:
        r = await svc.add_result(
            session, phone=phone, title=title, file_id=file_id,
            is_photo=is_photo, file_name=file_name, uploaded_via="bot",
        )
        ref = await svc.find_referrer_by_phone(session, phone)

    sent = False
    if ref:
        sent = await deliver_result(bot, ref.id, r)
        if sent:
            async with SessionLocal() as session:
                await svc.mark_result_delivered(session, r.id)

    await message.answer(
        f"✅ Natija saqlandi (tel: {phone}).\n" + (
            "📤 Bemorga avtomatik yuborildi." if sent
            else "ℹ️ Bemor hali botda ro'yxatdan o'tmagan — keyin 'Diagnostika javoblarim' tugmasi orqali oladi."
        )
    )


# ----------------- chat_member: QO'SHILISH -----------------

@router.chat_member(ChatMemberUpdatedFilter(member_status_changed=JOIN_TRANSITION))
async def on_join(event: ChatMemberUpdated, bot: Bot):
    # Foydalanuvchi kanalga obuna bo'ldi. Uni KIM taklif qilganini (referred_by) topamiz
    # va o'sha taklif qiluvchiga ball beramiz.
    if CHANNEL_CHAT_ID is not None and event.chat.id != CHANNEL_CHAT_ID:
        return

    joined = event.new_chat_member.user
    if joined.is_bot:
        return

    async with SessionLocal() as session:
        await svc.mark_channel_joined(session, joined.id, True)
        referrer_id = await svc.get_referred_by(session, joined.id)
        if referrer_id is None:
            # To'g'ridan-to'g'ri kelgan yoki botda ro'yxatdan o'tmagan — ball yo'q
            return

        is_new = await svc.record_join(
            session, referrer_id, joined.id, joined.username, _full_name(joined)
        )
        if not is_new:
            return

        new_rewards = await svc.award_new_rewards(session, referrer_id)
        count = await svc.active_count(session, referrer_id)

    try:
        await bot.send_message(
            referrer_id,
            f"🎉 Sizning havolangiz orqali yangi a'zo qo'shildi! Natijangiz: <b>{count} ta</b>.",
        )
        for r in new_rewards:
            await bot.send_message(
                referrer_id,
                f"🏆 <b>Tabriklaymiz!</b> Siz yangi darajani yutib oldingiz!\n\n"
                f"🎁 {r.title}\n"
                f"🔑 Chegirma kodingiz: <code>{r.code}</code>\n\n"
                "Ushbu kodni klinikada ko'rsating.",
            )
    except Exception:
        logger.warning("Referrerga (%s) xabar yuborib bo'lmadi", referrer_id)


# ----------------- chat_member: CHIQISH -----------------

@router.chat_member(ChatMemberUpdatedFilter(member_status_changed=LEAVE_TRANSITION))
async def on_leave(event: ChatMemberUpdated):
    if CHANNEL_CHAT_ID is not None and event.chat.id != CHANNEL_CHAT_ID:
        return
    left_user = event.new_chat_member.user
    async with SessionLocal() as session:
        await svc.mark_channel_joined(session, left_user.id, False)
        await svc.record_leave(session, left_user.id)


# ----------------- Setup -----------------

def build_dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.include_router(router)
    return dp


async def resolve_channel(bot: Bot) -> None:
    """Kanal ID si va bot username ini aniqlab, modul o'zgaruvchilariga saqlaydi."""
    global CHANNEL_CHAT_ID, BOT_USERNAME
    try:
        me = await bot.get_me()
        BOT_USERNAME = me.username
        logger.info("Bot aniqlandi: @%s", BOT_USERNAME)
    except Exception:
        logger.exception("Bot username ni aniqlab bo'lmadi")
    try:
        chat = await bot.get_chat(_channel_arg())
        CHANNEL_CHAT_ID = chat.id
        logger.info("Kanal aniqlandi: %s (%s)", chat.title, chat.id)
    except Exception:
        logger.exception("Kanalni aniqlab bo'lmadi — CHANNEL_ID va bot admin huquqini tekshiring")


ALLOWED_UPDATES = ["message", "callback_query", "chat_member", "my_chat_member"]
