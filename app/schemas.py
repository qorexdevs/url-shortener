from datetime import datetime
from typing import Optional

from pydantic import BaseModel

class ShortenRequest(BaseModel):
    url: str
    custom_alias: Optional[str] = None
    ttl_hours: Optional[int] = None

class ShortenResponse(BaseModel):
    original_url: str
    short_url: str
    short_code: str

class LinkStats(BaseModel):
    original_url: str
    short_url: str
    short_code: str
    clicks: int
    created_at: datetime
    last_clicked: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    expired: bool = False
