from datetime import datetime, timedelta, timezone
from io import BytesIO

import qrcode
import qrcode.image.svg as svg
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import BASE_URL, MAX_TTL_HOURS
from app.database import get_session
from app.models import Link
from app.queries import find_link, link_expired
from app.schemas import LinkPreview, LinkStats, ShortenRequest, ShortenResponse
from app.utils import (
    RESERVED_ALIASES,
    generate_short_code,
    normalize_url,
    validate_alias,
    validate_url,
)

router = APIRouter()

@router.post("/api/shorten", response_model=ShortenResponse, status_code=201)
async def shorten_url(data: ShortenRequest, session: AsyncSession = Depends(get_session)):
    url = data.url.strip()
    alias = data.custom_alias.strip() if data.custom_alias is not None else None

    if not validate_url(url):
        raise HTTPException(status_code=400, detail="Invalid URL")
    url = normalize_url(url)

    if data.ttl_hours is not None and data.ttl_hours <= 0:
        raise HTTPException(status_code=400, detail="ttl_hours must be greater than 0")
    if data.ttl_hours is not None and data.ttl_hours > MAX_TTL_HOURS:
        raise HTTPException(
            status_code=400, detail=f"ttl_hours must be at most {MAX_TTL_HOURS}"
        )

    code = None

    if alias is not None:
        if not validate_alias(alias):
            raise HTTPException(
                status_code=400,
                detail="Invalid alias. Use 3-30 characters: letters, digits, hyphens, underscores.",
            )
        if await find_link(session, alias):
            raise HTTPException(status_code=409, detail="Alias already taken")
        code = alias
    else:
        for _ in range(10):
            candidate = generate_short_code()
            if candidate.lower() in RESERVED_ALIASES:
                continue
            if not await find_link(session, candidate):
                code = candidate
                break
        if not code:
            raise HTTPException(status_code=500, detail="Failed to generate unique code")

    expires_at = None
    if data.ttl_hours is not None:
        expires_at = datetime.now(timezone.utc) + timedelta(hours=data.ttl_hours)

    link = Link(
        original_url=url,
        short_code=code,
        custom_alias=alias,
        expires_at=expires_at,
    )
    session.add(link)
    try:
        await session.commit()
    except IntegrityError:
        # lost a race with a concurrent request for the same code
        await session.rollback()
        raise HTTPException(status_code=409, detail="Alias already taken")

    return ShortenResponse(
        original_url=url,
        short_url=f"{BASE_URL}/{code}",
        short_code=code,
        expires_at=expires_at,
    )

@router.get("/api/health")
async def health(session: AsyncSession = Depends(get_session)):
    try:
        await session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="database unavailable")
    return {"status": "ok"}

@router.get("/api/stats/{code}", response_model=LinkStats)
async def get_stats(code: str, session: AsyncSession = Depends(get_session)):
    link = await find_link(session, code)
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")

    expired = link_expired(link)
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

@router.get("/api/preview/{code}", response_model=LinkPreview)
async def preview_link(code: str, session: AsyncSession = Depends(get_session)):
    # where a short link points without following it: no click counted, no redirect
    link = await find_link(session, code)
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")

    short_path = link.custom_alias or link.short_code
    return LinkPreview(
        short_url=f"{BASE_URL}/{short_path}",
        original_url=link.original_url,
        expires_at=link.expires_at,
        expired=link_expired(link),
    )

@router.get("/api/qr/{code}")
async def get_qr_code(
    code: str,
    fmt: str = "png",
    scale: int = 10,
    border: int = 4,
    session: AsyncSession = Depends(get_session),
):
    fmt = fmt.lower()
    if fmt not in ("png", "svg"):
        raise HTTPException(status_code=400, detail="fmt must be png or svg")
    if not 1 <= scale <= 40:
        raise HTTPException(status_code=400, detail="scale must be between 1 and 40")
    if not 0 <= border <= 20:
        raise HTTPException(status_code=400, detail="border must be between 0 and 20")

    link = await find_link(session, code)
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")

    if link_expired(link):
        raise HTTPException(status_code=410, detail="Link has expired")

    short_path = link.custom_alias or link.short_code
    short_url = f"{BASE_URL}/{short_path}"
    buf = BytesIO()
    if fmt == "svg":
        qrcode.make(
            short_url, image_factory=svg.SvgPathImage, box_size=scale, border=border
        ).save(buf)
        media_type = "image/svg+xml"
    else:
        qrcode.make(short_url, box_size=scale, border=border).save(buf, format="PNG")
        media_type = "image/png"
    buf.seek(0)
    # the qr image never changes for a code, so let browsers and caches keep it
    headers = {"Cache-Control": "public, max-age=86400"}
    return StreamingResponse(buf, media_type=media_type, headers=headers)

@router.delete("/api/links/{code}", status_code=204)
async def delete_link(code: str, session: AsyncSession = Depends(get_session)):
    link = await find_link(session, code)
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")
    await session.delete(link)
    await session.commit()

@router.get("/{code}")
async def redirect_to_url(code: str, session: AsyncSession = Depends(get_session)):
    link = await find_link(session, code)
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")

    if link_expired(link):
        raise HTTPException(status_code=410, detail="Link has expired")

    link.clicks += 1
    link.last_clicked = datetime.now(timezone.utc).replace(tzinfo=None)
    await session.commit()

    return RedirectResponse(url=link.original_url, status_code=307)
