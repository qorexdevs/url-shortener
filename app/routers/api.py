from datetime import datetime, timedelta, timezone
from io import BytesIO

import qrcode
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import BASE_URL
from app.database import get_session
from app.models import Link
from app.schemas import LinkStats, ShortenRequest, ShortenResponse
from app.utils import RESERVED_ALIASES, generate_short_code, validate_alias, validate_url

router = APIRouter()

@router.post("/api/shorten", response_model=ShortenResponse, status_code=201)
async def shorten_url(data: ShortenRequest, session: AsyncSession = Depends(get_session)):
    if not validate_url(data.url):
        raise HTTPException(status_code=400, detail="Invalid URL")

    code = None

    if data.custom_alias is not None:
        if not validate_alias(data.custom_alias):
            raise HTTPException(
                status_code=400,
                detail="Invalid alias. Use 3-30 characters: letters, digits, hyphens, underscores.",
            )
        alias_key = data.custom_alias.lower()
        existing = await session.execute(
            select(Link).where(
                (func.lower(Link.short_code) == alias_key)
                | (func.lower(Link.custom_alias) == alias_key)
            )
        )
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Alias already taken")
        code = data.custom_alias
    else:
        for _ in range(10):
            candidate = generate_short_code()
            if candidate.lower() in RESERVED_ALIASES:
                continue
            candidate_key = candidate.lower()
            existing = await session.execute(
                select(Link).where(
                    (func.lower(Link.short_code) == candidate_key)
                    | (func.lower(Link.custom_alias) == candidate_key)
                )
            )
            if not existing.scalar_one_or_none():
                code = candidate
                break
        if not code:
            raise HTTPException(status_code=500, detail="Failed to generate unique code")

    if data.ttl_hours is not None and data.ttl_hours <= 0:
        raise HTTPException(status_code=400, detail="ttl_hours must be greater than 0")

    expires_at = None
    if data.ttl_hours is not None:
        expires_at = datetime.now(timezone.utc) + timedelta(hours=data.ttl_hours)

    link = Link(
        original_url=data.url,
        short_code=code,
        custom_alias=data.custom_alias,
        expires_at=expires_at,
    )
    session.add(link)
    await session.commit()

    return ShortenResponse(
        original_url=data.url,
        short_url=f"{BASE_URL}/{code}",
        short_code=code,
    )

@router.get("/api/stats/{code}", response_model=LinkStats)
async def get_stats(code: str, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Link).where((Link.short_code == code) | (Link.custom_alias == code))
    )
    link = result.scalar_one_or_none()
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    expired = link.expires_at is not None and link.expires_at <= now
    short_path = link.custom_alias or link.short_code

    return LinkStats(
        original_url=link.original_url,
        short_url=f"{BASE_URL}/{short_path}",
        short_code=link.short_code,
        clicks=link.clicks,
        created_at=link.created_at,
        last_clicked=link.last_clicked,
        expires_at=link.expires_at,
        expired=expired,
    )

@router.get("/api/qr/{code}")
async def get_qr_code(code: str, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Link).where((Link.short_code == code) | (Link.custom_alias == code))
    )
    link = result.scalar_one_or_none()
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if link.expires_at and link.expires_at <= now:
        raise HTTPException(status_code=410, detail="Link has expired")

    short_path = link.custom_alias or link.short_code
    short_url = f"{BASE_URL}/{short_path}"
    img = qrcode.make(short_url)
    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return StreamingResponse(buf, media_type="image/png")

@router.get("/{code}")
async def redirect_to_url(code: str, session: AsyncSession = Depends(get_session)):
    result = await session.execute(
        select(Link).where((Link.short_code == code) | (Link.custom_alias == code))
    )
    link = result.scalar_one_or_none()
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    if link.expires_at and link.expires_at <= now:
        raise HTTPException(status_code=410, detail="Link has expired")

    link.clicks += 1
    link.last_clicked = now
    await session.commit()

    return RedirectResponse(url=link.original_url, status_code=307)
