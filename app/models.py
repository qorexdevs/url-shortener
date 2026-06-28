from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Integer, String

from app.database import Base

class Link(Base):
    __tablename__ = "links"

    id = Column(Integer, primary_key=True, autoincrement=True)
    original_url = Column(String, nullable=False)
    short_code = Column(String, unique=True, nullable=False, index=True)
    custom_alias = Column(String, unique=True, nullable=True, index=True)
    clicks = Column(Integer, default=0)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc).replace(tzinfo=None))
    last_clicked = Column(DateTime, nullable=True)
    expires_at = Column(DateTime, nullable=True)
    permanent = Column(Boolean, nullable=False, default=False)
    forward_query = Column(Boolean, nullable=False, default=False)
    click_limit = Column(Integer, nullable=True)
