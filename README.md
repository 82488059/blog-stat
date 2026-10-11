# blog-stat

Lightweight site/page PV & UV counter for a static Hexo blog. FastAPI + SQLite, Windows-friendly.

Split out from the blog monorepo so the stats API can be deployed and versioned on its own.

## Features

- Site PV / UV and per-page PV
- CORS for blog origins
- Bot UA filtering
- Optional debounce (`STAT_DEBOUNCE_SECONDS`)
- Optional admin list endpoint (`GET /api/stat/pages` when `STAT_PAGES_TOKEN` is set)
- `import_busuanzi.py` to seed counts from busuanzi

## Quick start (Windows)

```bat
run.bat
```

Creates `.venv` if needed, installs deps, binds `127.0.0.1:3001`.

Or manually:

```bat
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
set STAT_DATA_DIR=%CD%\data
.venv\Scripts\python -m uvicorn app:app --host 127.0.0.1 --port 3001
```

Health check: `GET http://127.0.0.1:3001/api/stat/health`

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

| Variable | Default | Meaning |
|----------|---------|---------|
| `STAT_DATA_DIR` | `./data` | SQLite directory (`stats.db`) |
| `STAT_CORS_ORIGINS` | `https://www.xssl.online,https://xssl.online,http://www.xssl.online,http://xssl.online,https://82488059.github.io` | Comma-separated CORS origins |
| `STAT_DEBOUNCE_SECONDS` | `0` | Ignore same IP+path hits within N seconds; `0` = count every refresh |
| `STAT_PAGES_TOKEN` | _(empty)_ | If set, enables `GET /api/stat/pages` (header `X-Stat-Token` or query `token`) |

## API

- `GET /api/stat/health` — liveness
- `GET /api/stat?path=/` — read counts
- `POST /api/stat` — body `{"path":"/"}`; increments PV/UV
- `GET /api/stat/pages?limit=50` — per-page PV list (token required)

## Import from busuanzi

```bat
.venv\Scripts\python import_busuanzi.py --help
```

## Optional tools

Scripts under `tools/` are blog content analysis utilities (image/ref health, CSDN URL cleanup). They are **not** required to run the stats service.

## Data

SQLite lives in `data/stats.db` (gitignored). Keep an empty `data/` via `.gitkeep`.
