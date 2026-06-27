from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Link
from conftest import test_session as db_session_factory


@pytest.mark.asyncio
async def test_health_ok(client):
    res = await client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_shorten_url(client):
    res = await client.post("/api/shorten", json={"url": "https://example.com"})
    assert res.status_code == 201
    data = res.json()
    assert data["original_url"] == "https://example.com"
    assert "short_url" in data
    assert len(data["short_code"]) == 6


@pytest.mark.asyncio
async def test_shorten_with_custom_alias(client):
    res = await client.post(
        "/api/shorten", json={"url": "https://example.com", "custom_alias": "mylink"}
    )
    assert res.status_code == 201
    assert res.json()["short_code"] == "mylink"


@pytest.mark.asyncio
async def test_shorten_trims_url_whitespace(client):
    res = await client.post("/api/shorten", json={"url": "  https://example.com  "})
    assert res.status_code == 201
    assert res.json()["original_url"] == "https://example.com"


@pytest.mark.asyncio
async def test_shorten_trims_url_tabs_and_newlines(client):
    res = await client.post("/api/shorten", json={"url": "\n\thttps://example.com\t\n"})
    assert res.status_code == 201
    assert res.json()["original_url"] == "https://example.com"


@pytest.mark.asyncio
async def test_shorten_trims_custom_alias_whitespace(client):
    res = await client.post(
        "/api/shorten", json={"url": "https://example.com", "custom_alias": "  mylink  "}
    )
    assert res.status_code == 201
    assert res.json()["short_code"] == "mylink"


@pytest.mark.asyncio
async def test_shorten_trims_custom_alias_tabs_and_newlines(client):
    res = await client.post(
        "/api/shorten",
        json={"url": "https://example.com", "custom_alias": "\n\tmylink\t\n"},
    )
    assert res.status_code == 201
    assert res.json()["short_code"] == "mylink"


@pytest.mark.asyncio
async def test_shorten_skips_reserved_generated_code(client):
    with patch("app.routers.api.generate_short_code", side_effect=["static", "abc123"]):
        res = await client.post("/api/shorten", json={"url": "https://example.com"})
    assert res.status_code == 201
    assert res.json()["short_code"] == "abc123"


@pytest.mark.asyncio
async def test_shorten_skips_mixed_case_reserved_generated_code(client):
    with patch("app.routers.api.generate_short_code", side_effect=["StAtIc", "abc123"]):
        res = await client.post("/api/shorten", json={"url": "https://example.com"})
    assert res.status_code == 201
    assert res.json()["short_code"] == "abc123"


@pytest.mark.asyncio
async def test_shorten_skips_docs_generated_code(client):
    with patch("app.routers.api.generate_short_code", side_effect=["docs", "abc123"]):
        res = await client.post("/api/shorten", json={"url": "https://example.com"})
    assert res.status_code == 201
    assert res.json()["short_code"] == "abc123"


@pytest.mark.asyncio
async def test_shorten_skips_generated_code_taken_by_custom_alias(client):
    async with db_session_factory() as session:
        session.add(
            Link(
                original_url="https://legacy.example.com",
                short_code="legacy01",
                custom_alias="abc123",
            )
        )
        await session.commit()

    with patch("app.routers.api.generate_short_code", side_effect=["abc123", "def456"]):
        res = await client.post("/api/shorten", json={"url": "https://example.com"})

    assert res.status_code == 201
    assert res.json()["short_code"] == "def456"


@pytest.mark.asyncio
async def test_shorten_skips_generated_code_taken_by_alias_case_insensitive(client):
    async with db_session_factory() as session:
        session.add(
            Link(
                original_url="https://legacy.example.com",
                short_code="legacy01",
                custom_alias="AbC123",
            )
        )
        await session.commit()

    with patch("app.routers.api.generate_short_code", side_effect=["abc123", "def456"]):
        res = await client.post("/api/shorten", json={"url": "https://example.com"})

    assert res.status_code == 201
    assert res.json()["short_code"] == "def456"


@pytest.mark.asyncio
async def test_shorten_duplicate_alias(client):
    payload = {"url": "https://example.com", "custom_alias": "taken"}
    await client.post("/api/shorten", json=payload)
    res = await client.post("/api/shorten", json=payload)
    assert res.status_code == 409


@pytest.mark.asyncio
async def test_shorten_duplicate_alias_case_insensitive(client):
    await client.post(
        "/api/shorten", json={"url": "https://example.com", "custom_alias": "MyLink"}
    )
    res = await client.post(
        "/api/shorten", json={"url": "https://example.com", "custom_alias": "mylink"}
    )
    assert res.status_code == 409


@pytest.mark.asyncio
async def test_shorten_duplicate_alias_race_returns_conflict(client):
    payload = {"url": "https://example.com", "custom_alias": "racy"}
    res = await client.post("/api/shorten", json=payload)
    assert res.status_code == 201

    # simulate losing the check-then-insert race: the existence check sees
    # nothing, the unique constraint fires on commit
    missed = MagicMock()
    missed.scalar_one_or_none.return_value = None
    with patch.object(AsyncSession, "execute", AsyncMock(return_value=missed)):
        res = await client.post("/api/shorten", json=payload)
    assert res.status_code == 409


@pytest.mark.asyncio
async def test_shorten_invalid_url(client):
    res = await client.post("/api/shorten", json={"url": "not-a-url"})
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_shorten_invalid_ipv6_url(client):
    res = await client.post("/api/shorten", json={"url": "http://[::1"})
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_shorten_rejects_localhost_with_invalid_port(client):
    res = await client.post("/api/shorten", json={"url": "http://localhost:abc/test"})
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_shorten_allows_localhost_url(client):
    res = await client.post("/api/shorten", json={"url": "http://localhost:3000/test"})
    assert res.status_code == 201
    assert res.json()["original_url"] == "http://localhost:3000/test"


@pytest.mark.asyncio
async def test_shorten_allows_loopback_ipv4_url(client):
    res = await client.post("/api/shorten", json={"url": "http://127.0.0.1:3000/test"})
    assert res.status_code == 201
    assert res.json()["original_url"] == "http://127.0.0.1:3000/test"


@pytest.mark.asyncio
async def test_shorten_allows_loopback_ipv6_url(client):
    res = await client.post("/api/shorten", json={"url": "http://[::1]:3000/test"})
    assert res.status_code == 201
    assert res.json()["original_url"] == "http://[::1]:3000/test"


@pytest.mark.asyncio
async def test_shorten_stores_idn_host_as_punycode(client):
    res = await client.post("/api/shorten", json={"url": "https://пример.рф/path"})
    assert res.status_code == 201
    code = res.json()["short_code"]
    assert res.json()["original_url"] == "https://xn--e1afmkfd.xn--p1ai/path"

    # the redirect Location header is latin-1 only, so it has to be the ascii host
    res = await client.get(f"/{code}", follow_redirects=False)
    assert res.headers["location"] == "https://xn--e1afmkfd.xn--p1ai/path"


