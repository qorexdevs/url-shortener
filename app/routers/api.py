import csv
from datetime import datetime, timedelta, timezone
from io import BytesIO, StringIO

import qrcode
import qrcode.image.svg as svg
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import BASE_URL, MAX_TTL_HOURS
from app.database import get_session
from app.models import Link
from app.queries import (
    all_links,
    count_links,
    delete_expired,
    find_link,
    find_live_by_url,
    link_exhausted,
    link_expired,
    list_links,
    summary_stats,
)
from app.schemas import (
    BulkDeleteRequest,
    BulkDeleteResponse,
    BulkShortenItem,
    BulkShortenRequest,
    BulkShortenResponse,
    LinkPreview,
    LinkStats,
    RetargetRequest,
    ShortenRequest,
    ShortenResponse,
    Summary,
)
from app.utils import (
    RESERVED_ALIASES,
    generate_short_code,
    merge_query,
    normalize_url,
    validate_alias,
    validate_url,
)

router = APIRouter()

def _parse_created(value: str, field: str) -> datetime | None:
    # accept an ISO date or datetime, store as naive utc to match Link.created_at
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{field} must be an ISO date")
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt

async def _shorten_one(data: ShortenRequest, session: AsyncSession) -> ShortenResponse:
    url = data.url.strip()
    alias = data.custom_alias.strip() if data.custom_alias is not None else None

    if not validate_url(url):
        raise HTTPException(status_code=400, detail="Invalid URL")
    url = normalize_url(url)

    # reuse hands back an existing live link for the same url instead of minting a
    # new code, so calling shorten twice stays idempotent. a custom alias always
    # makes a fresh link, and ttl/permanent on the request are ignored on a hit.
    if data.reuse and alias is None:
        existing = await find_live_by_url(session, url)
        if existing:
            short_path = existing.custom_alias or existing.short_code
            return ShortenResponse(
                original_url=existing.original_url,
                short_url=f"{BASE_URL}/{short_path}",
                short_code=existing.short_code,
                expires_at=existing.expires_at,
                permanent=existing.permanent,
                forward_query=existing.forward_query,
                click_limit=existing.click_limit,
                reused=True,
            )

    if data.ttl_hours is not None and data.ttl_hours <= 0:
        raise HTTPException(status_code=400, detail="ttl_hours must be greater than 0")
    if data.ttl_hours is not None and data.ttl_hours > MAX_TTL_HOURS:
        raise HTTPException(
            status_code=400, detail=f"ttl_hours must be at most {MAX_TTL_HOURS}"
        )

    if data.click_limit is not None and data.click_limit <= 0:
        raise HTTPException(status_code=400, detail="click_limit must be greater than 0")

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
        expires_at = (datetime.now(timezone.utc) + timedelta(hours=data.ttl_hours)).replace(
            tzinfo=None
        )

    link = Link(
        original_url=url,
        short_code=code,
        custom_alias=alias,
        expires_at=expires_at,
        permanent=data.permanent,
        forward_query=data.forward_query,
        click_limit=data.click_limit,
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
        permanent=link.permanent,
        forward_query=link.forward_query,
        click_limit=link.click_limit,
    )

@router.post("/api/shorten", response_model=ShortenResponse, status_code=201)
async def shorten_url(data: ShortenRequest, session: AsyncSession = Depends(get_session)):
    return await _shorten_one(data, session)

@router.post("/api/shorten/bulk", response_model=BulkShortenResponse)
async def shorten_bulk(
    data: BulkShortenRequest, session: AsyncSession = Depends(get_session)
):
    # shorten a batch in one call: each url is tried on its own, so a bad one comes
    # back as an error item instead of failing the whole request
    if not data.urls:
        raise HTTPException(status_code=400, detail="urls must not be empty")
    if len(data.urls) > 100:
        raise HTTPException(status_code=400, detail="at most 100 urls per request")

    results = []
    for item in data.urls:
        try:
            res = await _shorten_one(item, session)
            results.append(
                BulkShortenItem(
                    ok=True,
                    original_url=res.original_url,
                    short_url=res.short_url,
                    short_code=res.short_code,
                    expires_at=res.expires_at,
                    permanent=res.permanent,
                )
            )
        except HTTPException as exc:
            await session.rollback()
            results.append(
                BulkShortenItem(ok=False, original_url=item.url.strip(), error=exc.detail)
            )
    return BulkShortenResponse(results=results)

