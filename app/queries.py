from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Link

def link_expired(link: Link) -> bool:
    if link.expires_at is None:
        return False
    return link.expires_at <= datetime.now(timezone.utc).replace(tzinfo=None)

async def delete_expired(session: AsyncSession) -> int:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    result = await session.execute(
        delete(Link).where(Link.expires_at.is_not(None), Link.expires_at <= now)
    )
    await session.commit()
    return result.rowcount

def _filtered(
    stmt, status: str, q: str, min_clicks: int = 0, max_clicks: int | None = None,
    created_after: datetime | None = None, created_before: datetime | None = None,
    clicked_after: datetime | None = None, clicked_before: datetime | None = None,
    expires_after: datetime | None = None, expires_before: datetime | None = None,
):
    if status == "permanent":
        stmt = stmt.where(Link.permanent.is_(True))
    elif status == "unused":
        stmt = stmt.where(Link.clicks == 0)
    elif status != "all":
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        live = Link.expires_at.is_(None) | (Link.expires_at > now)
        stmt = stmt.where(live if status == "active" else ~live)
    if min_clicks:
        stmt = stmt.where(Link.clicks >= min_clicks)
    if max_clicks is not None:
        stmt = stmt.where(Link.clicks <= max_clicks)
    if created_after is not None:
        stmt = stmt.where(Link.created_at >= created_after)
    if created_before is not None:
        stmt = stmt.where(Link.created_at <= created_before)
    # a last_clicked bound drops never-clicked links - they have no click date to match
    if clicked_after is not None:
        stmt = stmt.where(Link.last_clicked >= clicked_after)
    if clicked_before is not None:
        stmt = stmt.where(Link.last_clicked <= clicked_before)
    # an expiry bound drops links that never expire - they have no date to match
    if expires_after is not None:
        stmt = stmt.where(Link.expires_at >= expires_after)
    if expires_before is not None:
        stmt = stmt.where(Link.expires_at <= expires_before)
    if q:
        # escape LIKE wildcards so a query like "50%" or "a_b" matches literally
        # instead of standing in for "anything"
        esc = q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"%{esc}%"
        stmt = stmt.where(
            Link.original_url.ilike(like, escape="\\")
            | Link.short_code.ilike(like, escape="\\")
            | Link.custom_alias.ilike(like, escape="\\")
        )
    return stmt

async def list_links(
    session: AsyncSession, limit: int, offset: int, sort: str = "created",
    status: str = "all", q: str = "", min_clicks: int = 0, max_clicks: int | None = None,
    created_after: datetime | None = None, created_before: datetime | None = None,
    clicked_after: datetime | None = None, clicked_before: datetime | None = None,
    expires_after: datetime | None = None, expires_before: datetime | None = None,
) -> list[Link]:
    if sort == "clicks":
        order = Link.clicks.desc()
    elif sort == "recent":
        order = Link.last_clicked.desc().nulls_last()
    elif sort == "stale":
        # least recently clicked first, never-clicked on top - handy for pruning
        order = Link.last_clicked.asc().nulls_first()
    elif sort == "expiring":
        order = Link.expires_at.asc().nulls_last()
    elif sort == "code":
        # alphabetical by the path people actually see - the alias if set, else the code
        order = func.coalesce(Link.custom_alias, Link.short_code).asc()
    else:
        order = Link.created_at.desc()
    stmt = _filtered(
        select(Link), status, q, min_clicks, max_clicks, created_after, created_before,
        clicked_after, clicked_before, expires_after, expires_before,
    )
    result = await session.execute(
        stmt.order_by(order, Link.id.desc()).limit(limit).offset(offset)
    )
    return list(result.scalars().all())

