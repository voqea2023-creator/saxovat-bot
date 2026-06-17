"""SQLAlchemy modellar."""
from datetime import datetime, date
from sqlalchemy import (
    BigInteger, String, DateTime, Date, ForeignKey, Integer, UniqueConstraint,
    LargeBinary, Boolean, Text, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


class Referrer(Base):
    """Taklif qiluvchi foydalanuvchi (botda /start bosgan odam)."""
    __tablename__ = "referrers"

    # Telegram user ID = birlamchi kalit.
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Ro'yxatdan o'tishda so'raladigan ism va telefon (dashboardда ko'rinadi).
    reg_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Bu foydalanuvchini kim taklif qilgan (piramida daraxti uchun). NULL = to'g'ridan-to'g'ri kelgan.
    referred_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # Kanalga obuna bo'lganmi (ball shu paytda beriladi).
    joined_channel: Mapped[bool] = mapped_column(default=False)

    # Shu odamga biriktirilgan unikal taklif havolasi.
    invite_link: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True)
    invite_link_name: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    referrals: Mapped[list["Referral"]] = relationship(back_populates="referrer", cascade="all, delete-orphan")
    rewards: Mapped[list["Reward"]] = relationship(back_populates="referrer", cascade="all, delete-orphan")


class Referral(Base):
    """Bitta qo'shilish hodisasi: kim, kimni taklif havolasi orqali qo'shgani."""
    __tablename__ = "referrals"
    __table_args__ = (
        # Bir foydalanuvchi bitta referrer uchun faqat bir marta sanaladi (dublikatga qarshi).
        UniqueConstraint("referrer_id", "joined_user_id", name="uq_referrer_joined"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    referrer_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("referrers.id"))

    joined_user_id: Mapped[int] = mapped_column(BigInteger)
    joined_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    joined_full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # "active" = hozir kanalda, "left" = chiqib ketgan.
    status: Mapped[str] = mapped_column(String(16), default="active")

    joined_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    left_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    referrer: Mapped["Referrer"] = relationship(back_populates="referrals")


class Reward(Base):
    """Yutib olingan chegirma (gemifikatsiya darajasi)."""
    __tablename__ = "rewards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    referrer_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("referrers.id"))

    tier_threshold: Mapped[int] = mapped_column(Integer)   # 5, 10, 20 ...
    title: Mapped[str] = mapped_column(String(255))
    code: Mapped[str] = mapped_column(String(32), unique=True)

    # "earned" = yutilgan, "redeemed" = klinikada ishlatilgan, "cancelled" = bekor qilingan.
    status: Mapped[str] = mapped_column(String(16), default="earned")

    earned_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    redeemed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    note: Mapped[str | None] = mapped_column(String(255), nullable=True)

    referrer: Mapped["Referrer"] = relationship(back_populates="rewards")


class Lead(Base):
    """CRM kartasi (bemor/mijoz). Kanban ustunlari = status."""
    __tablename__ = "leads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    phone_norm: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    service: Mapped[str | None] = mapped_column(String(255), nullable=True)   # qaysi xizmat
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Kanban ustuni: yangi / boglanildi / yozildi / keldi / kuzatuv
    status: Mapped[str] = mapped_column(String(32), default="yangi", index=True)
    next_contact: Mapped[date | None] = mapped_column(Date, nullable=True)  # keyingi aloqa sanasi

    telegram_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)  # botdagi user (bo'lsa)
    source: Mapped[str] = mapped_column(String(32), default="manual")  # manual / bot

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class Result(Base):
    """Diagnostika natijasi / doktor xulosasi. Telefon orqali bemorga biriktiriladi."""
    __tablename__ = "results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    phone: Mapped[str] = mapped_column(String(32))
    phone_norm: Mapped[str] = mapped_column(String(32), index=True)
    patient_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    result_type: Mapped[str] = mapped_column(String(64), default="Natija")  # Tahlil/UZD/Doktor xulosasi
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Fayl: bot orqali kelса file_id, panel orqali kelса blob. Yoki matnli natija.
    file_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    file_blob: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_photo: Mapped[bool] = mapped_column(Boolean, default=False)
    content_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    delivered: Mapped[bool] = mapped_column(Boolean, default=False)
    uploaded_via: Mapped[str] = mapped_column(String(16), default="panel")  # panel / bot
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
