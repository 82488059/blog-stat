"""Lightweight site/page PV & UV counter for static Hexo blog (Windows-friendly)."""

from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import time
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Iterator
from urllib.parse import unquote, urlparse

from fastapi import FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("STAT_DATA_DIR", BASE_DIR / "data"))
DB_PATH = DATA_DIR / "stats.db"

# Ignore accidental double-submit (same IP + path). 0 = count every refresh (busuanzi-like).
DEBOUNCE_SECONDS = int(os.environ.get("STAT_DEBOUNCE_SECONDS", "0"))

# Required to access GET /api/stat/pages. Empty = endpoint disabled (404).
PAGES_TOKEN = (os.environ.get("STAT_PAGES_TOKEN") or "").strip()

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
    r"(bot|spider|crawl|slurp|bingpreview|facebookexternalhit|wget|curl|python-requests)",
    re.I,
)

# Keep file-like paths (tools/*.html etc.); treat others as directory pages.
FILE_EXT_RE = re.compile(
    r"\.(html?|xml|json|txt|js|css|png|jpe?g|gif|webp|ico|svg|pdf|zip|gz|md)$",
    re.I,
)

app = FastAPI(title="blog-stat", docs_url=None, redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


class StatPayload(BaseModel):
    path: str = Field(default="/", max_length=512)


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


def _normalize_path(path: str) -> str:
    """Canonical page key: decode, strip index.html, unify trailing slash for dirs."""
    path = (path or "/").strip() or "/"
    if path.startswith("http://") or path.startswith("https://"):
        path = urlparse(path).path or "/"
    path = unquote(path)
    if not path.startswith("/"):
        path = "/" + path
    path = path.split("?", 1)[0].split("#", 1)[0]

    lower = path.lower()
    if lower.endswith("/index.html"):
        path = path[: -len("index.html")]
    elif lower.endswith("index.html"):
        path = path[: -len("index.html")] or "/"

    if path != "/" and not path.endswith("/") and not FILE_EXT_RE.search(path):
        path += "/"

    if len(path) > 512:
        path = path[:512]
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
    return bool(BOT_UA.search(ua))


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
    """List per-page PV. Disabled unless STAT_PAGES_TOKEN is set and matches."""
    if not PAGES_TOKEN:
        raise HTTPException(status_code=404, detail="Not Found")
    provided = (x_stat_token or token or "").strip()
    if provided != PAGES_TOKEN:
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
