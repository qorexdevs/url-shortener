from datetime import datetime

from pydantic import BaseModel

class ShortenRequest(BaseModel):
    url: str
    custom_alias: str | None = None
    ttl_hours: int | None = None

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
    last_clicked: datetime | None = None
    expires_at: datetime | None = None
    expired: bool = False
