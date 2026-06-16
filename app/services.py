"""
Biznes-logika: DB bilan ishlovchi yordamchi funksiyalar.
Bot va web dashboard shular orqali ma'lumotlar bazasiga murojaat qiladi.
"""
from datetime import datetime
from typing import Optional, Sequence

from sqlalchemy import select, func, update
from sqlalchemy.ext.asyncio import AsyncSession

from .models import Referrer, Referral, Reward
from . import rewards as rw


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
