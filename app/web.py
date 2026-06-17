"""Admin web dashboard (FastAPI router)."""
import os
import asyncio
from datetime import datetime, date
from fastapi import APIRouter, Request, Form, Depends, UploadFile, File, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from aiogram.types import BufferedInputFile

from .config import settings
from .db import get_session, SessionLocal
from . import services as svc
from . import rewards as rw
from . import bot as botmod
from .models import Result

# Broadcast holati (panelда ko'rsatish uchun, xotirada saqlanadi)
BROADCAST_STATUS = {"running": False, "sent": 0, "failed": 0, "total": 0, "finished_at": None}

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


# ---------------- Broadcast (hammaga xabar) ----------------

async def _run_broadcast(bot, ids, text, image_bytes, image_name):
    """Fonda barcha foydalanuvchilarga xabar yuboradi."""
    BROADCAST_STATUS.update(running=True, sent=0, failed=0, total=len(ids), finished_at=None)
    file_id = None
    for uid in ids:
        try:
            if image_bytes:
                if file_id:
                    await bot.send_photo(uid, file_id, caption=text or None)
                else:
                    msg = await bot.send_photo(
                        uid, BufferedInputFile(image_bytes, filename=image_name or "image.jpg"),
                        caption=text or None,
                    )
                    if msg.photo:
                        file_id = msg.photo[-1].file_id  # qayta yuklamaslik uchun file_id ni saqlaymiz
            else:
                await bot.send_message(uid, text)
            BROADCAST_STATUS["sent"] += 1
        except Exception:
            BROADCAST_STATUS["failed"] += 1
        await asyncio.sleep(0.05)  # flud-limitdan saqlanish
    BROADCAST_STATUS.update(running=False, finished_at=datetime.utcnow().strftime("%Y-%m-%d %H:%M"))


@router.get("/admin/broadcast", response_class=HTMLResponse)
async def broadcast_page(request: Request, started: str = "", error: str = "",
                         session: AsyncSession = Depends(get_session)):
    guard = _require_admin(request)
    if guard:
        return guard
    count = len(await svc.all_user_ids(session))
    return templates.TemplateResponse(
        request, "broadcast.html",
        {"count": count, "status": BROADCAST_STATUS, "started": started, "error": error},
    )


@router.post("/admin/broadcast")
async def broadcast_send(
    request: Request,
    background: BackgroundTasks,
    text: str = Form(""),
    image: UploadFile = File(None),
    session: AsyncSession = Depends(get_session),
):
    guard = _require_admin(request)
    if guard:
        return guard
    if BROADCAST_STATUS["running"]:
        return RedirectResponse("/admin/broadcast?error=Hozir+yuborish+ketmoqda", status_code=302)

    text = (text or "").strip()
    image_bytes = None
    image_name = None
    if image is not None and image.filename:
        image_bytes = await image.read()
        image_name = image.filename
    if not text and not image_bytes:
        return RedirectResponse("/admin/broadcast?error=Matn+yoki+rasm+kiriting", status_code=302)

    ids = await svc.all_user_ids(session)
    bot = request.app.state.bot
    background.add_task(_run_broadcast, bot, ids, text, image_bytes, image_name)
    return RedirectResponse("/admin/broadcast?started=1", status_code=302)


# ---------------- CRM (Kanban) ----------------

def _parse_date(s: str):
    s = (s or "").strip()
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


@router.get("/admin/crm", response_class=HTMLResponse)
async def crm_page(request: Request, session: AsyncSession = Depends(get_session)):
    guard = _require_admin(request)
    if guard:
        return guard
    grouped = await svc.leads_by_status(session)
    return templates.TemplateResponse(
        request, "crm.html",
        {"stages": svc.STAGES, "grouped": grouped, "today": date.today()},
    )


@router.post("/admin/crm/add")
async def crm_add(request: Request, name: str = Form(""), phone: str = Form(""),
                  service: str = Form(""), status: str = Form("yangi"),
                  note: str = Form(""), next_contact: str = Form(""),
                  session: AsyncSession = Depends(get_session)):
    guard = _require_admin(request)
    if guard:
        return guard
    await svc.create_lead(
        session, name=name.strip() or None, phone=phone.strip() or None,
        service=service.strip() or None, status=status, note=note.strip() or None,
        next_contact=_parse_date(next_contact),
    )
    return RedirectResponse("/admin/crm", status_code=302)