@router.get("/api/health")
async def health(session: AsyncSession = Depends(get_session)):
    try:
        await session.execute(text("SELECT 1"))
    except SQLAlchemyError:
        raise HTTPException(status_code=503, detail="database unavailable")
    return {"status": "ok"}

@router.get("/api/summary", response_model=Summary)
async def get_summary(session: AsyncSession = Depends(get_session)):
    # totals across every link: count, clicks, and the active/expired/permanent split
    return Summary(**await summary_stats(session))

@router.get("/api/links", response_model=list[LinkStats])
async def list_all_links(
    response: Response,
    limit: int = 50, offset: int = 0, sort: str = "created", status: str = "all",
    q: str = "", min_clicks: int = 0, max_clicks: int | None = None,
    created_after: str = "", created_before: str = "",
    clicked_after: str = "", clicked_before: str = "",
    expires_after: str = "", expires_before: str = "",
    session: AsyncSession = Depends(get_session),
):
    if not 1 <= limit <= 100:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 100")
    if offset < 0:
        raise HTTPException(status_code=400, detail="offset must be 0 or greater")
    if min_clicks < 0:
        raise HTTPException(status_code=400, detail="min_clicks must be 0 or greater")
    if max_clicks is not None and max_clicks < 0:
        raise HTTPException(status_code=400, detail="max_clicks must be 0 or greater")
    after = _parse_created(created_after, "created_after")
    before = _parse_created(created_before, "created_before")
    clicked_aft = _parse_created(clicked_after, "clicked_after")
    clicked_bef = _parse_created(clicked_before, "clicked_before")
    expires_aft = _parse_created(expires_after, "expires_after")
    expires_bef = _parse_created(expires_before, "expires_before")
    if sort not in ("created", "clicks", "recent", "stale", "expiring", "code"):
        raise HTTPException(
            status_code=400,
            detail="sort must be 'created', 'clicks', 'recent', 'stale', 'expiring' or 'code'",
        )
    if status not in ("all", "active", "expired", "permanent", "unused", "used", "expiring"):
        raise HTTPException(
            status_code=400,
            detail="status must be 'all', 'active', 'expired', 'permanent', 'unused', 'used' or 'expiring'",
        )

    q = q.strip()
    # total matching the same filters, so a client can page without guessing
    response.headers["X-Total-Count"] = str(
        await count_links(
            session, status, q, min_clicks, max_clicks, after, before,
            clicked_aft, clicked_bef, expires_aft, expires_bef,
        )
    )
    links = await list_links(
        session, limit, offset, sort, status, q, min_clicks, max_clicks, after, before,
        clicked_aft, clicked_bef, expires_aft, expires_bef,
    )
    return [
        LinkStats(
            original_url=link.original_url,
            short_url=f"{BASE_URL}/{link.custom_alias or link.short_code}",
            short_code=link.short_code,
            clicks=link.clicks,
            created_at=link.created_at,
            last_clicked=link.last_clicked,
            expires_at=link.expires_at,
            expired=link_expired(link),
            permanent=link.permanent,
            forward_query=link.forward_query,
            click_limit=link.click_limit,
            exhausted=link_exhausted(link),
        )
        for link in links
    ]

