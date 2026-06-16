"""
Reward logikasi va DB servislari uchun testlar.
Telegram API ga ulanmaydi — faqat ichki logikani tekshiradi.

Ishga tushirish:  python -m tests.test_logic
"""
import asyncio
import os
import tempfile

# Test uchun alohida vaqtinchalik SQLite baza
DB_PATH = os.path.join(tempfile.gettempdir(), "saxovat_test_data.db")
os.environ.setdefault("BOT_TOKEN", "TEST:TOKEN")
os.environ.setdefault("CHANNEL_ID", "@test_channel")
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{DB_PATH}")

from app import rewards as rw
from app.db import init_db, SessionLocal, engine
from app import services as svc


def test_tier_logic():
    assert rw.next_tier(0).threshold == 5
    assert rw.next_tier(4).threshold == 5
    assert rw.next_tier(5).threshold == 10
    assert rw.next_tier(10).threshold == 20
    assert rw.next_tier(20) is None

    # 0 ta yutilgan, 12 a'zo -> 5 va 10 yutiladi (20 emas)
    earned = rw.newly_earned_thresholds(12, set())
    assert [t.threshold for t in earned] == [5, 10]

    # 5 allaqachon yutilgan, 12 a'zo -> faqat 10
    earned2 = rw.newly_earned_thresholds(12, {5})
    assert [t.threshold for t in earned2] == [10]

    # 22 a'zo, hech narsa yutilmagan -> 5,10,20
    earned3 = rw.newly_earned_thresholds(22, set())
    assert [t.threshold for t in earned3] == [5, 10, 20]

    code = rw.generate_code(10)
    assert code.startswith("SAXOVAT-10-")
    print("OK: tier logikasi")


async def test_services():
    # toza baza
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    await init_db()

    REFERRER = 1000

    async with SessionLocal() as s:
        await svc.get_or_create_referrer(s, REFERRER, "ali", "Ali Valiyev")
        await svc.set_invite_link(s, REFERRER, "https://t.me/+abc123", "ref-1000")

    # link orqali topish
    async with SessionLocal() as s:
        found = await svc.find_referrer_by_link(s, "https://t.me/+abc123")
        assert found is not None and found.id == REFERRER

    # o'z-o'zini qo'shish sanalmaydi
    async with SessionLocal() as s:
        is_new = await svc.record_join(s, REFERRER, REFERRER, None, "self")
        assert is_new is False

    # 5 ta turli odam qo'shamiz
    async with SessionLocal() as s:
        for uid in range(2001, 2006):
            assert await svc.record_join(s, REFERRER, uid, f"user{uid}", f"User {uid}") is True
        # dublikat -> False
        assert await svc.record_join(s, REFERRER, 2001, "user2001", "User 2001") is False
        cnt = await svc.active_count(s, REFERRER)
        assert cnt == 5, cnt

    # 5-darajali mukofot yutilishi kerak
    async with SessionLocal() as s:
        new = await svc.award_new_rewards(s, REFERRER)
        assert len(new) == 1 and new[0].tier_threshold == 5
        # qayta chaqirilsa — yangi mukofot yo'q
        again = await svc.award_new_rewards(s, REFERRER)
        assert again == []

    # yana 5 ta -> 10 a'zo -> 10-daraja
    async with SessionLocal() as s:
        for uid in range(2006, 2011):
            await svc.record_join(s, REFERRER, uid, f"user{uid}", f"User {uid}")
        new = await svc.award_new_rewards(s, REFERRER)
        assert len(new) == 1 and new[0].tier_threshold == 10

    # bittasi chiqib ketsa, faol soni kamayadi, lekin yutilgan mukofot saqlanadi
    async with SessionLocal() as s:
        await svc.record_leave(s, 2002)
        cnt = await svc.active_count(s, REFERRER)
        assert cnt == 9, cnt
        rewards_list = await svc.list_rewards(s, REFERRER)
        assert {r.tier_threshold for r in rewards_list} == {5, 10}

    # chegirmani band qilish
    async with SessionLocal() as s:
        rewards_list = await svc.list_rewards(s, REFERRER)
        rid = rewards_list[0].id
        ok = await svc.redeem_reward(s, rid, by="admin", note="klinikada")
        assert ok is True
        # ikkinchi marta band qilib bo'lmaydi
        ok2 = await svc.redeem_reward(s, rid, by="admin")
        assert ok2 is False

    # totals
    async with SessionLocal() as s:
        t = await svc.totals(s)
        assert t["referrers"] == 1
        assert t["active_members"] == 9
        assert t["rewards_redeemed"] == 1

    await engine.dispose()
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
    print("OK: servis logikasi (qo'shish, dublikat, daraja, chiqish, band qilish)")


if __name__ == "__main__":
    test_tier_logic()
    asyncio.run(test_services())
    print("\nBARCHA TESTLAR MUVAFFAQIYATLI ✅")
