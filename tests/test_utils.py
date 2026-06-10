from app.utils import generate_short_code, normalize_url, validate_alias, validate_url


def test_generate_short_code_default_length():
    code = generate_short_code()
    assert len(code) == 6
    assert code.isalnum()


def test_generate_short_code_custom_length():
    code = generate_short_code(length=10)
    assert len(code) == 10


def test_generate_short_code_uniqueness():
    codes = {generate_short_code() for _ in range(100)}
    assert len(codes) > 90


def test_validate_url_valid():
    assert validate_url("https://example.com") is True
    assert validate_url("http://example.com/path?q=1") is True
    assert validate_url("https://sub.domain.co.uk/a/b") is True
    assert validate_url("http://localhost") is True
    assert validate_url("https://localhost:3000/path?q=1") is True
    assert validate_url("http://127.0.0.1:3000/path") is True
    assert validate_url("https://[::1]:8443/path") is True


def test_validate_url_invalid():
    assert validate_url("not-a-url") is False
    assert validate_url("") is False
    assert validate_url("ftp://nope") is False
    assert validate_url("ftp://example.com") is False
    assert validate_url("https://local_host") is False
    assert validate_url("http://localhost:abc") is False
    assert validate_url("http://[::1") is False


def test_validate_url_idn_host():
    assert validate_url("https://münchen.de") is True
    assert validate_url("https://пример.рф/path") is True
    assert validate_url("https://xn--mnchen-3ya.de") is True
    assert validate_url("http://münchen.de:8080/a?q=1") is True


def test_normalize_url_idn_host_to_punycode():
    # the result must be latin-1 safe so it can ride in a redirect Location header
    out = normalize_url("https://пример.рф/path?q=1")
    assert out == "https://xn--e1afmkfd.xn--p1ai/path?q=1"
    out.encode("latin-1")

    assert normalize_url("http://münchen.de:8080/a") == "http://xn--mnchen-3ya.de:8080/a"


def test_normalize_url_leaves_ascii_untouched():
    assert normalize_url("https://example.com/path?q=1") == "https://example.com/path?q=1"
    assert normalize_url("http://localhost:3000") == "http://localhost:3000"


def test_validate_url_max_length():
    long_path = "https://example.com/" + "a" * 2048
    assert validate_url(long_path) is False
    at_limit = "https://example.com/" + "a" * (2048 - len("https://example.com/"))
    assert len(at_limit) == 2048
    assert validate_url(at_limit) is True


def test_validate_alias_valid():
    assert validate_alias("my-link") is True
    assert validate_alias("abc") is True
    assert validate_alias("test_123") is True
    assert validate_alias("a" * 30) is True


def test_validate_alias_too_short():
    assert validate_alias("ab") is False
    assert validate_alias("") is False


def test_validate_alias_too_long():
    assert validate_alias("a" * 31) is False


def test_validate_alias_bad_chars():
    assert validate_alias("has spaces") is False
    assert validate_alias("no!special") is False
    assert validate_alias("\u0441\u043b\u043e\u0432\u043e") is False


def test_validate_alias_trailing_newline():
    assert validate_alias("abc\n") is False
    assert validate_alias("my-link\n") is False


def test_validate_alias_reserved_path():
    assert validate_alias("api") is False
    assert validate_alias("static") is False
    assert validate_alias("Stats") is False
    assert validate_alias("docs") is False
    assert validate_alias("Redoc") is False


def test_validate_alias_none():
    assert validate_alias(None) is False