@pytest.mark.asyncio
async def test_retarget_normalizes_idn_host_to_punycode(client):
    res = await client.post("/api/shorten", json={"url": "https://example.com"})
    code = res.json()["short_code"]

    res = await client.patch(f"/api/links/{code}", json={"url": "http://münchen.de:8080/a"})
    assert res.status_code == 200
    assert res.json()["original_url"] == "http://xn--mnchen-3ya.de:8080/a"

    res = await client.get(f"/{code}", follow_redirects=False)
    assert res.headers["location"] == "http://xn--mnchen-3ya.de:8080/a"


@pytest.mark.asyncio
async def test_shorten_invalid_alias(client):
    res = await client.post(
        "/api/shorten", json={"url": "https://example.com", "custom_alias": "ab"}
    )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_shorten_rejects_reserved_alias(client):
    for alias in ("api", "static", "stats", "docs", "redoc"):
        res = await client.post(
            "/api/shorten", json={"url": "https://example.com", "custom_alias": alias}
        )
        assert res.status_code == 400


@pytest.mark.asyncio
async def test_shorten_empty_alias(client):
    res = await client.post(
        "/api/shorten", json={"url": "https://example.com", "custom_alias": ""}
    )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_redirect(client):
    res = await client.post("/api/shorten", json={"url": "https://example.com"})
    code = res.json()["short_code"]
    res = await client.get(f"/{code}", follow_redirects=False)
    assert res.status_code == 307
    assert res.headers["location"] == "https://example.com"


@pytest.mark.asyncio
async def test_permanent_link_redirects_with_308(client):
    res = await client.post(
        "/api/shorten", json={"url": "https://example.com", "permanent": True}
    )
    assert res.status_code == 201
    assert res.json()["permanent"] is True
    code = res.json()["short_code"]

    res = await client.get(f"/{code}", follow_redirects=False)
    assert res.status_code == 308
    assert res.headers["location"] == "https://example.com"

    assert (await client.get(f"/api/stats/{code}")).json()["permanent"] is True


@pytest.mark.asyncio
async def test_links_default_to_temporary_redirect(client):
    res = await client.post("/api/shorten", json={"url": "https://example.com"})
    assert res.json()["permanent"] is False
    code = res.json()["short_code"]
    res = await client.get(f"/{code}", follow_redirects=False)
    assert res.status_code == 307


@pytest.mark.asyncio
async def test_redirect_short_code_lookup_case_insensitive(client):
    with patch("app.routers.api.generate_short_code", return_value="AbC123"):
        res = await client.post("/api/shorten", json={"url": "https://example.com"})
    assert res.status_code == 201
    assert res.json()["short_code"] == "AbC123"

    res = await client.get("/abc123", follow_redirects=False)
    assert res.status_code == 307
    assert res.headers["location"] == "https://example.com"


@pytest.mark.asyncio
async def test_redirect_not_found(client):
    res = await client.get("/nonexistent", follow_redirects=False)
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_redirect_plus_peeks_without_counting(client):
    res = await client.post("/api/shorten", json={"url": "https://example.com"})
    code = res.json()["short_code"]

    # a real visit first, so the peek has a click count to report back
    await client.get(f"/{code}", follow_redirects=False)

    res = await client.get(f"/{code}+", follow_redirects=False)
    assert res.status_code == 200
    data = res.json()
    assert data["original_url"] == "https://example.com"
    assert data["expired"] is False
    assert data["clicks"] == 1

    res = await client.get(f"/api/stats/{code}")
    assert res.json()["clicks"] == 1


@pytest.mark.asyncio
async def test_redirect_plus_not_found(client):
    res = await client.get("/nope+", follow_redirects=False)
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_stats(client):
    res = await client.post("/api/shorten", json={"url": "https://example.com"})
    code = res.json()["short_code"]

    # click it once
    await client.get(f"/{code}", follow_redirects=False)

    res = await client.get(f"/api/stats/{code}")
    assert res.status_code == 200
    data = res.json()
    assert data["clicks"] == 1
    assert data["original_url"] == "https://example.com"
    assert data["last_clicked"] is not None


@pytest.mark.asyncio
async def test_stats_short_code_lookup_case_insensitive(client):
    with patch("app.routers.api.generate_short_code", return_value="AbC123"):
        res = await client.post("/api/shorten", json={"url": "https://example.com"})
    assert res.status_code == 201

    res = await client.get("/api/stats/abc123")
    assert res.status_code == 200
    assert res.json()["short_url"].endswith("/AbC123")


@pytest.mark.asyncio
async def test_stats_not_found(client):
    res = await client.get("/api/stats/nope")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_preview_returns_destination(client):
    res = await client.post("/api/shorten", json={"url": "https://example.com"})
    code = res.json()["short_code"]

    res = await client.get(f"/api/preview/{code}")
    assert res.status_code == 200
    data = res.json()
    assert data["original_url"] == "https://example.com"
    assert data["expired"] is False
    assert data["clicks"] == 0


@pytest.mark.asyncio
async def test_preview_does_not_count_click(client):
    res = await client.post("/api/shorten", json={"url": "https://example.com"})
    code = res.json()["short_code"]

    await client.get(f"/api/preview/{code}")
    await client.get(f"/api/preview/{code}")

    res = await client.get(f"/api/stats/{code}")
    assert res.json()["clicks"] == 0
    assert res.json()["last_clicked"] is None


@pytest.mark.asyncio
async def test_preview_not_found(client):
    res = await client.get("/api/preview/nope")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_preview_marks_expired(client):
    res = await client.post(
        "/api/shorten", json={"url": "https://example.com", "ttl_hours": 1}
    )
    code = res.json()["short_code"]

    future = datetime.now(timezone.utc) + timedelta(hours=2)
    with patch("app.queries.datetime") as mock_dt:
        mock_dt.now.return_value = future
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        res = await client.get(f"/api/preview/{code}")
    assert res.status_code == 200
    assert res.json()["expired"] is True


@pytest.mark.asyncio
async def test_redirect_increments_clicks(client):
    res = await client.post("/api/shorten", json={"url": "https://example.com"})
    code = res.json()["short_code"]

    for _ in range(3):
        await client.get(f"/{code}", follow_redirects=False)

    res = await client.get(f"/api/stats/{code}")
    assert res.json()["clicks"] == 3


@pytest.mark.asyncio
async def test_head_redirect_does_not_count_as_click(client):
    res = await client.post("/api/shorten", json={"url": "https://example.com"})
    code = res.json()["short_code"]

    head = await client.head(f"/{code}", follow_redirects=False)
    assert head.status_code == 307
    assert head.headers["location"] == "https://example.com"

    # head probed the link, a real get still counts
    assert (await client.get(f"/api/stats/{code}")).json()["clicks"] == 0
    await client.get(f"/{code}", follow_redirects=False)
    assert (await client.get(f"/api/stats/{code}")).json()["clicks"] == 1


