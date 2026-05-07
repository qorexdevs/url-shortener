import random
import re
import string

import validators

from app.config import SHORT_CODE_LENGTH

RESERVED_ALIASES = {"api", "static", "stats"}

def generate_short_code(length: int = SHORT_CODE_LENGTH) -> str:
    chars = string.ascii_letters + string.digits
    return "".join(random.choices(chars, k=length))

def validate_url(url: str) -> bool:
    return validators.url(url) is True

def validate_alias(alias: str | None) -> bool:
    if not alias or len(alias) < 3 or len(alias) > 30:
        return False
    if alias.lower() in RESERVED_ALIASES:
        return False
    return bool(re.match(r"^[a-zA-Z0-9_-]+$", alias))
