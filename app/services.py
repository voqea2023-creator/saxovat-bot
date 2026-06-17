"""
Biznes-logika: DB bilan ishlovchi yordamchi funksiyalar.
Bot va web dashboard shular orqali ma'lumotlar bazasiga murojaat qiladi.
"""
import re
from datetime import datetime, date
from typing import Optional, Sequence

from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Referrer, Referral, Reward, Lead, Result
from . import rewards as rw


def normalize_phone(phone: Optional[str]) -> str:
    """Telefonni solishtirish uchun normallashtirish: faqat raqamlar, oxirgi 9 ta (O'zbekiston)."""
    if not phone:
        return ""
    digits = re.sub(r"\D", "", phone)
    return digits[-9:] if len(digits) >= 9 else digits


# ---------------- Referrer ----------------

async def get_or_create_referrer(
    session: AsyncSession, user_id: int, username: Optional[str], full_name: Optional[str]
) -> Referrer:
    ref = await session.get(Referrer, user_id)
    if ref is None:
        ref = Referrer(id=user_id, username=username, full_name=full_name)
        session.add(ref)
        await session.commit()
    else:
        # ism/username o'zgargan bo'lsa yangilaymiz
        changed = False
        if username and ref.username != username:
            ref.username = username
            changed = True
        if full_name and ref.full_name != full_name:
            ref.full_name = full_name
            changed = True
        if changed:
            await session.commit()
    return ref


async def set_registration(session: AsyncSession, user_id: int, name: str | None = None,
                           phone: str | None = None) -> None:
    """Ro'yxatdan o'tishda so'ralgan ism va/yoki telefonni saqlaydi."""
    ref = await session.get(Referrer, user_id)
    if ref:
        if name is not None:
            ref.reg_name = name
        if phone is not None:
            ref.phone = phone
        await session.commit()


async def is_registered(session: AsyncSession, user_id: int) -> bool:
    ref = await session.get(Referrer, user_id)
    return bool(ref and ref.reg_name and ref.phone)


async def set_referred_by(session: AsyncSession, user_id: int, referrer_id: int) -> None:
    """
    Bu foydalanuvchini kim taklif qilganini belgilaydi.
    Faqat bir marta o'rnatiladi (birinchi taklif qiluvchi yutadi), o'z-o'zini taklif sanalmaydi.
    """
    if user_id == referrer_id:
        return
    ref = await session.get(Referrer, user_id)
    if ref and ref.referred_by is None:
        # taklif qiluvchi mavjudligini tekshiramiz
        upline = await session.get(Referrer, referrer_id)
        if upline is not None:
            ref.referred_by = referrer_id
            await session.commit()


async def get_referred_by(session: AsyncSession, user_id: int) -> Optional[int]:
    ref = await session.get(Referrer, user_id)
    return ref.referred_by if ref else None


async def mark_channel_joined(session: AsyncSession, user_id: int, joined: bool = True) -> None:
    ref = await session.get(Referrer, user_id)
    if ref:
        ref.joined_channel = joined
        await session.commit()


async def set_invite_link(session: AsyncSession, user_id: int, link: str, name: str) -> None:
    ref = await session.get(Referrer, user_id)
    if ref:
        ref.invite_link = link
        ref.invite_link_name = name
        await session.commit()


async def find_referrer_by_link(session: AsyncSession, link: str) -> Optional[Referrer]:
    res = await session.execute(select(Referrer).where(Referrer.invite_link == link))
    return res.scalar_one_or_none()


async def find_referrer_by_link_name(session: AsyncSession, name: str) -> Optional[Referrer]:
    res = await session.execute(select(Referrer).where(Referrer.invite_link_name == name))
    return res.scalar_one_or_none()


# ---------------- Hisoblash ----------------

async def active_count(session: AsyncSession, referrer_id: int) -> int:
    res = await session.execute(
        select(func.count(Referral.id)).where(
            Referral.referrer_id == referrer_id, Referral.status == "active"
        )
    )
    return int(res.scalar() or 0)


async def earned_thresholds(session: AsyncSession, referrer_id: int) -> set[int]:
    res = await session.execute(
        select(Reward.tier_threshold).where(Reward.referrer_id == referrer_id)
    )
    return {int(x) for x in res.scalars().all()}


# ---------------- Qo'shilish / chiqish ----------------

async def record_join(
    session: AsyncSession,
    referrer_id: int,
    joined_user_id: int,
    joined_username: Optional[str],
    joined_full_name: Optional[str],
) -> bool:
    """
    Yangi qo'shilishni yozadi. True qaytarsa — yangi (sanaladigan) qo'shilish.
    Dublikat bo'lsa (avval qo'shilgan) — qayta faollashtiradi, lekin yangi deb sanamaydi.
    O'z-o'zini qo'shishni (referrer == joined) sanamaymiz.
    """
    if referrer_id == joined_user_id:
        return False

    res = await session.execute(
        select(Referral).where(
            Referral.referrer_id == referrer_id,
            Referral.joined_user_id == joined_user_id,
        )
    )
    existing = res.scalar_one_or_none()
    if existing:
        if existing.status != "active":
            existing.status = "active"
            existing.left_at = None
            await session.commit()
        return False

    session.add(
        Referral(
            referrer_id=referrer_id,
            joined_user_id=joined_user_id,
            joined_username=joined_username,
            joined_full_name=joined_full_name,
            status="active",
        )
    )
    await session.commit()
    return True