@pytest.mark.asyncio
async def test_custom_alias_redirect(client):
    await client.post(
        "/api/shorten", json={"url": "https://github.com", "custom_alias": "gh-link"}
    )
    res = await client.get("/gh-link", follow_redirects=False)
    assert res.status_code == 307
    assert res.headers["location"] == "https://github.com"


@pytest.mark.asyncio
async def test_custom_alias_redirect_case_insensitive(client):
    await client.post(
        "/api/shorten", json={"url": "https://github.com", "custom_alias": "Gh-Link"}
    )
    res = await client.get("/gh-link", follow_redirects=False)
    assert res.status_code == 307
    assert res.headers["location"] == "https://github.com"


@pytest.mark.asyncio
async def test_stats_short_url_uses_custom_alias(client):
    await client.post(
        "/api/shorten", json={"url": "https://github.com", "custom_alias": "gh-link"}
    )
    res = await client.get("/api/stats/gh-link")
    assert res.status_code == 200
    assert res.json()["short_url"].endswith("/gh-link")


@pytest.mark.asyncio
async def test_stats_lookup_case_insensitive(client):
    await client.post(
        "/api/shorten", json={"url": "https://github.com", "custom_alias": "Gh-Link"}
    )
    res = await client.get("/api/stats/gh-link")
    assert res.status_code == 200
    assert res.json()["short_url"].endswith("/Gh-Link")


@pytest.mark.asyncio
async def test_shorten_with_ttl(client):
    res = await client.post(
        "/api/shorten", json={"url": "https://example.com", "ttl_hours": 24}
    )
    assert res.status_code == 201
    body = res.json()
    code = body["short_code"]
    assert body["expires_at"] is not None

    stats = await client.get(f"/api/stats/{code}")
    data = stats.json()
    assert data["expires_at"] is not None
    assert data["expired"] is False


@pytest.mark.asyncio
async def test_shorten_without_ttl_has_no_expiry(client):
    res = await client.post("/api/shorten", json={"url": "https://example.com"})
    assert res.status_code == 201
    assert res.json()["expires_at"] is None


@pytest.mark.asyncio
async def test_shorten_rejects_zero_ttl(client):
    res = await client.post(
        "/api/shorten", json={"url": "https://example.com", "ttl_hours": 0}
    )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_shorten_rejects_negative_ttl(client):
    res = await client.post(
        "/api/shorten", json={"url": "https://example.com", "ttl_hours": -1}
    )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_shorten_rejects_ttl_over_limit(client):
    res = await client.post(
        "/api/shorten", json={"url": "https://example.com", "ttl_hours": 24 * 365 * 10 + 1}
    )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_shorten_rejects_huge_ttl_without_500(client):
    # used to overflow timedelta and crash with a 500
    res = await client.post(
        "/api/shorten", json={"url": "https://example.com", "ttl_hours": 10**15}
    )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_expired_link_returns_410(client):
    res = await client.post(
        "/api/shorten", json={"url": "https://example.com", "ttl_hours": 1}
    )
    code = res.json()["short_code"]

    future = datetime.now(timezone.utc) + timedelta(hours=2)
    with patch("app.queries.datetime") as mock_dt:
        mock_dt.now.return_value = future
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        res = await client.get(f"/{code}", follow_redirects=False)
        assert res.status_code == 410


@pytest.mark.asyncio
async def test_link_expires_at_boundary(client):
    base = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    expires_at = base + timedelta(hours=1)

    with patch("app.routers.api.datetime") as mock_dt:
        mock_dt.now.return_value = base
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        res = await client.post(
            "/api/shorten", json={"url": "https://example.com", "ttl_hours": 1}
        )
    code = res.json()["short_code"]

    with patch("app.queries.datetime") as mock_dt:
        mock_dt.now.return_value = expires_at
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        res = await client.get(f"/{code}", follow_redirects=False)
        assert res.status_code == 410


@pytest.mark.asyncio
async def test_stored_datetimes_are_naive(client):
    res = await client.post(
        "/api/shorten", json={"url": "https://example.com", "ttl_hours": 1}
    )
    code = res.json()["short_code"]

    from app.queries import find_link

    async with db_session_factory() as s:
        link = await find_link(s, code)
        assert link.created_at.tzinfo is None
        assert link.expires_at.tzinfo is None


@pytest.mark.asyncio
async def test_stats_shows_expired(client):
    res = await client.post(
        "/api/shorten", json={"url": "https://example.com", "ttl_hours": 1}
    )
    code = res.json()["short_code"]

    future = datetime.now(timezone.utc) + timedelta(hours=2)
    with patch("app.queries.datetime") as mock_dt:
        mock_dt.now.return_value = future
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        stats = await client.get(f"/api/stats/{code}")
        assert stats.json()["expired"] is True


@pytest.mark.asyncio
async def test_qr_code(client):
    res = await client.post("/api/shorten", json={"url": "https://example.com"})
    code = res.json()["short_code"]
    res = await client.get(f"/api/qr/{code}")
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/png"
    assert "max-age" in res.headers["cache-control"]
    assert len(res.content) > 100


@pytest.mark.asyncio
async def test_qr_code_svg(client):
    res = await client.post("/api/shorten", json={"url": "https://example.com"})
    code = res.json()["short_code"]
    res = await client.get(f"/api/qr/{code}?fmt=svg")
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/svg+xml"
    assert b"<svg" in res.content


@pytest.mark.asyncio
async def test_qr_code_bad_format(client):
    res = await client.post("/api/shorten", json={"url": "https://example.com"})
    code = res.json()["short_code"]
    res = await client.get(f"/api/qr/{code}?fmt=gif")
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_qr_code_scale_changes_size(client):
    res = await client.post("/api/shorten", json={"url": "https://example.com"})
    code = res.json()["short_code"]
    small = await client.get(f"/api/qr/{code}?scale=2")
    big = await client.get(f"/api/qr/{code}?scale=20")
    assert small.status_code == 200
    assert big.status_code == 200
    assert len(big.content) > len(small.content)


@pytest.mark.asyncio
async def test_qr_code_rejects_bad_scale(client):
    res = await client.post("/api/shorten", json={"url": "https://example.com"})
    code = res.json()["short_code"]
    assert (await client.get(f"/api/qr/{code}?scale=0")).status_code == 400
    assert (await client.get(f"/api/qr/{code}?scale=99")).status_code == 400


@pytest.mark.asyncio
async def test_qr_code_rejects_bad_border(client):
    res = await client.post("/api/shorten", json={"url": "https://example.com"})
    code = res.json()["short_code"]
    assert (await client.get(f"/api/qr/{code}?border=-1")).status_code == 400
    assert (await client.get(f"/api/qr/{code}?border=99")).status_code == 400


