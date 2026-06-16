"""
Gemifikatsiya darajalari (tiers) va mukofot logikasi.

YANGI SHARTLAR QO'SHISH: faqat shu TIERS ro'yxatini tahrirlang.
Har bir daraja:  threshold (necha kishi), title (chegirma matni).
"""
import secrets
from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class Tier:
    threshold: int
    title: str


# --- Klinikaning gemifikatsiya shartlari ---
TIERS: List[Tier] = [
    Tier(
        threshold=5,
        title="Doktor ko'rigiga 50% chegirma (bir martalik)",
    ),
    Tier(
        threshold=10,
        title="Doktor ko'rigiga 100% chegirma (bir martalik) + bepul umumiy qon tahlili "
              "va qondagi qand miqdori",
    ),
    Tier(
        threshold=20,
        title="2 ta doktor ko'rigiga 100% chegirma + bepul umumiy qon tahlili "
              "va qondagi qand miqdori",
    ),
]

# Doktorlar ro'yxati (xabarlarda ko'rsatish uchun)
DOCTORS = ["pediatr", "nevropatolog", "ginekolog", "mammolog"]


def tiers_sorted() -> List[Tier]:
    return sorted(TIERS, key=lambda t: t.threshold)


def next_tier(active_count: int) -> Tier | None:
    """Keyingi yutib olinadigan daraja (yoki None — hammasi yutilgan)."""
    for t in tiers_sorted():
        if active_count < t.threshold:
            return t
    return None


def newly_earned_thresholds(active_count: int, already_earned: set[int]) -> List[Tier]:
    """
    Joriy faol a'zolar soniga ko'ra, ALdin yutilmagan, lekin endi yutilgan darajalar.
    """
    result = []
    for t in tiers_sorted():
        if active_count >= t.threshold and t.threshold not in already_earned:
            result.append(t)
    return result


def generate_code(threshold: int) -> str:
    """Klinikada ko'rsatiladigan unikal chegirma kodi, masalan: SAXOVAT-10-3F9A2B."""
    rnd = secrets.token_hex(3).upper()
    return f"SAXOVAT-{threshold}-{rnd}"
