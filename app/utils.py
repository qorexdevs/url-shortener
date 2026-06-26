import re
import secrets
import string
from urllib.parse import urlsplit, urlunsplit

import validators

from app.config import MAX_URL_LENGTH, SHORT_CODE_LENGTH

RESERVED_ALIASES = {"api", "static", "stats", "docs", "redoc"}

def generate_short_code(length: int = SHORT_CODE_LENGTH) -> str:
    chars = string.ascii_letters + string.digits
    return "".join(secrets.choice(chars) for _ in range(length))

def validate_url(url: str) -> bool:
    if len(url) > MAX_URL_LENGTH:
        return False
    if validators.url(url) is True and url.lower().startswith(("http://", "https://")):
        return True

    try:
        parsed = urlsplit(url)
        parsed.port
    except ValueError:
        return False
    if parsed.scheme.lower() not in {"http", "https"}:
        return False
    if parsed.hostname == "localhost":
        return True

    # validators rejects non-ascii hosts, so accept an international domain when
    # its host is valid IDNA (münchen.de, пример.рф and friends)
    ascii_url = _idna_url(parsed)
    return bool(ascii_url and validators.url(ascii_url) is True)

def _idna_url(parsed) -> str | None:
    host = parsed.hostname
    if not host or host.isascii():
        return None
    try:
        ascii_host = host.encode("idna").decode("ascii")
    except (UnicodeError, ValueError):
        return None
    netloc = f"{ascii_host}:{parsed.port}" if parsed.port is not None else ascii_host
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))

def normalize_url(url: str) -> str:
    # store an ascii host so the 307 Location header (latin-1 only) never breaks
    # on an international domain like пример.рф; münchen.de also goes to punycode.
    # scheme and host are case-insensitive, so fold them to lowercase too, else
    # reuse mints a second link for HTTP://Example.COM next to http://example.com
    parsed = urlsplit(url)
    host = parsed.hostname
    if not host:
        return url
    if host.isascii():
        ascii_host = host
    else:
        try:
            ascii_host = host.encode("idna").decode("ascii")
        except (UnicodeError, ValueError):
            return url
    userinfo = ""
    if parsed.username:
        userinfo = parsed.username
        if parsed.password:
            userinfo += f":{parsed.password}"
        userinfo += "@"
    host_part = f"[{ascii_host}]" if ":" in ascii_host else ascii_host
    netloc = f"{userinfo}{host_part}"
    if parsed.port is not None:
        netloc += f":{parsed.port}"
    return urlunsplit((parsed.scheme.lower(), netloc, parsed.path, parsed.query, parsed.fragment))

def validate_alias(alias: str | None) -> bool:
    if not alias or len(alias) < 3 or len(alias) > 30:
        return False
    if alias.lower() in RESERVED_ALIASES:
        return False
    return bool(re.fullmatch(r"[a-zA-Z0-9_-]+", alias))