@pytest.mark.asyncio
async def test_qr_code_download_sets_attachment(client):
    res = await client.post("/api/shorten", json={"url": "https://example.com"})
    code = res.json()["short_code"]

    inline = await client.get(f"/api/qr/{code}")
    assert "content-disposition" not in inline.headers

    res = await client.get(f"/api/qr/{code}?download=1")
    assert res.status_code == 200
    assert res.headers["content-disposition"] == f'attachment; filename="{code}.png"'

    res = await client.get(f"/api/qr/{code}?fmt=svg&download=1")
    assert res.headers["content-disposition"] == f'attachment; filename="{code}.svg"'


@pytest.mark.asyncio
async def test_qr_code_lookup_case_insensitive(client):
    await client.post(
        "/api/shorten", json={"url": "https://example.com", "custom_alias": "Qr-Link"}
    )
    res = await client.get("/api/qr/qr-link")
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/png"


@pytest.mark.asyncio
async def test_qr_short_code_lookup_case_insensitive(client):
    with patch("app.routers.api.generate_short_code", return_value="AbC123"):
        res = await client.post("/api/shorten", json={"url": "https://example.com"})
    assert res.status_code == 201

    res = await client.get("/api/qr/abc123")
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/png"


@pytest.mark.asyncio
async def test_expired_qr_code_returns_410(client):
    res = await client.post(
        "/api/shorten", json={"url": "https://example.com", "ttl_hours": 1}
    )
    code = res.json()["short_code"]

    future = datetime.now(timezone.utc) + timedelta(hours=2)
    with patch("app.queries.datetime") as mock_dt:
        mock_dt.now.return_value = future
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        res = await client.get(f"/api/qr/{code}")
        assert res.status_code == 410


@pytest.mark.asyncio
async def test_qr_code_not_found(client):
    res = await client.get("/api/qr/nope")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_no_ttl_means_no_expiration(client):
    res = await client.post("/api/shorten", json={"url": "https://example.com"})
    code = res.json()["short_code"]
    stats = await client.get(f"/api/stats/{code}")
    assert stats.json()["expires_at"] is None
    assert stats.json()["expired"] is False


@pytest.mark.asyncio
async def test_home_page_has_ttl_field(client):
    res = await client.get("/")
    assert res.status_code == 200
    assert 'id="ttl"' in res.text


@pytest.mark.asyncio
async def test_stats_page_shows_expiration(client):
    res = await client.post(
        "/api/shorten", json={"url": "https://example.com", "ttl_hours": 24}
    )
    code = res.json()["short_code"]

    res = await client.get(f"/stats/{code}")
    assert res.status_code == 200
    assert "Expiration" in res.text
    expiration = res.text[res.text.index("Expiration"):res.text.index("Total Clicks")]
    assert "Never" not in expiration


@pytest.mark.asyncio
async def test_stats_page_shows_expired_at_boundary(client):
    base = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    expires_at = base + timedelta(hours=1)

    with patch("app.routers.api.datetime") as mock_dt:
        mock_dt.now.return_value = base
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        res = await client.post(
            "/api/shorten", json={"url": "https://example.com", "ttl_hours": 1}
        )
    code = res.json()["short_code"]

    with patch("app.routers.pages.datetime") as mock_dt:
        mock_dt.now.return_value = expires_at
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        res = await client.get(f"/stats/{code}")
        assert res.status_code == 200
        assert "(expired)" in res.text


@pytest.mark.asyncio
async def test_stats_page_short_url_uses_custom_alias(client):
    await client.post(
        "/api/shorten", json={"url": "https://github.com", "custom_alias": "gh-link"}
    )
    res = await client.get("/stats/gh-link")
    assert res.status_code == 200
    assert "/gh-link" in res.text


@pytest.mark.asyncio
async def test_stats_page_shows_qr_for_active_link(client):
    await client.post(
        "/api/shorten", json={"url": "https://github.com", "custom_alias": "gh-qr"}
    )
    res = await client.get("/stats/gh-qr")
    assert res.status_code == 200
    assert "/api/qr/gh-qr" in res.text


@pytest.mark.asyncio
async def test_stats_page_hides_qr_for_expired_link(client):
    base = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    with patch("app.routers.api.datetime") as mock_dt:
        mock_dt.now.return_value = base
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        res = await client.post(
            "/api/shorten", json={"url": "https://example.com", "ttl_hours": 1}
        )
    code = res.json()["short_code"]

    with patch("app.routers.pages.datetime") as mock_dt:
        mock_dt.now.return_value = base + timedelta(hours=2)
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        res = await client.get(f"/stats/{code}")
        assert res.status_code == 200
        assert "/api/qr/" not in res.text


@pytest.mark.asyncio
async def test_stats_page_short_code_lookup_case_insensitive(client):
    with patch("app.routers.api.generate_short_code", return_value="AbC123"):
        res = await client.post("/api/shorten", json={"url": "https://example.com"})
    assert res.status_code == 201

    res = await client.get("/stats/abc123")
    assert res.status_code == 200
    assert "/AbC123" in res.text


@pytest.mark.asyncio
async def test_stats_page_custom_alias_lookup_case_insensitive(client):
    await client.post(
        "/api/shorten", json={"url": "https://github.com", "custom_alias": "Gh-Link"}
    )
    res = await client.get("/stats/gh-link")
    assert res.status_code == 200
    assert "/Gh-Link" in res.text



@pytest.mark.asyncio
async def test_list_links_empty(client):
    res = await client.get("/api/links")
    assert res.status_code == 200
    assert res.json() == []


@pytest.mark.asyncio
async def test_list_links_newest_first(client):
    for url in ("https://a.example.com", "https://b.example.com", "https://c.example.com"):
        await client.post("/api/shorten", json={"url": url})

    res = await client.get("/api/links")
    assert res.status_code == 200
    urls = [item["original_url"] for item in res.json()]
    assert urls == ["https://c.example.com", "https://b.example.com", "https://a.example.com"]


@pytest.mark.asyncio
async def test_list_links_pagination(client):
    for i in range(5):
        await client.post("/api/shorten", json={"url": f"https://example.com/{i}"})

    first = await client.get("/api/links?limit=2&offset=0")
    second = await client.get("/api/links?limit=2&offset=2")
    assert len(first.json()) == 2
    assert len(second.json()) == 2
    codes = {x["short_code"] for x in first.json()} | {x["short_code"] for x in second.json()}
    assert len(codes) == 4


@pytest.mark.asyncio
async def test_list_links_total_count_header(client):
    for i in range(5):
        await client.post("/api/shorten", json={"url": f"https://example.com/{i}"})

    res = await client.get("/api/links?limit=2")
    assert len(res.json()) == 2
    assert res.headers["X-Total-Count"] == "5"

    res = await client.get("/api/links?q=example.com/3")
    assert res.headers["X-Total-Count"] == "1"