async def all_links(
    session: AsyncSession, status: str = "all", q: str = "", min_clicks: int = 0,
    max_clicks: int | None = None, created_after: datetime | None = None,
    created_before: datetime | None = None, clicked_after: datetime | None = None,
    clicked_before: datetime | None = None, expires_after: datetime | None = None,
    expires_before: datetime | None = None,
) -> list[Link]:
    # every matching link, newest first, no pagination - for a full csv export
    stmt = _filtered(
        select(Link), status, q, min_clicks, max_clicks, created_after, created_before,
        clicked_after, clicked_before, expires_after, expires_before,
    ).order_by(Link.created_at.desc(), Link.id.desc())
    result = await session.execute(stmt)
    return list(result.scalars().all())

async def count_links(
    session: AsyncSession, status: str = "all", q: str = "", min_clicks: int = 0,
    max_clicks: int | None = None, created_after: datetime | None = None,
    created_before: datetime | None = None, clicked_after: datetime | None = None,
    clicked_before: datetime | None = None, expires_after: datetime | None = None,
    expires_before: datetime | None = None,
) -> int:
    stmt = _filtered(
        select(func.count(Link.id)), status, q, min_clicks, max_clicks,
        created_after, created_before, clicked_after, clicked_before,
        expires_after, expires_before,
    )
    return await session.scalar(stmt) or 0

async def summary_stats(session: AsyncSession) -> dict:
    # one-pass counters for a dashboard: totals plus the live/expired/permanent split.
    # active and expired ignore permanent links, which have no expiry to be past.
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    soon = now + timedelta(hours=24)
    day_ago = now - timedelta(hours=24)
    expires = Link.expires_at
    row = (
        await session.execute(
            select(
                func.count(Link.id),
                func.coalesce(func.sum(Link.clicks), 0),
                func.count().filter(Link.permanent.is_(True)),
                func.count().filter(
                    Link.permanent.is_(False), expires.is_not(None), expires <= now
                ),
                func.count().filter(Link.clicks == 0),
                func.count().filter(Link.custom_alias.is_not(None)),
                # still live but expiring within a day - the dashboard's "act now" bucket
                func.count().filter(
                    Link.permanent.is_(False), expires.is_not(None),
                    expires > now, expires <= soon,
                ),
                # links made in the last day - the counterpart to expiring_soon
                func.count().filter(Link.created_at >= day_ago),
            )
        )
    ).one()
    total, clicks, permanent, expired, unused, custom, expiring_soon, created_recently = row
    top = (
        await session.execute(
            select(Link.short_code, Link.clicks)
            .order_by(Link.clicks.desc(), Link.id.asc()).limit(1)
        )
    ).first()
    busiest, busiest_clicks = (top[0], top[1]) if top else (None, 0)
    return {
        "total_links": total,
        "total_clicks": clicks,
        "active": total - permanent - expired,
        "expired": expired,
        "permanent": permanent,
        "unused": unused,
        "custom": custom,
        "expiring_soon": expiring_soon,
        "created_recently": created_recently,
        "avg_clicks": round(clicks / total, 2) if total else 0.0,
        "busiest": busiest,
        "busiest_clicks": busiest_clicks,
        # how much of all traffic the single busiest link pulls - 0..1
        "busiest_share": round(busiest_clicks / clicks, 2) if clicks else 0.0,
    }

async def find_live_by_url(session: AsyncSession, url: str) -> Link | None:
    # newest link still pointing at url that has not expired, for reuse on shorten.
    # custom aliases are skipped so reuse never hands back someone's named link.
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    live = Link.expires_at.is_(None) | (Link.expires_at > now)
    result = await session.execute(
        select(Link)
        .where(Link.original_url == url, Link.custom_alias.is_(None), live)
        .order_by(Link.created_at.desc(), Link.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()

async def find_link(session: AsyncSession, code: str) -> Link | None:
    code_key = code.lower()
    result = await session.execute(
        select(Link).where(
            (func.lower(Link.short_code) == code_key)
            | (func.lower(Link.custom_alias) == code_key)
        )
    )
    return result.scalar_one_or_none()