async def record_leave(session: AsyncSession, joined_user_id: int) -> None:
    """Foydalanuvchi kanaldan chiqsa, uning barcha 'active' yozuvlarini 'left' qiladi."""
    await session.execute(
        update(Referral)
        .where(Referral.joined_user_id == joined_user_id, Referral.status == "active")
        .values(status="left", left_at=datetime.utcnow())
    )
    await session.commit()


# ---------------- Mukofotlar ----------------

async def award_new_rewards(session: AsyncSession, referrer_id: int) -> list[Reward]:
    """
    Joriy faol a'zolar soniga qarab, hali yutilmagan darajalarni yutadi.
    Yutilgan mukofot DOIMIY saqlanadi (keyin a'zo chiqib ketsa ham bekor qilinmaydi).
    Yangi yutilgan Reward obyektlari ro'yxatini qaytaradi.
    """
    count = await active_count(session, referrer_id)
    already = await earned_thresholds(session, referrer_id)
    new_tiers = rw.newly_earned_thresholds(count, already)

    created: list[Reward] = []
    for tier in new_tiers:
        code = rw.generate_code(tier.threshold)
        reward = Reward(
            referrer_id=referrer_id,
            tier_threshold=tier.threshold,
            title=tier.title,
            code=code,
            status="earned",
        )
        session.add(reward)
        created.append(reward)
    if created:
        await session.commit()
    return created


async def list_rewards(session: AsyncSession, referrer_id: int) -> Sequence[Reward]:
    res = await session.execute(
        select(Reward).where(Reward.referrer_id == referrer_id).order_by(Reward.tier_threshold)
    )
    return res.scalars().all()


# ---------------- Dashboard uchun ----------------

async def leaderboard(session: AsyncSession, limit: int = 100):
    """Reyting: (referrer, faol_a'zolar_soni) kamayish tartibida."""
    sub = (
        select(Referral.referrer_id, func.count(Referral.id).label("cnt"))
        .where(Referral.status == "active")
        .group_by(Referral.referrer_id)
        .subquery()
    )
    res = await session.execute(
        select(Referrer, func.coalesce(sub.c.cnt, 0).label("cnt"))
        .outerjoin(sub, sub.c.referrer_id == Referrer.id)
        .order_by(func.coalesce(sub.c.cnt, 0).desc())
        .limit(limit)
    )
    return res.all()


async def all_rewards(session: AsyncSession, status: Optional[str] = None, search: Optional[str] = None):
    q = select(Reward, Referrer).join(Referrer, Reward.referrer_id == Referrer.id)
    if status:
        q = q.where(Reward.status == status)
    if search:
        like = f"%{search}%"
        q = q.where(Reward.code.ilike(like))
    q = q.order_by(Reward.earned_at.desc())
    res = await session.execute(q)
    return res.all()


async def get_reward_by_code(session: AsyncSession, code: str) -> Optional[Reward]:
    res = await session.execute(select(Reward).where(Reward.code == code))
    return res.scalar_one_or_none()


async def redeem_reward(session: AsyncSession, reward_id: int, by: str, note: str = "") -> bool:
    reward = await session.get(Reward, reward_id)
    if reward is None or reward.status != "earned":
        return False
    reward.status = "redeemed"
    reward.redeemed_at = datetime.utcnow()
    reward.redeemed_by = by
    reward.note = note or None
    await session.commit()
    return True


async def all_user_ids(session: AsyncSession) -> list[int]:
    """Botdagi barcha foydalanuvchilar (referrerlar) ID si — broadcast uchun."""
    res = await session.execute(select(Referrer.id))
    return [int(x) for x in res.scalars().all()]


async def totals(session: AsyncSession) -> dict:
    referrers = int((await session.execute(select(func.count(Referrer.id)))).scalar() or 0)
    active = int(
        (await session.execute(
            select(func.count(Referral.id)).where(Referral.status == "active")
        )).scalar() or 0
    )
    earned = int(
        (await session.execute(
            select(func.count(Reward.id)).where(Reward.status == "earned")
        )).scalar() or 0
    )
    redeemed = int(
        (await session.execute(
            select(func.count(Reward.id)).where(Reward.status == "redeemed")
        )).scalar() or 0
    )
    return {"referrers": referrers, "active_members": active, "rewards_earned": earned, "rewards_redeemed": redeemed}