@pytest.mark.asyncio
async def test_export_links_csv(client):
    for url in ("https://a.example.com", "https://b.example.com"):
        await client.post("/api/shorten", json={"url": url})

    res = await client.get("/api/links.csv")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    assert "attachment" in res.headers["content-disposition"]
    rows = [r for r in res.text.splitlines() if r]
    assert rows[0].startswith("short_code,short_url,original_url,clicks")
    assert len(rows) == 3  # header + two links
    assert "https://a.example.com" in res.text


@pytest.mark.asyncio
async def test_export_links_csv_respects_filter(client):
    await client.post("/api/shorten", json={"url": "https://github.com/x"})
    await client.post("/api/shorten", json={"url": "https://example.com/y"})

    res = await client.get("/api/links.csv?q=github")
    rows = [r for r in res.text.splitlines() if r]
    assert len(rows) == 2  # header + the one match
    assert "github" in res.text
    assert "example.com/y" not in res.text

    assert (await client.get("/api/links.csv?status=bogus")).status_code == 400


@pytest.mark.asyncio
async def test_list_links_sort_by_clicks(client):
    codes = {}
    for url in ("https://a.example.com", "https://b.example.com", "https://c.example.com"):
        res = await client.post("/api/shorten", json={"url": url})
        codes[url] = res.json()["short_code"]

    for _ in range(3):
        await client.get(f"/{codes['https://b.example.com']}", follow_redirects=False)
    await client.get(f"/{codes['https://a.example.com']}", follow_redirects=False)

    res = await client.get("/api/links?sort=clicks")
    assert res.status_code == 200
    urls = [item["original_url"] for item in res.json()]
    assert urls == ["https://b.example.com", "https://a.example.com", "https://c.example.com"]

    assert (await client.get("/api/links?sort=bogus")).status_code == 400


@pytest.mark.asyncio
async def test_list_links_sort_by_recent(client):
    codes = {}
    for url in ("https://a.example.com", "https://b.example.com", "https://c.example.com"):
        res = await client.post("/api/shorten", json={"url": url})
        codes[url] = res.json()["short_code"]

    # click b, then a - a is the most recently clicked, c never clicked
    await client.get(f"/{codes['https://b.example.com']}", follow_redirects=False)
    await client.get(f"/{codes['https://a.example.com']}", follow_redirects=False)

    res = await client.get("/api/links?sort=recent")
    assert res.status_code == 200
    urls = [item["original_url"] for item in res.json()]
    # clicked ones first, newest click on top, never-clicked sinks to the end
    assert urls[:2] == ["https://a.example.com", "https://b.example.com"]
    assert urls[-1] == "https://c.example.com"


@pytest.mark.asyncio
async def test_list_links_sort_by_stale(client):
    codes = {}
    for url in ("https://a.example.com", "https://b.example.com", "https://c.example.com"):
        res = await client.post("/api/shorten", json={"url": url})
        codes[url] = res.json()["short_code"]

    # click b, then a - a is freshest, c never clicked so it's the most stale
    await client.get(f"/{codes['https://b.example.com']}", follow_redirects=False)
    await client.get(f"/{codes['https://a.example.com']}", follow_redirects=False)

    res = await client.get("/api/links?sort=stale")
    assert res.status_code == 200
    urls = [item["original_url"] for item in res.json()]
    # never-clicked on top, then oldest click, freshest click last
    assert urls[0] == "https://c.example.com"
    assert urls[-2:] == ["https://b.example.com", "https://a.example.com"]


@pytest.mark.asyncio
async def test_list_links_sort_by_expiring(client):
    await client.post("/api/shorten", json={"url": "https://soon.example.com", "ttl_hours": 1})
    await client.post("/api/shorten", json={"url": "https://later.example.com", "ttl_hours": 24})
    await client.post("/api/shorten", json={"url": "https://forever.example.com"})

    res = await client.get("/api/links?sort=expiring")
    assert res.status_code == 200
    urls = [item["original_url"] for item in res.json()]
    # soonest expiry on top, the one with no ttl sinks to the end
    assert urls == [
        "https://soon.example.com",
        "https://later.example.com",
        "https://forever.example.com",
    ]


@pytest.mark.asyncio
async def test_list_links_sort_by_code(client):
    await client.post("/api/shorten", json={"url": "https://m.example.com", "custom_alias": "mango"})
    await client.post("/api/shorten", json={"url": "https://a.example.com", "custom_alias": "apple"})
    await client.post("/api/shorten", json={"url": "https://z.example.com", "custom_alias": "zebra"})

    res = await client.get("/api/links?sort=code")
    assert res.status_code == 200
    paths = [item["short_url"].rsplit("/", 1)[-1] for item in res.json()]
    assert paths == ["apple", "mango", "zebra"]


@pytest.mark.asyncio
async def test_list_links_filter_by_status(client):
    await client.post("/api/shorten", json={"url": "https://live.example.com"})
    past = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
    async with db_session_factory() as session:
        session.add(
            Link(original_url="https://dead.example.com", short_code="dead0001",
                 expires_at=past)
        )
        await session.commit()

    active = await client.get("/api/links?status=active")
    assert [x["original_url"] for x in active.json()] == ["https://live.example.com"]

    expired = await client.get("/api/links?status=expired")
    assert [x["original_url"] for x in expired.json()] == ["https://dead.example.com"]

    assert len((await client.get("/api/links")).json()) == 2
    assert (await client.get("/api/links?status=bogus")).status_code == 400


@pytest.mark.asyncio
async def test_list_links_filter_by_unused(client):
    await client.post("/api/shorten", json={"url": "https://never.example.com"})
    async with db_session_factory() as session:
        session.add(
            Link(original_url="https://clicked.example.com", short_code="hit00001", clicks=3)
        )
        await session.commit()

    unused = await client.get("/api/links?status=unused")
    assert [x["original_url"] for x in unused.json()] == ["https://never.example.com"]
    assert all(x["clicks"] == 0 for x in unused.json())


@pytest.mark.asyncio
async def test_list_links_filter_by_used(client):
    await client.post("/api/shorten", json={"url": "https://never.example.com"})
    async with db_session_factory() as session:
        session.add(
            Link(original_url="https://clicked.example.com", short_code="hit00001", clicks=3)
        )
        await session.commit()

    used = await client.get("/api/links?status=used")
    assert [x["original_url"] for x in used.json()] == ["https://clicked.example.com"]
    assert all(x["clicks"] > 0 for x in used.json())


