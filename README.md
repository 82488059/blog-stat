# blog-stat

Lightweight site/page PV & UV counter for a static Hexo blog. FastAPI + SQLite, Windows-friendly.

Split out from the blog monorepo so the stats API can be deployed and versioned on its own.

> **Security:** this repo is public. Read [SECURITY.md](SECURITY.md) before deploying. Bind **127.0.0.1** only; never expose port 3001 directly.

## Features

- Site PV / UV and per-page PV
- CORS allow-list for blog origins (configurable via `STAT_CORS_ORIGINS`)
- Bot / empty-UA filtering on write path
- Path sanitization (no `..` / control chars / backslash tricks)
- Per-IP POST rate limit and body size cap
- Optional debounce (`STAT_DEBOUNCE_SECONDS`)
- Optional admin list endpoint (`GET /api/stat/pages` when `STAT_PAGES_TOKEN` is set)
- `import_busuanzi.py` to seed counts from busuanzi

## Quick start (Windows)

```bat
run.bat
```

Creates `.venv` if needed, installs deps, binds **`127.0.0.1:3001`** (localhost only).

Or manually:

```bat
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
set STAT_DATA_DIR=%CD%\data
.venv\Scripts\python -m uvicorn app:app --host 127.0.0.1 --port 3001
```

Do **not** pass `--host 0.0.0.0`. Health check: `GET http://127.0.0.1:3001/api/stat/health`

## Quick start (Linux)

```bash
chmod +x run.sh
./run.sh
```

Same bind: **`127.0.0.1:3001`**. Manual:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
export STAT_DATA_DIR="$PWD/data"
.venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 3001
```

### systemd (optional)

Example unit: [`deploy/blog-stat.service`](deploy/blog-stat.service). Adjust `WorkingDirectory` / user, then:

```bash
sudo cp deploy/blog-stat.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now blog-stat
```

Still put nginx in front; do not open port 3001 on the firewall.


## nginx

Proxy `/api/` to the local service (do not expose 3001 publicly):

```nginx
location /api/ {
    proxy_pass http://127.0.0.1:3001;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

The app trusts `X-Real-IP` from nginx for visitor identity.

## Environment variables (`STAT_*`)

See also `.env.example` (placeholders only).

| Variable | Default | Meaning |
|----------|---------|---------|
| `STAT_DATA_DIR` | `./data` | SQLite directory (`stats.db`) |
| `STAT_CORS_ORIGINS` | known blog HTTPS/HTTP origins | Comma-separated CORS origins (**not** `*`) |
| `STAT_DEBOUNCE_SECONDS` | `0` | Ignore same IP+path hits within N seconds; `0` = count every refresh |
| `STAT_PAGES_TOKEN` | _(empty)_ | If set, enables `GET /api/stat/pages` (header `X-Stat-Token` or query `token`) |
| `STAT_RATE_LIMIT_WINDOW` | `60` | Rate-limit window seconds for POST |
| `STAT_RATE_LIMIT_MAX` | `120` | Max POSTs per IP per window (`0` = off) |
| `STAT_MAX_BODY_BYTES` | `4096` | Max POST body size |

## API

- `GET /api/stat/health` — liveness
- `GET /api/stat?path=/` — read counts
- `POST /api/stat` — body `{"path":"/"}`; increments PV/UV
- `GET /api/stat/pages?limit=50` — per-page PV list (token required; otherwise 404)

Interactive docs (`/docs`, `/openapi.json`) are disabled.

## Import from busuanzi

```bat
.venv\Scripts\python import_busuanzi.py --help
```

## Optional tools (`tools/`)

Scripts under `tools/` are **local-only** blog content analysis / cleanup utilities (image/ref health, CSDN URL cleanup). They can read or **rewrite** markdown under a Hexo `source/` tree.

- **Not** part of the stats HTTP service
- **Not** mounted by uvicorn
- **Do not** run or expose them on a public server

See [tools/README.md](tools/README.md).

## Data

SQLite lives in `data/stats.db` (gitignored). Keep an empty `data/` via `.gitkeep`.
