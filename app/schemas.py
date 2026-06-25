from datetime import datetime

from pydantic import BaseModel

class ShortenRequest(BaseModel):
    url: str
    custom_alias: str | None = None
    ttl_hours: int | None = None
    permanent: bool = False

class ShortenResponse(BaseModel):
    original_url: str
    short_url: str
    short_code: str
    expires_at: datetime | None = None
    permanent: bool = False

class BulkShortenRequest(BaseModel):
    urls: list[ShortenRequest]

class BulkShortenItem(BaseModel):
    ok: bool
    original_url: str
    short_url: str | None = None
    short_code: str | None = None
    expires_at: datetime | None = None
    permanent: bool = False
    error: str | None = None

class BulkShortenResponse(BaseModel):
    results: list[BulkShortenItem]

class BulkDeleteRequest(BaseModel):
    codes: list[str]

class BulkDeleteResponse(BaseModel):
    deleted: list[str]
    not_found: list[str]

class RetargetRequest(BaseModel):
    url: str | None = None
    ttl_hours: int | None = None

class LinkPreview(BaseModel):
    short_url: str
    original_url: str
    expires_at: datetime | None = None
    expired: bool = False

class LinkStats(BaseModel):
    original_url: str
    short_url: str
    short_code: str
    clicks: int
    created_at: datetime
    last_clicked: datetime | None = None
    expires_at: datetime | None = None
    expired: bool = False
    permanent: bool = False
