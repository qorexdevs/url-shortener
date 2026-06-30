from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Link

def link_expired(link: Link) -> bool:
    if link.expires_at is None:
        return False
    return link.expires_at <= datetime.now(timezone.utc).replace(tzinfo=None)

def link_exhausted(link: Link) -> bool:
    if link.click_limit is None:
        return False
    return link.clicks >= link.click_limit

def link_remaining(link: Link) -> int | None:
    # clicks left before a capped link starts to 410, None when it has no cap.
    # clamped at 0 so an over-counted link reports 0 rather than a negative
    if link.click_limit is None:
        return None
    return max(0, link.click_limit - link.clicks)

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
    elif status == "used":
        stmt = stmt.where(Link.clicks > 0)
    elif status == "exhausted":
        # links that have spent their click limit and now 410 - matches link_exhausted
        stmt = stmt.where(Link.click_limit.is_not(None), Link.clicks >= Link.click_limit)
    elif status == "capped":
        # every link with a click budget, spent or not - the superset of exhausted
        stmt = stmt.where(Link.click_limit.is_not(None))
    elif status == "expiring":
        # live links whose ttl runs out within 24h - matches the summary's expiring_soon count
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        stmt = stmt.where(
            Link.expires_at.is_not(None),
            Link.expires_at > now,
            Link.expires_at <= now + timedelta(hours=24),
        )
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

SORTS = ("created", "clicks", "recent", "stale", "expiring", "code", "remaining")

# every status _filtered understands, in the order shown to the client
STATUSES = (
    "all", "active", "expired", "permanent",
    "unused", "used", "exhausted", "capped", "expiring",
)


def _order_for(sort: str):
    if sort == "clicks":
        return Link.clicks.desc()
    if sort == "recent":
        return Link.last_clicked.desc().nulls_last()
    if sort == "stale":
        # least recently clicked first, never-clicked on top - handy for pruning
        return Link.last_clicked.asc().nulls_first()
    if sort == "expiring":
        return Link.expires_at.asc().nulls_last()
    if sort == "code":
        # alphabetical by the path people actually see - the alias if set, else the code
        return func.coalesce(Link.custom_alias, Link.short_code).asc()
    if sort == "remaining":
        # capped links by clicks left, tightest budget first; unlimited links
        # have no cap so they fall to the bottom
        return (Link.click_limit - Link.clicks).asc().nulls_last()
    return Link.created_at.desc()

async def list_links(
    session: AsyncSession, limit: int, offset: int, sort: str = "created",
    status: str = "all", q: str = "", min_clicks: int = 0, max_clicks: int | None = None,
    created_after: datetime | None = None, created_before: datetime | None = None,
    clicked_after: datetime | None = None, clicked_before: datetime | None = None,
    expires_after: datetime | None = None, expires_before: datetime | None = None,
) -> list[Link]:
    stmt = _filtered(
        select(Link), status, q, min_clicks, max_clicks, created_after, created_before,
        clicked_after, clicked_before, expires_after, expires_before,
    )
    result = await session.execute(
        stmt.order_by(_order_for(sort), Link.id.desc()).limit(limit).offset(offset)
    )
    return list(result.scalars().all())

async def all_links(
    session: AsyncSession, status: str = "all", q: str = "", min_clicks: int = 0,
    max_clicks: int | None = None, created_after: datetime | None = None,
    created_before: datetime | None = None, clicked_after: datetime | None = None,
    clicked_before: datetime | None = None, expires_after: datetime | None = None,
    expires_before: datetime | None = None, sort: str = "created",
) -> list[Link]:
    # every matching link, no pagination - for a full csv export
    stmt = _filtered(
        select(Link), status, q, min_clicks, max_clicks, created_after, created_before,
        clicked_after, clicked_before, expires_after, expires_before,
    ).order_by(_order_for(sort), Link.id.desc())
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
                # links that have spent their click limit and now 410 - matches link_exhausted
                func.count().filter(
                    Link.click_limit.is_not(None), Link.clicks >= Link.click_limit
                ),
                # every link with a click limit set, spent or not - the denominator
                # that makes exhausted readable ("3 of 8 capped links spent")
                func.count().filter(Link.click_limit.is_not(None)),
                # redirects still available before capped links go dark - the running
                # total of link_remaining over links with room left. spent links
                # contribute 0 (clicks < click_limit drops them), matching the clamp
                func.coalesce(
                    func.sum(Link.click_limit - Link.clicks).filter(
                        Link.click_limit.is_not(None), Link.clicks < Link.click_limit
                    ),
                    0,
                ),
            )
        )
    ).one()
    (
        total, clicks, permanent, expired, unused, custom,
        expiring_soon, created_recently, exhausted, capped, remaining_clicks,
    ) = row
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
        "exhausted": exhausted,
        "capped": capped,
        "remaining_clicks": remaining_clicks,
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
