"""Import site_uv / site_pv / page_pv from busuanzi into local SQLite."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote, urlparse

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_DB = Path(__file__).resolve().parent / "data" / "stats.db"
BUSUANZI_URL = "https://busuanzi.ibruce.info/busuanzi?jsonpCallback=cb"
JSONP_RE = re.compile(r"cb\s*\(\s*(\{.*?\})\s*\)\s*;", re.S)


FILE_EXT_RE = re.compile(
    r"\.(html?|xml|json|txt|js|css|png|jpe?g|gif|webp|ico|svg|pdf|zip|gz|md)$",
    re.I,
)


def normalize_path(url_or_path: str) -> str:
    raw = (url_or_path or "/").strip() or "/"
    if raw.startswith("http://") or raw.startswith("https://"):
        raw = urlparse(raw).path or "/"
    raw = unquote(raw)
    if not raw.startswith("/"):
        raw = "/" + raw
    raw = raw.split("?", 1)[0].split("#", 1)[0]
    lower = raw.lower()
    if lower.endswith("/index.html"):
        raw = raw[: -len("index.html")]
    elif lower.endswith("index.html"):
        raw = raw[: -len("index.html")] or "/"
    if raw != "/" and not raw.endswith("/") and not FILE_EXT_RE.search(raw):
        raw += "/"
    return raw or "/"


def fetch_busuanzi(referer: str, timeout: float = 20.0, retries: int = 5) -> dict:
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                BUSUANZI_URL,
                headers={
                    "Referer": referer,
                    "User-Agent": "Mozilla/5.0 (compatible; blog-stat-import/1.0)",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                text = resp.read().decode("utf-8", errors="replace")
            m = JSONP_RE.search(text)
            if not m:
                raise RuntimeError(f"unexpected busuanzi response for {referer}: {text[:200]}")
            return json.loads(m.group(1))
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, RuntimeError, json.JSONDecodeError) as e:
            last_err = e
            # Back off hard on 502/503 from busuanzi.
            sleep_s = min(30.0, 1.5 * (2 ** attempt))
            time.sleep(sleep_s)
    assert last_err is not None
    raise last_err


def ensure_db(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
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
    return conn


def set_meta_max(conn: sqlite3.Connection, key: str, value: int) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = CASE "
        "WHEN excluded.value > value THEN excluded.value ELSE value END",
        (key, int(value)),
    )


def set_page_pv_max(conn: sqlite3.Connection, path: str, pv: int) -> None:
    conn.execute(
        "INSERT INTO page_pv(path, pv) VALUES(?, ?) "
        "ON CONFLICT(path) DO UPDATE SET pv = CASE "
        "WHEN excluded.pv > pv THEN excluded.pv ELSE pv END",
        (path, int(pv)),
    )


def load_urls(site: str, sitemap: str | None, urls_file: str | None) -> list[str]:
    urls: list[str] = []
    if urls_file:
        for line in Path(urls_file).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                urls.append(line)
    elif sitemap:
        xml_text: str
        if sitemap.startswith("http://") or sitemap.startswith("https://"):
            with urllib.request.urlopen(sitemap, timeout=30) as resp:
                xml_text = resp.read().decode("utf-8", errors="replace")
        else:
            xml_text = Path(sitemap).read_text(encoding="utf-8")
        root = ET.fromstring(xml_text)
        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        locs = [el.text.strip() for el in root.findall("sm:url/sm:loc", ns) if el.text]
        if not locs:
            locs = [el.text.strip() for el in root.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}loc") if el.text]
        urls.extend(locs)
    if site.rstrip("/") + "/" not in urls and site.rstrip("/") not in urls:
        urls.insert(0, site if site.endswith("/") else site + "/")
    # de-dupe keep order
    seen = set()
    out = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync busuanzi counters into local stats.db")
    parser.add_argument("--site", default="http://www.xssl.online/", help="Site origin / homepage URL")
    parser.add_argument("--sitemap", default="", help="Sitemap URL or local path (import all page_pv)")
    parser.add_argument("--urls-file", default="", help="Optional text file with one URL per line")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite db path")
    parser.add_argument("--delay", type=float, default=0.35, help="Delay between busuanzi requests")
    parser.add_argument("--site-only", action="store_true", help="Only import site_uv/site_pv (+ homepage page_pv)")
    args = parser.parse_args()

    site = args.site if args.site.endswith("/") else args.site + "/"
    sitemap = args.sitemap
    if not args.site_only and not sitemap and not args.urls_file:
        sitemap = site.rstrip("/") + "/sitemap.xml"

    urls = [site] if args.site_only else load_urls(site, sitemap or None, args.urls_file or None)
    print(f"importing {len(urls)} URL(s) from busuanzi -> {args.db}")

    conn = ensure_db(Path(args.db))
    ok = 0
    fail = 0
    site_uv = site_pv = None

    for i, url in enumerate(urls, 1):
        try:
            data = fetch_busuanzi(url)
            path = normalize_path(url)
            page_pv = int(data.get("page_pv") or 0)
            set_page_pv_max(conn, path, page_pv)

            # Site totals: take from first successful homepage-ish fetch,
            # then keep the max observed (requests themselves bump busuanzi a bit).
            cur_uv = int(data.get("site_uv") or 0)
            cur_pv = int(data.get("site_pv") or 0)
            site_uv = cur_uv if site_uv is None else max(site_uv, cur_uv)
            site_pv = cur_pv if site_pv is None else max(site_pv, cur_pv)

            ok += 1
            if i == 1 or i % 20 == 0 or i == len(urls):
                print(f"[{i}/{len(urls)}] {path} page_pv={page_pv} site_uv={cur_uv} site_pv={cur_pv}")
            conn.commit()
        except (urllib.error.URLError, TimeoutError, RuntimeError, json.JSONDecodeError) as e:
            fail += 1
            print(f"[{i}/{len(urls)}] FAIL {url}: {e}", file=sys.stderr)
        time.sleep(max(args.delay, 0))

    if site_uv is not None:
        set_meta_max(conn, "site_uv", site_uv)
    if site_pv is not None:
        set_meta_max(conn, "site_pv", site_pv)
    conn.commit()

    row_uv = conn.execute("SELECT value FROM meta WHERE key='site_uv'").fetchone()[0]
    row_pv = conn.execute("SELECT value FROM meta WHERE key='site_pv'").fetchone()[0]
    pages = conn.execute("SELECT COUNT(*), COALESCE(SUM(pv),0) FROM page_pv").fetchone()
    conn.close()

    print(
        f"done. ok={ok} fail={fail} | site_uv={row_uv} site_pv={row_pv} | "
        f"pages={pages[0]} sum_page_pv={pages[1]}"
    )
    print(f"copy {args.db} to the Windows Server STAT_DATA_DIR if imported on another machine.")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
