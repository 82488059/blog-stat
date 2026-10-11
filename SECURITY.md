# Security

Deployment and hardening notes for **blog-stat** (public GitHub repo; treat as internet-facing once proxied).

## Bind and reverse proxy

- Run uvicorn on **`127.0.0.1:3001` only** (`run.bat` / `run.sh` / systemd unit). Never bind `0.0.0.0`.
- Put **nginx** (or similar) in front; proxy `/api/` to `http://127.0.0.1:3001`.
- Do **not** open port 3001 on the firewall or publish it to the internet.
- Set `proxy_set_header X-Real-IP $remote_addr;` so visitor IPs are trustworthy. The app intentionally ignores client-supplied `X-Forwarded-For`.

## Secrets and data

- No tokens or passwords are hardcoded. Set secrets via environment variables (or a local `.env` that is **gitignored**).
- `STAT_PAGES_TOKEN` — long random value if you enable `GET /api/stat/pages`. Wrong/missing token returns **404** (not 401) to avoid oracles. Comparison is constant-time; the token is never logged.
- Never commit `stats.db`, `.env`, or real tokens. See `.gitignore` and `.env.example`.

## CORS

- Default allow-list is the known blog origins only (not `*`).
- Extend with `STAT_CORS_ORIGINS` (comma-separated). Keep this tight to your real front-end origins.

## Abuse controls

| Control | Default | Env |
|---------|---------|-----|
| Path validation | reject `..`, `\`, control chars, overlong paths | — |
| Bot UA filter (+ empty UA) | on for POST writes | — |
| Per-IP POST rate limit | 120 / 60s | `STAT_RATE_LIMIT_MAX`, `STAT_RATE_LIMIT_WINDOW` |
| POST body size | 4096 bytes | `STAT_MAX_BODY_BYTES` |
| Debounce | off (`0`) | `STAT_DEBOUNCE_SECONDS` |

Prefer nginx `limit_req` in addition to the in-app limiter for multi-process deployments (in-memory limits are per process).

## API surface

- FastAPI `/docs`, `/redoc`, and `/openapi.json` are **disabled**.
- `tools/` scripts are **local CLI only**. They are not mounted by uvicorn. Some can rewrite markdown under a blog `source/` tree — never expose them on a public host. See `tools/README.md`.

## Checklist before going live

1. `STAT_CORS_ORIGINS` matches production HTTPS origins.
2. `STAT_PAGES_TOKEN` set (or leave empty to keep `/api/stat/pages` disabled).
3. Process listens on `127.0.0.1` only; nginx terminates TLS.
4. `data/*.db` is outside git and backed up privately.
5. Firewall: no inbound to 3001 from the WAN.