# ==================== CRM (Lead / Kanban) ====================

# Kanban ustunlari (kalit, ko'rinadigan nom). Bemor "yopilmaydi" — oxirgisi doimiy kuzatuv.
STAGES = [
    ("yangi", "Yangi"),
    ("boglanildi", "Bog'lanildi"),
    ("yozildi", "Qabulga yozildi"),
    ("keldi", "Xizmat ko'rsatildi"),
    ("kuzatuv", "Kuzatuvda"),
]
STAGE_KEYS = [k for k, _ in STAGES]


async def create_lead(session: AsyncSession, name=None, phone=None, service=None,
                      status="yangi", note=None, next_contact=None,
                      telegram_id=None, source="manual") -> Lead:
    lead = Lead(
        name=name, phone=phone, phone_norm=normalize_phone(phone), service=service,
        status=status if status in STAGE_KEYS else "yangi", note=note,
        next_contact=next_contact, telegram_id=telegram_id, source=source,
    )
    session.add(lead)
    await session.commit()
    return lead


async def get_lead(session: AsyncSession, lead_id: int) -> Optional[Lead]:
    return await session.get(Lead, lead_id)


async def update_lead(session: AsyncSession, lead_id: int, **fields) -> bool:
    lead = await session.get(Lead, lead_id)
    if not lead:
        return False
    for k, v in fields.items():
        if hasattr(lead, k):
            setattr(lead, k, v)
    if "phone" in fields:
        lead.phone_norm = normalize_phone(fields.get("phone"))
    await session.commit()
    return True


async def move_lead(session: AsyncSession, lead_id: int, status: str) -> bool:
    if status not in STAGE_KEYS:
        return False
    lead = await session.get(Lead, lead_id)
    if not lead:
        return False
    lead.status = status
    await session.commit()
    return True


async def delete_lead(session: AsyncSession, lead_id: int) -> bool:
    lead = await session.get(Lead, lead_id)
    if not lead:
        return False
    await session.delete(lead)
    await session.commit()
    return True


async def leads_by_status(session: AsyncSession) -> dict:
    res = await session.execute(select(Lead).order_by(Lead.updated_at.desc()))
    leads = res.scalars().all()
    grouped = {k: [] for k in STAGE_KEYS}
    for lead in leads:
        grouped.setdefault(lead.status, []).append(lead)
    return grouped


async def seed_lead_from_user(session: AsyncSession, telegram_id: int,
                              name: Optional[str], phone: Optional[str]) -> None:
    """Botda ro'yxatdan o'tgan foydalanuvchi uchun CRM kartasi yaratadi (agar yo'q bo'lsa)."""
    res = await session.execute(select(Lead).where(Lead.telegram_id == telegram_id))
    if res.scalar_one_or_none() is not None:
        return
    norm = normalize_phone(phone)
    if norm:
        res2 = await session.execute(select(Lead).where(Lead.phone_norm == norm))
        if res2.scalar_one_or_none() is not None:
            return
    session.add(Lead(name=name, phone=phone, phone_norm=norm,
                     status="yangi", telegram_id=telegram_id, source="bot"))
    await session.commit()


# ==================== Diagnostika natijalari (Result) ====================

async def add_result(session: AsyncSession, phone: str, result_type="Natija", title=None,
                     file_id=None, file_blob=None, file_name=None, is_photo=False,
                     content_text=None, patient_name=None, uploaded_via="panel") -> Result:
    r = Result(
        phone=phone, phone_norm=normalize_phone(phone), patient_name=patient_name,
        result_type=result_type, title=title, file_id=file_id, file_blob=file_blob,
        file_name=file_name, is_photo=is_photo, content_text=content_text,
        uploaded_via=uploaded_via,
    )
    session.add(r)
    await session.commit()
    return r


async def results_by_phone(session: AsyncSession, phone: str) -> Sequence[Result]:
    norm = normalize_phone(phone)
    if not norm:
        return []
    res = await session.execute(
        select(Result).where(Result.phone_norm == norm).order_by(Result.created_at.desc())
    )
    return res.scalars().all()


async def recent_results(session: AsyncSession, limit: int = 50) -> Sequence[Result]:
    res = await session.execute(select(Result).order_by(Result.created_at.desc()).limit(limit))
    return res.scalars().all()


async def mark_result_delivered(session: AsyncSession, result_id: int) -> None:
    r = await session.get(Result, result_id)
    if r:
        r.delivered = True
        await session.commit()


async def find_referrer_by_phone(session: AsyncSession, phone: str) -> Optional[Referrer]:
    """Telefon raqami orqali botdagi foydalanuvchini topadi (normallashtirilgan solishtirish)."""
    norm = normalize_phone(phone)
    if not norm:
        return None
    res = await session.execute(select(Referrer).where(Referrer.phone.isnot(None)))
    for ref in res.scalars().all():
        if normalize_phone(ref.phone) == norm:
            return ref
    return None
