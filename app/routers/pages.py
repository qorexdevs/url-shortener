from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import BASE_URL
from app.database import get_session
from app.models import Link

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

@router.get("/")
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@router.get("/stats/{code}")
async def stats_page(request: Request, code: str, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Link).where((Link.short_code == code) | (Link.custom_alias == code))
    )
    link = result.scalar_one_or_none()
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")

    return templates.TemplateResponse(
        "stats.html",
        {
            "request": request,
            "link": link,
            "short_url": f"{BASE_URL}/{link.short_code}",
            "base_url": BASE_URL,
        },
    )
