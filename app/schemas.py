from datetime import datetime

from pydantic import BaseModel

class ShortenRequest(BaseModel):
    url: str
    custom_alias: str | None = None
    ttl_hours: int | None = None
    permanent: bool = False
    reuse: bool = False
    forward_query: bool = False
    click_limit: int | None = None

class ShortenResponse(BaseModel):
    original_url: str
    short_url: str
    short_code: str
    expires_at: datetime | None = None
    permanent: bool = False
    reused: bool = False
    forward_query: bool = False
    click_limit: int | None = None

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
    permanent: bool | None = None
    forward_query: bool | None = None
    click_limit: int | None = None

class LinkPreview(BaseModel):
    short_url: str
    original_url: str
    clicks: int = 0
    expires_at: datetime | None = None
    expired: bool = False
    click_limit: int | None = None
    exhausted: bool = False
    remaining: int | None = None

class Summary(BaseModel):
    total_links: int
    total_clicks: int
    active: int
    expired: int
    permanent: int
    unused: int
    custom: int
    expiring_soon: int
    created_recently: int
    exhausted: int = 0
    avg_clicks: float
    busiest: str | None
    busiest_clicks: int = 0
    busiest_share: float = 0.0

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
    forward_query: bool = False
    click_limit: int | None = None
    exhausted: bool = False
    remaining: int | None = None
