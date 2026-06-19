<p align="center">
  <h1 align="center">URL Shortener</h1>
  <p align="center">A fast and simple URL shortener with a dark-themed web UI, custom aliases, and click tracking.</p>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-3776AB?style=flat&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/FastAPI-0.115-009688?style=flat&logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/SQLAlchemy-2.0-D71F00?style=flat&logo=sqlalchemy&logoColor=white" alt="SQLAlchemy">
  <img src="https://img.shields.io/badge/Jinja2-Templates-B41717?style=flat&logo=jinja&logoColor=white" alt="Jinja2">
  <img src="https://img.shields.io/badge/License-MIT-green?style=flat" alt="License">
</p>

---

## Features

- Shorten URLs with a single click
- Custom aliases like `/my-link`
- Click tracking with last-clicked timestamp
- Dark-themed responsive UI
- REST API for programmatic access
- QR code generation for any link
- Link preview to see a destination without counting a click
- Link expiration via `ttl_hours`
- Permanent (308) redirects opt-in, temporary (307) by default
- Reserved aliases block route collisions
- URL validation allows only `http://` and `https://` schemes
- Async SQLite (aiosqlite)

## Quick Start

```bash
# Clone the repository
git clone https://github.com/qorexdevs/url-shortener.git
cd url-shortener

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/macOS
venv\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements.txt

# Run the server
uvicorn app.main:app --reload
```

Open [http://localhost:8000](http://localhost:8000) in your browser.

### Docker

```bash
docker compose up -d
```

The database is stored in a named volume so your data persists across container restarts.

## API Documentation

### Shorten a URL

```http
POST /api/shorten
Content-Type: application/json
```

Only `http://` and `https://` URLs are accepted, including `localhost` and loopback IP addresses (`127.0.0.1`, `::1`). URLs longer than 2048 characters are rejected.

```json
{
  "url": "https://example.com/very/long/url",
  "custom_alias": "my-link",
  "ttl_hours": 24,
  "permanent": false
}
```

**Response:**

```json
{
  "original_url": "https://example.com/very/long/url",
  "short_url": "http://localhost:8000/my-link",
  "short_code": "my-link",
  "expires_at": "2025-01-02T00:00:00",
  "permanent": false
}
```

`expires_at` is `null` when no `ttl_hours` was set. Set `permanent: true` to redirect with a
cacheable 308 instead of the default 307. Browsers cache it, so later hits skip the server and
stop counting clicks.

### Get Link Stats

```http
GET /api/stats/{code}
```

```json
{
  "original_url": "https://example.com/very/long/url",
  "short_url": "http://localhost:8000/my-link",
  "short_code": "my-link",
  "clicks": 42,
  "created_at": "2025-01-01T00:00:00",
  "last_clicked": "2025-01-02T12:30:00",
  "expires_at": "2025-01-02T00:00:00",
  "expired": false
}
```

### List Links

```http
GET /api/links                    ->  newest first, 50 per page
GET /api/links?limit=20&offset=40 ->  page through them
GET /api/links?sort=clicks        ->  most clicked first
GET /api/links?status=active      ->  only links that haven't expired
GET /api/links?status=expired     ->  only links past their ttl
GET /api/links?q=github           ->  match the destination url, code or alias
```

Returns every link with the same fields as stats, newest first. `limit` is 1-100 (default 50) and `offset` skips that many rows, so `offset=limit` gets the next page. `sort` is `created` (default) or `clicks` for the most clicked first. `status` is `all` (default), `active`, or `expired`. 400 on a bad `limit`, a negative `offset`, an unknown `sort`, or an unknown `status`.

### Preview

```http
GET /api/preview/{code}
```

```json
{
  "short_url": "http://localhost:8000/my-link",
  "original_url": "https://example.com/very/long/url",
  "expires_at": "2025-01-02T00:00:00",
  "expired": false
}
```

Resolves where a short link points without following it. No click is counted and there is no redirect, so it is safe for checking a link before opening it. You can also append `+` to the short link itself (`GET /{code}+`) to get the same preview, the way bitly does.

### QR Code

```http
GET /api/qr/{code}                   ->  PNG image
GET /api/qr/{code}?fmt=svg            ->  SVG image
GET /api/qr/{code}?scale=20&border=2  ->  bigger image, tighter quiet zone
```

Returns a QR code image encoding the short URL. Useful for sharing links in print or presentations.
PNG by default; pass `fmt=svg` for a crisp, scalable vector you can drop into print or the web.
`scale` sets the pixel size of each module (1-40, default 10) and `border` the quiet zone width (0-20, default 4).

### Retarget

```http
PATCH /api/links/{code}
{ "url": "https://example.org/new", "ttl_hours": 24 }
```

Updates an existing link in place, keeping its code, alias and click count. Send `url` to point it somewhere new, `ttl_hours` to reset the expiry window from now, or both. At least one is required. The URL is validated and normalized like on shorten, and `ttl_hours` follows the same bounds. Returns the updated stats, 400 on a bad URL, bad ttl or an empty body, 404 if nothing matches.

### Delete

```http
DELETE /api/links/{code}  ->  204 No Content
```

Removes a short link by its code or custom alias. Returns 404 if nothing matches. The code lookup is case-insensitive, same as the other endpoints.

### Purge expired

```http
DELETE /api/expired  ->  { "deleted": 3 }
```

Drops every link that's past its ttl in one pass and returns how many were removed. Links without a ttl are left alone. Handy for a cron job or a manual cleanup so expired rows don't pile up.

### Redirect

```http
GET /{code}   ->  307 redirect to original URL (308 for a permanent link)
GET /{code}+  ->  preview the destination instead of following it
```

## Configuration

| Variable | Default | Description |
|---|---|---|
| `BASE_URL` | `http://localhost:8000` | Base URL for generated short links |
| `DATABASE_URL` | `sqlite+aiosqlite:///./shortener.db` | Database connection string |

## Project Structure

```
url-shortener/
|-- app/
|   |-- __init__.py
|   |-- main.py              # FastAPI application entry point
|   |-- config.py            # Settings and configuration
|   |-- database.py          # Async engine and session
|   |-- models.py            # SQLAlchemy URL model
|   |-- schemas.py           # Pydantic schemas
|   |-- utils.py             # Short code generation
|   |-- routers/
|   |   |-- __init__.py
|   |   |-- api.py           # REST API endpoints
|   |   `-- pages.py         # Web UI routes
|   |-- templates/
|   |   |-- base.html        # Base layout
|   |   |-- index.html       # Main page (shorten form)
|   |   `-- stats.html       # Link statistics page
|   `-- static/
|       |-- css/style.css    # Dark theme styles
|       `-- js/main.js       # Frontend logic
|-- Dockerfile
|-- docker-compose.yml
|-- requirements.txt
|-- .gitignore
`-- README.md
```

## Tech Stack

| Component | Technology |
|---|---|
| Framework | FastAPI 0.115 |
| ORM | SQLAlchemy 2.0 (async) |
| Database | SQLite via aiosqlite |
| Templates | Jinja2 |
| Frontend | Vanilla HTML/CSS/JS |
| Server | Uvicorn |

## License

MIT


---

<p align="center">
  <sub>developed by <a href="https://github.com/qorexdevs">qorex</a></sub>
  <br>
  <sub>
    <a href="https://github.com/qorexdevs">GitHub</a> | <a href="https://t.me/qorexdev">Telegram</a>
  </sub>
</p>
