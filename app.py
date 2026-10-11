"""Lightweight site/page PV & UV counter for static Hexo blog (Windows-friendly)."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import sqlite3
import time
from collections import defaultdict
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from threading import Lock
from typing import Iterator
from urllib.parse import unquote, urlparse

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("STAT_DATA_DIR", BASE_DIR / "data"))
DB_PATH = DATA_DIR / "stats.db"

# Ignore accidental double-submit (same IP + path). 0 = count every refresh (busuanzi-like).
DEBOUNCE_SECONDS = int(os.environ.get("STAT_DEBOUNCE_SECONDS", "0"))

# Required to access GET /api/stat/pages. Empty = endpoint disabled (404).
PAGES_TOKEN = (os.environ.get("STAT_PAGES_TOKEN") or "").strip()

# Per-IP rate limit for mutating requests (POST). 0 = disabled.
RATE_LIMIT_WINDOW = int(os.environ.get("STAT_RATE_LIMIT_WINDOW", "60"))
RATE_LIMIT_MAX = int(os.environ.get("STAT_RATE_LIMIT_MAX", "120"))

# Max JSON body size for POST (bytes).
MAX_BODY_BYTES = int(os.environ.get("STAT_MAX_BODY_BYTES", "4096"))

MAX_PATH_LEN = 512

ALLOWED_ORIGINS = [
    o.strip()
    for o in (
        os.environ.get(
            "STAT_CORS_ORIGINS",
            "https://www.xssl.online,https://xssl.online,"
            "http://www.xssl.online,http://xssl.online,"
            "https://82488059.github.io",
        )
    ).split(",")
    if o.strip()
]

BOT_UA = re.compile(
    r"(bot|spider|crawl|slurp|bingpreview|facebookexternalhit|wget|curl|"
    r"python-requests|scrapy|httpclient|java/|go-http|okhttp|libwww|"
    r"phantomjs|headlesschrome|selenium|puppeteer|playwright|"
    r"axios/|node-fetch|httpie|aiohttp|undici|feedfetcher|preview)",
    re.I,
)

# Keep file-like paths (tools/*.html etc.); treat others as directory pages.
FILE_EXT_RE = re.compile(
    r"\.(html?|xml|json|txt|js|css|png|jpe?g|gif|webp|ico|svg|pdf|zip|gz|md)$",
    re.I,
)

# Control chars (incl. NUL) and other unsafe path markers.
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")

app = FastAPI(
    title="blog-stat",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

_rate_lock = Lock()
_rate_hits: dict[str, list[float]] = defaultdict(list)


class StatPayload(BaseModel):
    path: str = Field(default="/", max_length=MAX_PATH_LEN)


class LimitBodySizeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method in ("POST", "PUT", "PATCH"):
            cl = request.headers.get("content-length")
            if cl is not None:
                try:
                    size = int(cl)
                except ValueError:
                    return JSONResponse({"detail": "Invalid Content-Length"}, status_code=400)
                if size > MAX_BODY_BYTES:
                    return JSONResponse({"detail": "Payload too large"}, status_code=413)
        return await call_next(request)


app.add_middleware(LimitBodySizeMiddleware)


def _ensure_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS page_pv (
                path TEXT PRIMARY KEY,
                pv INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS uv_day (
                day TEXT NOT NULL,
                visitor TEXT NOT NULL,
                PRIMARY KEY (day, visitor)
            );
            CREATE TABLE IF NOT EXISTS hit_debounce (
                visitor TEXT NOT NULL,
                path TEXT NOT NULL,
                ts REAL NOT NULL,
                PRIMARY KEY (visitor, path)
            );
            INSERT OR IGNORE INTO meta(key, value) VALUES ('site_pv', 0);
            INSERT OR IGNORE INTO meta(key, value) VALUES ('site_uv', 0);
            """
        )


@contextmanager
def _connect() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(DB_PATH, timeout=30)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        yield conn
        conn.commit()
    finally:
        conn.close()


def _client_ip(request: Request) -> str:
    # Trust only nginx-set X-Real-IP ($remote_addr). Do not use client X-Forwarded-For.
    real_ip = (request.headers.get("x-real-ip") or "").strip()
    if real_ip:
        return real_ip
    if request.client:
        return request.client.host
    return "unknown"


def _visitor_id(ip: str) -> str:
    return hashlib.sha256(f"{ip}|{date.today().isoformat()}".encode()).hexdigest()[:32]


