from datetime import datetime, timezone

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

async def list_links(
    session: AsyncSession, limit: int, offset: int, sort: str = "created",
    status: str = "all", q: str = "",
) -> list[Link]:
    if sort == "clicks":
        order = Link.clicks.desc()
    elif sort == "recent":
        order = Link.last_clicked.desc().nulls_last()
    elif sort == "expiring":
        order = Link.expires_at.asc().nulls_last()
    else:
        order = Link.created_at.desc()
    stmt = select(Link)
    if status == "permanent":
        stmt = stmt.where(Link.permanent.is_(True))
    elif status != "all":
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        live = Link.expires_at.is_(None) | (Link.expires_at > now)
        stmt = stmt.where(live if status == "active" else ~live)
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
    result = await session.execute(
        stmt.order_by(order, Link.id.desc()).limit(limit).offset(offset)
    )
    return list(result.scalars().all())

async def find_link(session: AsyncSession, code: str) -> Link | None:
    code_key = code.lower()
    result = await session.execute(
        select(Link).where(
            (func.lower(Link.short_code) == code_key)
            | (func.lower(Link.custom_alias) == code_key)
        )
    )
    return result.scalar_one_or_none()