@router.get("/api/links.csv")
async def export_links_csv(
    status: str = "all", sort: str = "created", q: str = "",
    min_clicks: int = 0, max_clicks: int | None = None,
    created_after: str = "", created_before: str = "",
    clicked_after: str = "", clicked_before: str = "",
    expires_after: str = "", expires_before: str = "",
    session: AsyncSession = Depends(get_session),
):
    # full export of the matching links as csv, same status/q/sort filters as
    # the list, no pagination - for a backup or a spreadsheet
    if status not in ("all", "active", "expired", "permanent", "unused", "used", "expiring"):
        raise HTTPException(
            status_code=400,
            detail="status must be 'all', 'active', 'expired', 'permanent', 'unused', 'used' or 'expiring'",
        )
    if sort not in ("created", "clicks", "recent", "stale", "expiring", "code"):
        raise HTTPException(
            status_code=400,
            detail="sort must be 'created', 'clicks', 'recent', 'stale', 'expiring' or 'code'",
        )
    if min_clicks < 0:
        raise HTTPException(status_code=400, detail="min_clicks must be 0 or greater")
    if max_clicks is not None and max_clicks < 0:
        raise HTTPException(status_code=400, detail="max_clicks must be 0 or greater")
    after = _parse_created(created_after, "created_after")
    before = _parse_created(created_before, "created_before")
    clicked_aft = _parse_created(clicked_after, "clicked_after")
    clicked_bef = _parse_created(clicked_before, "clicked_before")
    expires_aft = _parse_created(expires_after, "expires_after")
    expires_bef = _parse_created(expires_before, "expires_before")
    links = await all_links(
        session, status, q.strip(), min_clicks, max_clicks, after, before,
        clicked_aft, clicked_bef, expires_aft, expires_bef, sort,
    )

    buf = StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "short_code", "short_url", "original_url", "clicks",
        "created_at", "last_clicked", "expires_at", "expired", "permanent",
    ])
    for link in links:
        short_path = link.custom_alias or link.short_code
        writer.writerow([
            link.short_code,
            f"{BASE_URL}/{short_path}",
            link.original_url,
            link.clicks,
            link.created_at.isoformat() if link.created_at else "",
            link.last_clicked.isoformat() if link.last_clicked else "",
            link.expires_at.isoformat() if link.expires_at else "",
            link_expired(link),
            link.permanent,
        ])

    headers = {"Content-Disposition": 'attachment; filename="links.csv"'}
    return Response(content=buf.getvalue(), media_type="text/csv", headers=headers)

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
        permanent=link.permanent,
        forward_query=link.forward_query,
        click_limit=link.click_limit,
        exhausted=link_exhausted(link),
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
        clicks=link.clicks,
        expires_at=link.expires_at,
        expired=link_expired(link),
        click_limit=link.click_limit,
        exhausted=link_exhausted(link),
    )

