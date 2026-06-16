"""Ma'lumotlar bazasi: engine, sessiya va jadvallarni yaratish."""
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase

from .config import settings


class Base(DeclarativeBase):
    pass


def _normalize_db_url(url: str) -> str:
    """
    Ko'p hosting platformalari (Render, Railway) Postgres URL ni 'postgres://' yoki
    'postgresql://' ko'rinishida beradi. SQLAlchemy + asyncpg uchun
    'postgresql+asyncpg://' kerak. Shuni avtomatik tuzatamiz.
    """
    if url.startswith("postgres://"):
        url = "postgresql+asyncpg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+asyncpg://" + url[len("postgresql://"):]
    # asyncpg 'sslmode' query parametrini tushunmaydi — olib tashlaymiz (kerak bo'lsa ssl=require ishlaydi)
    if "+asyncpg" in url and "sslmode=" in url:
        import re
        url = re.sub(r"[?&]sslmode=[^&]+", "", url)
    return url


DB_URL = _normalize_db_url(settings.DATABASE_URL)

# SQLite uchun check_same_thread kerak emas (async drayver), Postgres uchun ham bir xil chaqiriladi.
engine = create_async_engine(DB_URL, echo=False, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    # Modellar import qilingan bo'lishi shart (jadvallar metadata ga ro'yxatdan o'tishi uchun).
    from . import models  # noqa: F401
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_session() -> AsyncSession:
    async with SessionLocal() as session:
        yield session