def _rate_limited(ip: str) -> bool:
    """Return True if this IP exceeded the POST rate budget."""
    if RATE_LIMIT_MAX <= 0 or RATE_LIMIT_WINDOW <= 0:
        return False
    now = time.time()
    cutoff = now - RATE_LIMIT_WINDOW
    with _rate_lock:
        hits = _rate_hits[ip]
        hits = [t for t in hits if t > cutoff]
        if len(hits) >= RATE_LIMIT_MAX:
            _rate_hits[ip] = hits
            return True
        hits.append(now)
        _rate_hits[ip] = hits
        # Bound memory: drop idle keys occasionally.
        if len(_rate_hits) > 10000:
            stale = [k for k, v in _rate_hits.items() if not v or v[-1] < cutoff]
            for k in stale[:5000]:
                _rate_hits.pop(k, None)
        return False


def _is_safe_path_candidate(raw: str) -> bool:
    if not raw or len(raw) > MAX_PATH_LEN:
        return False
    if _CONTROL_RE.search(raw):
        return False
    if "\\" in raw:
        return False
    # Reject "." / ".." as path segments (traversal / noise).
    for seg in raw.replace("\\", "/").split("/"):
        if seg in (".", ".."):
            return False
    return True


def _normalize_path(path: str) -> str:
    """Canonical page key: decode, strip index.html, unify trailing slash for dirs.

    Rejects traversal, backslashes, control characters, and overlong paths.
    """
    path = (path or "/").strip() or "/"
    if not _is_safe_path_candidate(path):
        raise HTTPException(status_code=400, detail="Invalid path")

    if path.startswith("http://") or path.startswith("https://"):
        path = urlparse(path).path or "/"
        if not _is_safe_path_candidate(path):
            raise HTTPException(status_code=400, detail="Invalid path")

    path = unquote(path)
    if not _is_safe_path_candidate(path):
        raise HTTPException(status_code=400, detail="Invalid path")

    path = path.split("?", 1)[0].split("#", 1)[0]
    if not path.startswith("/"):
        path = "/" + path

    parts = [p for p in path.split("/") if p]
    if any(p in (".", "..") for p in parts):
        raise HTTPException(status_code=400, detail="Invalid path")
    path = "/" + "/".join(parts) if parts else "/"

    lower = path.lower()
    if lower.endswith("/index.html"):
        path = path[: -len("index.html")]
    elif lower.endswith("index.html"):
        path = path[: -len("index.html")] or "/"

    if path != "/" and not path.endswith("/") and not FILE_EXT_RE.search(path):
        path += "/"

    if len(path) > MAX_PATH_LEN:
        raise HTTPException(status_code=400, detail="Invalid path")
    return path or "/"


def _path_aliases(path: str) -> list[str]:
    """Possible historical keys for the same page (before canonicalization)."""
    canon = _normalize_path(path)
    aliases = {canon}
    if canon == "/":
        aliases.update({"/index.html", "/index.htm"})
    elif FILE_EXT_RE.search(canon):
        # Real file pages (e.g. /tools/json.html) — no slash variants.
        pass
    elif canon.endswith("/"):
        bare = canon.rstrip("/")
        aliases.update({bare, canon + "index.html", bare + "/index.html"})
    return [a for a in aliases if a]


def _is_bot(request: Request) -> bool:
    ua = request.headers.get("user-agent") or ""
    if not ua.strip():
        # Empty UA is common for scrapers; treat as bot for write path.
        return True
    return bool(BOT_UA.search(ua))


def _token_matches(provided: str) -> bool:
    """Constant-time compare against STAT_PAGES_TOKEN. Never log the token."""
    if not PAGES_TOKEN:
        return False
    # Hash to fixed length so compare_digest never raises on length mismatch.
    a = hashlib.sha256(provided.encode("utf-8")).digest()
    b = hashlib.sha256(PAGES_TOKEN.encode("utf-8")).digest()
    return hmac.compare_digest(a, b)