@router.post("/admin/crm/{lead_id}/move")
async def crm_move(request: Request, lead_id: int, session: AsyncSession = Depends(get_session)):
    if not _is_admin(request):
        return JSONResponse({"ok": False}, status_code=403)
    data = await request.json()
    ok = await svc.move_lead(session, lead_id, data.get("status", ""))
    return JSONResponse({"ok": ok})


@router.get("/admin/crm/{lead_id}", response_class=HTMLResponse)
async def crm_edit_page(request: Request, lead_id: int, session: AsyncSession = Depends(get_session)):
    guard = _require_admin(request)
    if guard:
        return guard
    lead = await svc.get_lead(session, lead_id)
    if not lead:
        return RedirectResponse("/admin/crm", status_code=302)
    return templates.TemplateResponse(request, "crm_edit.html", {"lead": lead, "stages": svc.STAGES})


@router.post("/admin/crm/{lead_id}/edit")
async def crm_edit(request: Request, lead_id: int, name: str = Form(""), phone: str = Form(""),
                   service: str = Form(""), status: str = Form("yangi"),
                   note: str = Form(""), next_contact: str = Form(""),
                   session: AsyncSession = Depends(get_session)):
    guard = _require_admin(request)
    if guard:
        return guard
    await svc.update_lead(
        session, lead_id, name=name.strip() or None, phone=phone.strip() or None,
        service=service.strip() or None, status=status, note=note.strip() or None,
        next_contact=_parse_date(next_contact),
    )
    return RedirectResponse("/admin/crm", status_code=302)


@router.post("/admin/crm/{lead_id}/delete")
async def crm_delete(request: Request, lead_id: int, session: AsyncSession = Depends(get_session)):
    guard = _require_admin(request)
    if guard:
        return guard
    await svc.delete_lead(session, lead_id)
    return RedirectResponse("/admin/crm", status_code=302)


# ---------------- Diagnostika natijalari (yuklash) ----------------

async def _notify_result(bot, result_id: int):
    """Natija egasini (telefon orqali) topib, botda avtomatik yuboradi."""
    async with SessionLocal() as session:
        r = await session.get(Result, result_id)
        if not r:
            return
        ref = await svc.find_referrer_by_phone(session, r.phone)
    if ref:
        ok = await botmod.deliver_result(bot, ref.id, r)
        if ok:
            async with SessionLocal() as session:
                await svc.mark_result_delivered(session, result_id)


@router.get("/admin/results", response_class=HTMLResponse)
async def results_page(request: Request, started: str = "", error: str = "",
                       session: AsyncSession = Depends(get_session)):
    guard = _require_admin(request)
    if guard:
        return guard
    items = await svc.recent_results(session, 50)
    return templates.TemplateResponse(
        request, "results.html", {"items": items, "started": started, "error": error},
    )


@router.post("/admin/results/upload")
async def results_upload(request: Request, background: BackgroundTasks,
                         phone: str = Form(""), result_type: str = Form("Natija"),
                         title: str = Form(""), text: str = Form(""),
                         file: UploadFile = File(None),
                         session: AsyncSession = Depends(get_session)):
    guard = _require_admin(request)
    if guard:
        return guard
    phone = phone.strip()
    if not phone:
        return RedirectResponse("/admin/results?error=Telefon+raqami+shart", status_code=302)
    text = text.strip()
    file_blob = None
    file_name = None
    is_photo = False
    if file is not None and file.filename:
        file_blob = await file.read()
        file_name = file.filename
        is_photo = (file.content_type or "").startswith("image/")
    if not text and not file_blob:
        return RedirectResponse("/admin/results?error=Fayl+yoki+matn+kiriting", status_code=302)

    r = await svc.add_result(
        session, phone=phone, result_type=result_type.strip() or "Natija",
        title=title.strip() or None, file_blob=file_blob, file_name=file_name,
        is_photo=is_photo, content_text=text or None, uploaded_via="panel",
    )
    background.add_task(_notify_result, request.app.state.bot, r.id)
    return RedirectResponse("/admin/results?started=1", status_code=302)


@router.get("/healthz")
async def healthz():
    return {"ok": True}