@pytest.mark.asyncio
async def test_list_links_filter_by_permanent(client):
    await client.post("/api/shorten", json={"url": "https://temp.example.com"})
    await client.post(
        "/api/shorten", json={"url": "https://forever.example.com", "permanent": True}
    )

    perm = await client.get("/api/links?status=permanent")
    assert [x["original_url"] for x in perm.json()] == ["https://forever.example.com"]
    assert all(x["permanent"] for x in perm.json())


@pytest.mark.asyncio
async def test_list_links_search(client):
    await client.post("/api/shorten", json={"url": "https://github.com/qorexdevs"})
    await client.post("/api/shorten", json={"url": "https://example.com/blog",
                                            "custom_alias": "myblog"})

    by_url = await client.get("/api/links?q=github")
    assert [x["original_url"] for x in by_url.json()] == ["https://github.com/qorexdevs"]

    # the alias matches too, case-insensitively
    by_alias = await client.get("/api/links?q=MYBLOG")
    assert [x["short_code"] for x in by_alias.json()] == ["myblog"]

    assert (await client.get("/api/links?q=nomatch")).json() == []


@pytest.mark.asyncio
async def test_list_links_search_treats_wildcards_literally(client):
    await client.post("/api/shorten", json={"url": "https://example.com/50%off"})
    await client.post("/api/shorten", json={"url": "https://example.com/plain"})

    # "%" must match the literal char, not stand in for "anything"
    hits = await client.get("/api/links?q=50%25")
    assert [x["original_url"] for x in hits.json()] == ["https://example.com/50%off"]


@pytest.mark.asyncio
async def test_list_links_filter_by_min_clicks(client):
    codes = {}
    for url in ("https://a.example.com", "https://b.example.com", "https://c.example.com"):
        res = await client.post("/api/shorten", json={"url": url})
        codes[url] = res.json()["short_code"]

    for _ in range(3):
        await client.get(f"/{codes['https://a.example.com']}", follow_redirects=False)
    await client.get(f"/{codes['https://b.example.com']}", follow_redirects=False)

    res = await client.get("/api/links?min_clicks=2")
    assert res.status_code == 200
    assert [x["original_url"] for x in res.json()] == ["https://a.example.com"]
    assert res.headers["X-Total-Count"] == "1"

    # min_clicks=0 is the default and keeps every link, never-clicked included
    assert len((await client.get("/api/links?min_clicks=0")).json()) == 3
    assert (await client.get("/api/links?min_clicks=-1")).status_code == 400


@pytest.mark.asyncio
async def test_list_links_filter_by_max_clicks(client):
    codes = {}
    for url in ("https://a.example.com", "https://b.example.com", "https://c.example.com"):
        res = await client.post("/api/shorten", json={"url": url})
        codes[url] = res.json()["short_code"]

    for _ in range(3):
        await client.get(f"/{codes['https://a.example.com']}", follow_redirects=False)
    await client.get(f"/{codes['https://b.example.com']}", follow_redirects=False)

    # low-traffic links for pruning: b has 1 click, c has none
    res = await client.get("/api/links?max_clicks=1")
    assert res.status_code == 200
    assert sorted(x["original_url"] for x in res.json()) == [
        "https://b.example.com", "https://c.example.com",
    ]
    assert res.headers["X-Total-Count"] == "2"

    # pairs with min_clicks for an exact range
    res = await client.get("/api/links?min_clicks=1&max_clicks=1")
    assert [x["original_url"] for x in res.json()] == ["https://b.example.com"]

    # max_clicks=0 keeps only never-clicked links, default is unbounded
    assert [x["original_url"] for x in (await client.get("/api/links?max_clicks=0")).json()] == [
        "https://c.example.com",
    ]
    assert len((await client.get("/api/links")).json()) == 3
    assert (await client.get("/api/links?max_clicks=-1")).status_code == 400


@pytest.mark.asyncio
async def test_list_links_filter_by_created_range(client):
    for url in ("https://a.example.com", "https://b.example.com", "https://c.example.com"):
        await client.post("/api/shorten", json={"url": url})

    # everything was created just now, so a far-past floor keeps all of it
    res = await client.get("/api/links?created_after=2000-01-01")
    assert res.status_code == 200
    assert res.headers["X-Total-Count"] == "3"
    # a future floor drops everything, a future ceiling keeps everything
    assert len((await client.get("/api/links?created_after=2999-01-01")).json()) == 0
    assert len((await client.get("/api/links?created_before=2999-01-01")).json()) == 3
    assert len((await client.get("/api/links?created_before=2000-01-01")).json()) == 0
    # bounds pair into a window, and a tz-aware value is accepted
    res = await client.get(
        "/api/links?created_after=2000-01-01T00:00:00%2B00:00&created_before=2999-01-01"
    )
    assert res.headers["X-Total-Count"] == "3"
    assert (await client.get("/api/links?created_after=nope")).status_code == 400
    assert (await client.get("/api/links?created_before=2026-13-40")).status_code == 400


@pytest.mark.asyncio
async def test_list_links_filter_by_clicked_range(client):
    codes = {}
    for url in ("https://a.example.com", "https://b.example.com", "https://c.example.com"):
        res = await client.post("/api/shorten", json={"url": url})
        codes[url] = res.json()["short_code"]

    # click a and b, leave c never-clicked
    await client.get(f"/{codes['https://a.example.com']}", follow_redirects=False)
    await client.get(f"/{codes['https://b.example.com']}", follow_redirects=False)

    # a far-past floor keeps both clicked links but never drops in the never-clicked c
    res = await client.get("/api/links?clicked_after=2000-01-01")
    assert res.status_code == 200
    assert res.headers["X-Total-Count"] == "2"
    urls = {item["original_url"] for item in res.json()}
    assert urls == {"https://a.example.com", "https://b.example.com"}
    # a future floor drops everything, a future ceiling keeps the two clicked ones
    assert len((await client.get("/api/links?clicked_after=2999-01-01")).json()) == 0
    assert len((await client.get("/api/links?clicked_before=2999-01-01")).json()) == 2
    assert len((await client.get("/api/links?clicked_before=2000-01-01")).json()) == 0
    assert (await client.get("/api/links?clicked_after=nope")).status_code == 400


@pytest.mark.asyncio
async def test_list_links_filter_by_expires_range(client):
    # a expires in the future, b never expires (no ttl)
    await client.post("/api/shorten", json={"url": "https://a.example.com", "ttl_hours": 24})
    await client.post("/api/shorten", json={"url": "https://b.example.com"})

    # a past floor keeps the expiring link but drops the never-expiring one
    res = await client.get("/api/links?expires_after=2000-01-01")
    assert res.status_code == 200
    assert res.headers["X-Total-Count"] == "1"
    assert {item["original_url"] for item in res.json()} == {"https://a.example.com"}
    # a far-future ceiling keeps the expiring link, a far-future floor drops everything
    assert len((await client.get("/api/links?expires_before=2999-01-01")).json()) == 1
    assert len((await client.get("/api/links?expires_after=2999-01-01")).json()) == 0
    assert (await client.get("/api/links?expires_after=nope")).status_code == 400


