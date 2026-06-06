import random
import re
import string
from urllib.parse import urlsplit

import validators

from app.config import MAX_URL_LENGTH, SHORT_CODE_LENGTH

RESERVED_ALIASES = {"api", "static", "stats", "docs", "redoc"}

def generate_short_code(length: int = SHORT_CODE_LENGTH) -> str:
    chars = string.ascii_letters + string.digits
    return "".join(random.choices(chars, k=length))

def validate_url(url: str) -> bool:
    if len(url) > MAX_URL_LENGTH:
        return False
    if validators.url(url) is True:
        return url.lower().startswith(("http://", "https://"))

    try:
        parsed = urlsplit(url)
        parsed.port
    except ValueError:
        return False
    if parsed.scheme.lower() not in {"http", "https"}:
        return False
    return parsed.hostname == "localhost"

def validate_alias(alias: str | None) -> bool:
    if not alias or len(alias) < 3 or len(alias) > 30:
        return False
    if alias.lower() in RESERVED_ALIASES:
        return False
    return bool(re.fullmatch(r"[a-zA-Z0-9_-]+", alias))