@router.get("/api/qr/{code}")
async def get_qr_code(
    code: str,
    fmt: str = "png",
    scale: int = 10,
    border: int = 4,
    download: bool = False,
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
    if download:
        headers["Content-Disposition"] = f'attachment; filename="{short_path}.{fmt}"'
    return StreamingResponse(buf, media_type=media_type, headers=headers)

@router.patch("/api/links/{code}", response_model=LinkStats)
async def retarget_link(
    code: str, data: RetargetRequest, session: AsyncSession = Depends(get_session)
):
    # update an existing link in place, keeping the code and clicks: a new
    # destination, a fresh expiry window, promote it to permanent, or a mix
    link = await find_link(session, code)
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")

    if (
        data.url is None
        and data.ttl_hours is None
        and data.permanent is None
        and data.forward_query is None
        and data.click_limit is None
    ):
        raise HTTPException(
            status_code=400,
            detail="Provide url, ttl_hours, permanent, forward_query or click_limit",
        )

    if data.ttl_hours is not None and data.permanent:
        raise HTTPException(
            status_code=400, detail="ttl_hours and permanent are mutually exclusive"
        )

    if data.url is not None:
        url = data.url.strip()
        if not validate_url(url):
            raise HTTPException(status_code=400, detail="Invalid URL")
        link.original_url = normalize_url(url)

    if data.ttl_hours is not None:
        if data.ttl_hours <= 0:
            raise HTTPException(status_code=400, detail="ttl_hours must be greater than 0")
        if data.ttl_hours > MAX_TTL_HOURS:
            raise HTTPException(
                status_code=400, detail=f"ttl_hours must be at most {MAX_TTL_HOURS}"
            )
        expires = datetime.now(timezone.utc) + timedelta(hours=data.ttl_hours)
        link.expires_at = expires.replace(tzinfo=None)

    if data.permanent is not None:
        link.permanent = data.permanent
        if data.permanent:
            link.expires_at = None

    if data.forward_query is not None:
        link.forward_query = data.forward_query

    if data.click_limit is not None:
        if data.click_limit <= 0:
            raise HTTPException(status_code=400, detail="click_limit must be greater than 0")
        link.click_limit = data.click_limit

    await session.commit()

    short_path = link.custom_alias or link.short_code
    return LinkStats(
        original_url=link.original_url,
        short_url=f"{BASE_URL}/{short_path}",
        short_code=link.short_code,
        clicks=link.clicks,
        created_at=link.created_at,
        last_clicked=link.last_clicked,
        expires_at=link.expires_at,
        expired=link_expired(link),
        permanent=link.permanent,
        forward_query=link.forward_query,
        click_limit=link.click_limit,
        exhausted=link_exhausted(link),
    )

@router.delete("/api/expired")
async def purge_expired(session: AsyncSession = Depends(get_session)):
    # drop every link past its ttl in one pass, for a cron or a manual cleanup
    removed = await delete_expired(session)
    return {"deleted": removed}

@router.post("/api/links/bulk-delete", response_model=BulkDeleteResponse)
async def delete_bulk(
    data: BulkDeleteRequest, session: AsyncSession = Depends(get_session)
):
    # delete a batch by code in one call, reporting which were gone so the caller
    # can tell a real removal from a code that never existed
    if not data.codes:
        raise HTTPException(status_code=400, detail="codes must not be empty")
    if len(data.codes) > 100:
        raise HTTPException(status_code=400, detail="at most 100 codes per request")

    deleted, not_found = [], []
    for code in data.codes:
        link = await find_link(session, code)
        if link:
            await session.delete(link)
            deleted.append(code)
        else:
            not_found.append(code)
    await session.commit()
    return BulkDeleteResponse(deleted=deleted, not_found=not_found)

@router.delete("/api/links/{code}", status_code=204)
async def delete_link(code: str, session: AsyncSession = Depends(get_session)):
    link = await find_link(session, code)
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")
    await session.delete(link)
    await session.commit()

@router.api_route("/{code}", methods=["GET", "HEAD"])
async def redirect_to_url(
    code: str, request: Request, session: AsyncSession = Depends(get_session)
):
    # bitly-style: a trailing + peeks at the destination instead of following it
    if code.endswith("+"):
        link = await find_link(session, code[:-1])
        if not link:
            raise HTTPException(status_code=404, detail="Link not found")
        short_path = link.custom_alias or link.short_code
        return LinkPreview(
            short_url=f"{BASE_URL}/{short_path}",
            original_url=link.original_url,
            clicks=link.clicks,
            expires_at=link.expires_at,
            expired=link_expired(link),
            click_limit=link.click_limit,
            exhausted=link_exhausted(link),
        )

    link = await find_link(session, code)
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")

    if link_expired(link):
        raise HTTPException(status_code=410, detail="Link has expired")

    if link_exhausted(link):
        raise HTTPException(status_code=410, detail="Link has reached its click limit")

    # HEAD is how link checkers and unfurlers probe a link without visiting it, so
    # don't count it as a click. the redirect headers still come back.
    if request.method != "HEAD":
        link.clicks += 1
        link.last_clicked = datetime.now(timezone.utc).replace(tzinfo=None)
        await session.commit()

    # carry the visitor's query string onto the destination when the link opts in,
    # so a campaign tag on the short link reaches the target
    dest = link.original_url
    if link.forward_query and request.url.query:
        dest = merge_query(dest, request.url.query)

    # 308 lets browsers cache a permanent link, so later hits skip the server and
    # stop counting clicks. that's the tradeoff you opt into with permanent=true.
    status = 308 if link.permanent else 307
    return RedirectResponse(url=dest, status_code=status)
