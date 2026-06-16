"""Admin web dashboard (FastAPI router)."""
import os
from fastapi import APIRouter, Request, Form, Depends
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import get_session
from . import services as svc
from . import rewards as rw

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

router = APIRouter()


def _is_admin(request: Request) -> bool:
    return bool(request.session.get("admin"))


def _require_admin(request: Request):
    if not _is_admin(request):
        return RedirectResponse("/admin/login", status_code=302)
    return None


# ---------------- Auth ----------------

@router.get("/", response_class=HTMLResponse)
async def root():
    return RedirectResponse("/admin")


@router.get("/admin/login", response_class=HTMLResponse)
async def login_page(request: Request, error: str = ""):
    if _is_admin(request):
        return RedirectResponse("/admin", status_code=302)
    return templates.TemplateResponse(request, "login.html", {"error": error})


@router.post("/admin/login")
async def login_submit(request: Request, password: str = Form(...)):
    if password == settings.ADMIN_PASSWORD:
        request.session["admin"] = True
        return RedirectResponse("/admin", status_code=302)
    return RedirectResponse("/admin/login?error=Parol+noto%27g%27ri", status_code=302)


@router.get("/admin/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/admin/login", status_code=302)


# ---------------- Dashboard ----------------

@router.get("/admin", response_class=HTMLResponse)
async def dashboard(request: Request, session: AsyncSession = Depends(get_session)):
    guard = _require_admin(request)
    if guard:
        return guard
    t = await svc.totals(session)
    board = await svc.leaderboard(session, limit=200)
    rows = []
    for ref, cnt in board:
        name = ref.reg_name or ref.full_name or (f"@{ref.username}" if ref.username else str(ref.id))
        rows.append({
            "name": name,
            "phone": ref.phone or "—",
            "username": ref.username,
            "id": ref.id,
            "count": cnt,
            "next": rw.next_tier(cnt),
        })
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {"totals": t, "rows": rows, "tiers": rw.tiers_sorted()},
    )


# ---------------- Chegirmalar (rewards) ----------------

@router.get("/admin/rewards", response_class=HTMLResponse)
async def rewards_page(
    request: Request,
    status: str = "",
    q: str = "",
    session: AsyncSession = Depends(get_session),
):
    guard = _require_admin(request)
    if guard:
        return guard
    data = await svc.all_rewards(session, status=status or None, search=q or None)
    items = []
    for reward, ref in data:
        name = ref.reg_name or ref.full_name or (f"@{ref.username}" if ref.username else str(ref.id))
        items.append({"r": reward, "name": name, "phone": ref.phone or "—", "username": ref.username})
    return templates.TemplateResponse(
        request,
        "rewards.html",
        {"items": items, "status": status, "q": q},
    )


@router.post("/admin/rewards/{reward_id}/redeem")
async def redeem(
    request: Request,
    reward_id: int,
    note: str = Form(""),
    session: AsyncSession = Depends(get_session),
):
    guard = _require_admin(request)
    if guard:
        return guard
    await svc.redeem_reward(session, reward_id, by="admin", note=note)
    return RedirectResponse("/admin/rewards", status_code=302)


@router.get("/healthz")
async def healthz():
    return {"ok": True}
