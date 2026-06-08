from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Link

def link_expired(link: Link) -> bool:
    if link.expires_at is None:
        return False
    return link.expires_at <= datetime.now(timezone.utc).replace(tzinfo=None)

async def find_link(session: AsyncSession, code: str) -> Link | None:
    code_key = code.lower()
    result = await session.execute(
        select(Link).where(
            (func.lower(Link.short_code) == code_key)
            | (func.lower(Link.custom_alias) == code_key)
        )
    )
    return result.scalar_one_or_none()
