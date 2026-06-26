from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import BASE_URL
from app.database import get_session
from app.queries import find_link, list_links, summary_stats

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

@router.get("/")
async def home(request: Request):
    return templates.TemplateResponse(request, "index.html")

@router.get("/dashboard")
async def dashboard_page(request: Request, session: AsyncSession = Depends(get_session)):
    stats = await summary_stats(session)
    top = await list_links(session, limit=5, offset=0, sort="clicks", min_clicks=1)
    return templates.TemplateResponse(
        request, "dashboard.html", {"stats": stats, "top": top}
    )

@router.get("/stats/{code}")
async def stats_page(request: Request, code: str, session: AsyncSession = Depends(get_session)):
    link = await find_link(session, code)
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    expired = link.expires_at is not None and link.expires_at <= now
    short_path = link.custom_alias or link.short_code

    return templates.TemplateResponse(
        request,
        "stats.html",
        {
            "link": link,
            "short_url": f"{BASE_URL}/{short_path}",
            "short_path": short_path,
            "base_url": BASE_URL,
            "expired": expired,
        },
    )