@pytest.mark.asyncio
async def test_export_csv_filter_by_created_range(client):
    await client.post("/api/shorten", json={"url": "https://a.example.com"})
    res = await client.get("/api/links.csv?created_after=2999-01-01")
    assert res.status_code == 200
    assert len(res.text.strip().splitlines()) == 1  # header only
    assert (await client.get("/api/links.csv?created_after=nope")).status_code == 400
    assert (await client.get("/api/links.csv?clicked_after=nope")).status_code == 400


@pytest.mark.asyncio
async def test_list_links_rejects_bad_limit(client):
    assert (await client.get("/api/links?limit=0")).status_code == 400
    assert (await client.get("/api/links?limit=101")).status_code == 400


@pytest.mark.asyncio
async def test_list_links_rejects_negative_offset(client):
    assert (await client.get("/api/links?offset=-1")).status_code == 400


@pytest.mark.asyncio
async def test_delete_link(client):
    res = await client.post("/api/shorten", json={"url": "https://example.com"})
    code = res.json()["short_code"]

    res = await client.delete(f"/api/links/{code}")
    assert res.status_code == 204

    res = await client.get(f"/{code}", follow_redirects=False)
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_delete_link_case_insensitive(client):
    with patch("app.routers.api.generate_short_code", return_value="AbC123"):
        res = await client.post("/api/shorten", json={"url": "https://example.com"})
    assert res.status_code == 201

    res = await client.delete("/api/links/abc123")
    assert res.status_code == 204


@pytest.mark.asyncio
async def test_delete_link_not_found(client):
    res = await client.delete("/api/links/nope")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_purge_expired(client):
    res = await client.post(
        "/api/shorten", json={"url": "https://example.com", "ttl_hours": 1}
    )
    expiring = res.json()["short_code"]
    res = await client.post("/api/shorten", json={"url": "https://example.org"})
    permanent = res.json()["short_code"]

    future = datetime.now(timezone.utc) + timedelta(hours=2)
    with patch("app.queries.datetime") as mock_dt:
        mock_dt.now.return_value = future
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        res = await client.delete("/api/expired")
    assert res.status_code == 200
    assert res.json() == {"deleted": 1}

    assert (await client.get(f"/api/stats/{expiring}")).status_code == 404
    assert (await client.get(f"/api/stats/{permanent}")).status_code == 200


@pytest.mark.asyncio
async def test_purge_expired_none(client):
    await client.post("/api/shorten", json={"url": "https://example.com"})
    res = await client.delete("/api/expired")
    assert res.status_code == 200
    assert res.json() == {"deleted": 0}


@pytest.mark.asyncio
async def test_retarget_link(client):
    res = await client.post("/api/shorten", json={"url": "https://example.com"})
    code = res.json()["short_code"]

    res = await client.patch(f"/api/links/{code}", json={"url": "https://example.org/new"})
    assert res.status_code == 200
    assert res.json()["original_url"] == "https://example.org/new"

    res = await client.get(f"/{code}", follow_redirects=False)
    assert res.headers["location"] == "https://example.org/new"


@pytest.mark.asyncio
async def test_retarget_link_keeps_clicks(client):
    res = await client.post("/api/shorten", json={"url": "https://example.com"})
    code = res.json()["short_code"]
    await client.get(f"/{code}", follow_redirects=False)

    res = await client.patch(f"/api/links/{code}", json={"url": "https://example.org"})
    assert res.json()["clicks"] == 1


@pytest.mark.asyncio
async def test_retarget_link_rejects_bad_url(client):
    res = await client.post("/api/shorten", json={"url": "https://example.com"})
    code = res.json()["short_code"]

    res = await client.patch(f"/api/links/{code}", json={"url": "not a url"})
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_retarget_link_not_found(client):
    res = await client.patch("/api/links/nope", json={"url": "https://example.com"})
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_retarget_sets_expiry(client):
    res = await client.post("/api/shorten", json={"url": "https://example.com"})
    code = res.json()["short_code"]
    assert res.json()["expires_at"] is None

    res = await client.patch(f"/api/links/{code}", json={"ttl_hours": 24})
    assert res.status_code == 200
    assert res.json()["expires_at"] is not None
    assert res.json()["original_url"] == "https://example.com"


@pytest.mark.asyncio
async def test_retarget_url_and_ttl_together(client):
    res = await client.post("/api/shorten", json={"url": "https://example.com"})
    code = res.json()["short_code"]

    res = await client.patch(
        f"/api/links/{code}", json={"url": "https://example.org", "ttl_hours": 48}
    )
    assert res.json()["original_url"] == "https://example.org"
    assert res.json()["expires_at"] is not None


@pytest.mark.asyncio
async def test_retarget_empty_body_rejected(client):
    res = await client.post("/api/shorten", json={"url": "https://example.com"})
    code = res.json()["short_code"]

    res = await client.patch(f"/api/links/{code}", json={})
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_retarget_makes_link_permanent(client):
    res = await client.post(
        "/api/shorten", json={"url": "https://example.com", "ttl_hours": 24}
    )
    code = res.json()["short_code"]
    assert res.json()["expires_at"] is not None

    res = await client.patch(f"/api/links/{code}", json={"permanent": True})
    assert res.status_code == 200
    assert res.json()["permanent"] is True
    assert res.json()["expires_at"] is None


@pytest.mark.asyncio
async def test_retarget_permanent_and_ttl_conflict(client):
    res = await client.post("/api/shorten", json={"url": "https://example.com"})
    code = res.json()["short_code"]

    res = await client.patch(
        f"/api/links/{code}", json={"permanent": True, "ttl_hours": 24}
    )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_retarget_rejects_bad_ttl(client):
    res = await client.post("/api/shorten", json={"url": "https://example.com"})
    code = res.json()["short_code"]

    res = await client.patch(f"/api/links/{code}", json={"ttl_hours": 0})
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_bulk_shorten_multiple(client):
    res = await client.post(
        "/api/shorten/bulk",
        json={"urls": [{"url": "https://a.com"}, {"url": "https://b.com"}]},
    )
    assert res.status_code == 200
    results = res.json()["results"]
    assert len(results) == 2
    assert all(r["ok"] for r in results)
    assert results[0]["original_url"] == "https://a.com"
    assert len({r["short_code"] for r in results}) == 2


@pytest.mark.asyncio
async def test_bulk_shorten_partial_failure(client):
    res = await client.post(
        "/api/shorten/bulk",
        json={"urls": [{"url": "https://ok.com"}, {"url": "not-a-url"}]},
    )
    assert res.status_code == 200
    results = res.json()["results"]
    assert results[0]["ok"] is True
    assert results[1]["ok"] is False
    assert results[1]["short_code"] is None
    assert results[1]["error"]


