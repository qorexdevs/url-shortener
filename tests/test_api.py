from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest


@pytest.mark.asyncio
async def test_shorten_url(client):
    res = await client.post("/api/shorten", json={"url": "https://example.com"})
    assert res.status_code == 200
    data = res.json()
    assert data["original_url"] == "https://example.com"
    assert "short_url" in data
    assert len(data["short_code"]) == 6


@pytest.mark.asyncio
async def test_shorten_with_custom_alias(client):
    res = await client.post(
        "/api/shorten", json={"url": "https://example.com", "custom_alias": "mylink"}
    )
    assert res.status_code == 200
    assert res.json()["short_code"] == "mylink"


@pytest.mark.asyncio
async def test_shorten_duplicate_alias(client):
    payload = {"url": "https://example.com", "custom_alias": "taken"}
    await client.post("/api/shorten", json=payload)
    res = await client.post("/api/shorten", json=payload)
    assert res.status_code == 409


@pytest.mark.asyncio
async def test_shorten_invalid_url(client):
    res = await client.post("/api/shorten", json={"url": "not-a-url"})
    assert res.status_code == 400


@pytest.mark.asyncio
async def test_shorten_invalid_alias(client):
    res = await client.post(
        "/api/shorten", json={"url": "https://example.com", "custom_alias": "ab"}
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
async def test_redirect_not_found(client):
    res = await client.get("/nonexistent", follow_redirects=False)
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
async def test_stats_not_found(client):
    res = await client.get("/api/stats/nope")
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_redirect_increments_clicks(client):
    res = await client.post("/api/shorten", json={"url": "https://example.com"})
    code = res.json()["short_code"]

    for _ in range(3):
        await client.get(f"/{code}", follow_redirects=False)

    res = await client.get(f"/api/stats/{code}")
    assert res.json()["clicks"] == 3


@pytest.mark.asyncio
async def test_custom_alias_redirect(client):
    await client.post(
        "/api/shorten", json={"url": "https://github.com", "custom_alias": "gh-link"}
    )
    res = await client.get("/gh-link", follow_redirects=False)
    assert res.status_code == 307
    assert res.headers["location"] == "https://github.com"


@pytest.mark.asyncio
async def test_shorten_with_ttl(client):
    res = await client.post(
        "/api/shorten", json={"url": "https://example.com", "ttl_hours": 24}
    )
    assert res.status_code == 200
    code = res.json()["short_code"]

    stats = await client.get(f"/api/stats/{code}")
    data = stats.json()
    assert data["expires_at"] is not None
    assert data["expired"] is False


@pytest.mark.asyncio
async def test_expired_link_returns_410(client):
    res = await client.post(
        "/api/shorten", json={"url": "https://example.com", "ttl_hours": 1}
    )
    code = res.json()["short_code"]

    future = datetime.now(timezone.utc) + timedelta(hours=2)
    with patch("app.routers.api.datetime") as mock_dt:
        mock_dt.now.return_value = future
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        res = await client.get(f"/{code}", follow_redirects=False)
        assert res.status_code == 410


@pytest.mark.asyncio
async def test_stats_shows_expired(client):
    res = await client.post(
        "/api/shorten", json={"url": "https://example.com", "ttl_hours": 1}
    )
    code = res.json()["short_code"]

    future = datetime.now(timezone.utc) + timedelta(hours=2)
    with patch("app.routers.api.datetime") as mock_dt:
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
    assert len(res.content) > 100


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