def _get_page_pv(conn: sqlite3.Connection, path: str) -> int:
    """Read page PV; merge split alias rows into the canonical key."""
    canon = _normalize_path(path)
    aliases = _path_aliases(canon)
    placeholders = ",".join("?" for _ in aliases)
    rows = conn.execute(
        f"SELECT path, pv FROM page_pv WHERE path IN ({placeholders})",
        aliases,
    ).fetchall()
    if not rows:
        return 0

    total = sum(int(pv) for _, pv in rows)
    # Consolidate onto canonical path so later hits stay on one key.
    conn.execute(
        f"DELETE FROM page_pv WHERE path IN ({placeholders}) AND path != ?",
        (*aliases, canon),
    )
    conn.execute(
        "INSERT INTO page_pv(path, pv) VALUES(?, ?) "
        "ON CONFLICT(path) DO UPDATE SET pv = excluded.pv",
        (canon, total),
    )
    return total


def _bump_page_pv(conn: sqlite3.Connection, path: str) -> int:
    current = _get_page_pv(conn, path)
    canon = _normalize_path(path)
    new_val = current + 1
    conn.execute(
        "INSERT INTO page_pv(path, pv) VALUES(?, ?) "
        "ON CONFLICT(path) DO UPDATE SET pv = excluded.pv",
        (canon, new_val),
    )
    return new_val


def _read_counts(conn: sqlite3.Connection, path: str) -> dict:
    site_pv = conn.execute("SELECT value FROM meta WHERE key='site_pv'").fetchone()[0]
    site_uv = conn.execute("SELECT value FROM meta WHERE key='site_uv'").fetchone()[0]
    page_pv = _get_page_pv(conn, path)
    return {
        "site_pv": site_pv,
        "site_uv": site_uv,
        "page_pv": page_pv,
        "path": _normalize_path(path),
    }


@app.on_event("startup")
def on_startup() -> None:
    _ensure_db()


@app.get("/api/stat/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/stat/pages")
def list_pages(
    limit: int = Query(default=50, ge=1, le=500),
    x_stat_token: str | None = Header(default=None, alias="X-Stat-Token"),
    token: str | None = Query(default=None),
) -> dict:
    """List per-page PV. Disabled unless STAT_PAGES_TOKEN is set and matches.

    Missing/wrong token always returns 404 (no oracle). Token is never logged.
    """
    if not PAGES_TOKEN:
        raise HTTPException(status_code=404, detail="Not Found")
    provided = (x_stat_token or token or "").strip()
    if not _token_matches(provided):
        raise HTTPException(status_code=404, detail="Not Found")
    with _connect() as conn:
        rows = conn.execute(
            "SELECT path, pv FROM page_pv ORDER BY pv DESC LIMIT ?",
            (limit,),
        ).fetchall()
        total_pages = conn.execute("SELECT COUNT(*) FROM page_pv").fetchone()[0]
    return {
        "total_pages": total_pages,
        "pages": [{"path": p, "page_pv": pv} for p, pv in rows],
    }


@app.get("/api/stat")
def get_stat(path: str = "/") -> dict:
    path = _normalize_path(path)
    with _connect() as conn:
        return _read_counts(conn, path)


@app.post("/api/stat")
def post_stat(payload: StatPayload, request: Request) -> dict:
    path = _normalize_path(payload.path)
    if _is_bot(request):
        with _connect() as conn:
            return _read_counts(conn, path)

    ip = _client_ip(request)
    if _rate_limited(ip):
        raise HTTPException(status_code=429, detail="Too Many Requests")

    visitor = _visitor_id(ip)
    now = time.time()
    day = date.today().isoformat()

    with _connect() as conn:
        row = conn.execute(
            "SELECT ts FROM hit_debounce WHERE visitor=? AND path=?",
            (visitor, path),
        ).fetchone()
        should_count_pv = row is None or (now - float(row[0])) >= DEBOUNCE_SECONDS

        if should_count_pv:
            conn.execute(
                "INSERT INTO hit_debounce(visitor, path, ts) VALUES(?,?,?) "
                "ON CONFLICT(visitor, path) DO UPDATE SET ts=excluded.ts",
                (visitor, path, now),
            )
            conn.execute("UPDATE meta SET value = value + 1 WHERE key='site_pv'")
            _bump_page_pv(conn, path)

        uv_row = conn.execute(
            "SELECT 1 FROM uv_day WHERE day=? AND visitor=?",
            (day, visitor),
        ).fetchone()
        if uv_row is None:
            conn.execute(
                "INSERT INTO uv_day(day, visitor) VALUES(?, ?)",
                (day, visitor),
            )
            conn.execute("UPDATE meta SET value = value + 1 WHERE key='site_uv'")

        return _read_counts(conn, path)