@pytest.mark.asyncio
async def test_bulk_shorten_keeps_custom_alias(client):
    res = await client.post(
        "/api/shorten/bulk",
        json={"urls": [{"url": "https://x.com", "custom_alias": "mybulk"}]},
    )
    assert res.json()["results"][0]["short_code"] == "mybulk"


@pytest.mark.asyncio
async def test_bulk_shorten_duplicate_alias_in_batch(client):
    res = await client.post(
        "/api/shorten/bulk",
        json={
            "urls": [
                {"url": "https://x.com", "custom_alias": "dup"},
                {"url": "https://y.com", "custom_alias": "dup"},
            ]
        },
    )
    results = res.json()["results"]
    assert results[0]["ok"] is True
    assert results[1]["ok"] is False
    assert results[1]["error"] == "Alias already taken"


@pytest.mark.asyncio
async def test_bulk_shorten_empty_rejected(client):
    res = await client.post("/api/shorten/bulk", json={"urls": []})
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_bulk_shorten_too_many_rejected(client):
    res = await client.post(
        "/api/shorten/bulk",
        json={"urls": [{"url": "https://e.com"} for _ in range(101)]},
    )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_bulk_delete(client):
    codes = []
    for _ in range(3):
        res = await client.post("/api/shorten", json={"url": "https://example.com"})
        codes.append(res.json()["short_code"])

    res = await client.post("/api/links/bulk-delete", json={"codes": codes + ["nope"]})
    assert res.status_code == 200
    body = res.json()
    assert sorted(body["deleted"]) == sorted(codes)
    assert body["not_found"] == ["nope"]

    for code in codes:
        res = await client.get(f"/{code}", follow_redirects=False)
        assert res.status_code == 404


@pytest.mark.asyncio
async def test_bulk_delete_empty_rejected(client):
    res = await client.post("/api/links/bulk-delete", json={"codes": []})
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_bulk_delete_too_many_rejected(client):
    res = await client.post(
        "/api/links/bulk-delete",
        json={"codes": [f"c{i}" for i in range(101)]},
    )
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_summary_empty(client):
    res = await client.get("/api/summary")
    assert res.status_code == 200
    assert res.json() == {
        "total_links": 0, "total_clicks": 0, "active": 0, "expired": 0, "permanent": 0,
        "unused": 0, "custom": 0, "expiring_soon": 0, "created_recently": 0,
        "avg_clicks": 0.0, "busiest": None, "busiest_clicks": 0, "busiest_share": 0.0,
    }


@pytest.mark.asyncio
async def test_summary_counts(client):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    past = now - timedelta(hours=1)
    soon = now + timedelta(hours=12)
    async with db_session_factory() as session:
        session.add_all([
            Link(original_url="https://live.example.com", short_code="live0001",
                 custom_alias="live0001", clicks=3),
            Link(original_url="https://perm.example.com", short_code="perm0001",
                 permanent=True, clicks=2),
            Link(original_url="https://dead.example.com", short_code="dead0001",
                 expires_at=past, clicks=5),
            Link(original_url="https://fresh.example.com", short_code="fresh001", clicks=0),
            Link(original_url="https://soon.example.com", short_code="soon0001",
                 expires_at=soon, clicks=1),
        ])
        await session.commit()

    res = await client.get("/api/summary")
    assert res.json() == {
        "total_links": 5, "total_clicks": 11, "active": 3, "expired": 1, "permanent": 1,
        "unused": 1, "custom": 1, "expiring_soon": 1, "created_recently": 5,
        "avg_clicks": 2.2, "busiest": "dead0001", "busiest_clicks": 5, "busiest_share": 0.45,
    }


@pytest.mark.asyncio
async def test_summary_created_recently_excludes_old(client):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    async with db_session_factory() as session:
        session.add_all([
            Link(original_url="https://new.example.com", short_code="new00001"),
            Link(original_url="https://old.example.com", short_code="old00001",
                 created_at=now - timedelta(days=2)),
        ])
        await session.commit()

    res = await client.get("/api/summary")
    assert res.json()["created_recently"] == 1


@pytest.mark.asyncio
async def test_dashboard_page(client):
    async with db_session_factory() as session:
        session.add(Link(original_url="https://x.example.com", short_code="busy0001", clicks=9))
        session.add(Link(original_url="https://y.example.com", short_code="cold0001", clicks=0))
        await session.commit()

    res = await client.get("/dashboard")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    body = res.text
    assert "Dashboard" in body
    # busiest link gets rendered as a link to its stats page, with its click count
    assert "/stats/busy0001" in body
    assert "busy0001 (9 clicks, 100% of all)" in body
    # the top-links list shows clicked links but skips never-clicked ones
    assert "Top Links" in body
    assert "9 clicks" in body
    assert "cold0001" not in body


@pytest.mark.asyncio
async def test_shorten_reuse_returns_same_code(client):
    first = await client.post(
        "/api/shorten", json={"url": "https://example.com", "reuse": True}
    )
    assert first.json()["reused"] is False
    code = first.json()["short_code"]

    second = await client.post(
        "/api/shorten", json={"url": "https://example.com", "reuse": True}
    )
    assert second.json()["short_code"] == code
    assert second.json()["reused"] is True


@pytest.mark.asyncio
async def test_shorten_without_reuse_makes_new_code(client):
    first = await client.post("/api/shorten", json={"url": "https://example.com"})
    second = await client.post("/api/shorten", json={"url": "https://example.com"})
    assert first.json()["short_code"] != second.json()["short_code"]


@pytest.mark.asyncio
async def test_shorten_reuse_matches_trimmed_url(client):
    first = await client.post(
        "/api/shorten", json={"url": "https://example.com", "reuse": True}
    )
    code = first.json()["short_code"]

    second = await client.post(
        "/api/shorten", json={"url": "  https://example.com  ", "reuse": True}
    )
    assert second.json()["short_code"] == code
    assert second.json()["reused"] is True


@pytest.mark.asyncio
async def test_shorten_reuse_skips_custom_alias(client):
    await client.post(
        "/api/shorten",
        json={"url": "https://example.com", "custom_alias": "named", "reuse": True},
    )
    res = await client.post(
        "/api/shorten", json={"url": "https://example.com", "reuse": True}
    )
    assert res.json()["short_code"] != "named"
    assert res.json()["reused"] is False


@pytest.mark.asyncio
async def test_shorten_reuse_ignores_expired_link(client):
    past = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=1)
    async with db_session_factory() as session:
        session.add(
            Link(original_url="https://example.com", short_code="exp00001", expires_at=past)
        )
        await session.commit()

    res = await client.post(
        "/api/shorten", json={"url": "https://example.com", "reuse": True}
    )
    assert res.json()["short_code"] != "exp00001"
    assert res.json()["reused"] is False
