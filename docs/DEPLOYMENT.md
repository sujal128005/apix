# Deployment

APIx runs as two processes: PostgreSQL and a single Python application that
serves both the JSON API and the website. There is no Node toolchain, no build
step and no CDN, so a deployment cannot fail because an asset did not download.

---

## Local

```powershell
docker compose up -d                           # PostgreSQL 16 on 127.0.0.1:5433
py -3.12 -m venv .venv
.venv\Scripts\pip install -e ".[dev]"
.venv\Scripts\python scripts\init_db.py        # migrate and seed
.venv\Scripts\pytest -q                        # expect 815 passed
```

```powershell
$env:APIX_CONTACT_URL="https://github.com/your-name/apix"
$env:PYTHONPATH="apps"
.venv\Scripts\python -m uvicorn api.main:app --port 8000
```

On Linux or macOS use `python3.12` and `.venv/bin/`.

---

## Environment

| Variable | Required | Default | Notes |
|---|---|---|---|
| `APIX_CONTACT_URL` | **yes** | — | Contact address in the crawler's User-Agent. **Without it the compliance gate refuses every request.** APIx does not crawl anonymously. |
| `APIX_DB_HOST` | no | `127.0.0.1` | |
| `APIX_DB_PORT` | no | `5433` | 5433, not 5432, to avoid colliding with an existing local Postgres |
| `APIX_DB_NAME` | no | `apix` | |
| `APIX_APP_USER` / `APIX_APP_PASSWORD` | no | dev defaults | The application role. Cannot `UPDATE` or `DELETE` append-only tables. |
| `APIX_MIGRATOR_USER` / `APIX_MIGRATOR_PASSWORD` | no | dev defaults | Owns schema. Needed for migrations and for `--reset`. |
| `APIX_CORS_ORIGINS` | no | localhost | Comma-separated allow-list. Never `*`. |
| `APIX_RATE_LIMIT_PER_MINUTE` | no | `600` | Per process. Behind several workers the effective limit multiplies. |
| `APIX_DEFAULT_CRAWL_DELAY` | no | `5.0` | **May be raised, never lowered.** Load fails otherwise. |
| `APIX_DAILY_REQUEST_BUDGET` | no | `200` | **May be lowered, never raised.** |

Compliance settings are one-directional on purpose: a safeguard that can be
relaxed under deadline pressure is not a safeguard.

**Never commit `.env`.** `.env.example` is committed with no values.

---

## Production notes

**Run migrations as the migrator role, serve as the application role.** The
application role cannot modify append-only tables — that is the immutability
guarantee, and running the app as the owner would silently discard it.

```bash
python -m alembic -c db/alembic.ini upgrade head     # migrator
uvicorn api.main:app --host 0.0.0.0 --port 8000      # app role
```

**Terminate TLS in front of the app.** Uvicorn is not the right place for it.
Keep `X-Forwarded-*` handling on at the proxy and pass the real client IP, or
the rate limiter sees one client.

**One worker, or accept a multiplied rate limit.** The limiter is in-process.
With four workers the effective limit is four times what is configured. If that
matters, move it to the proxy.

**Back up before every migration.** Index observations are append-only; a bad
migration is not something you can edit your way out of, which is the point.

```bash
pg_dump -h HOST -U apix_migrator apix > apix-$(date +%F).sql
```

---

## Scheduled collection

The daily job is in `packages/collector/scheduler.py`. It runs in **IST**,
because collection dates and T+N travel dates are defined in IST; scheduling in
UTC would shift which day a "daily" run belongs to.

```python
from collector.scheduler import CollectionSchedule, start_scheduler

scheduler = start_scheduler(
    engine,
    run_collection=...,
    compute_index=...,
    schedule=CollectionSchedule(hour=6, minute=0),
)
```

One run at a time (`max_instances=1`), missed runs coalesce rather than
stampede, and a failed run is recorded without killing the schedule.

For a single-server deployment, a cron entry calling the job directly is an
equally valid choice and one fewer moving part.

---

## Health

| Endpoint | Use |
|---|---|
| `/api/v1/health` | Liveness. No database. Exempt from rate limiting. |
| `/api/v1/ready` | Readiness. Checks the database and returns 503 if unreachable. |
| `/api/v1/operations` | Freshness, source status, recent runs, alerts. |

Point an uptime check at `/api/v1/ready`, not `/health` — the latter returns 200
with the database down.

---

## What to verify after deploying

1. `/api/v1/ready` returns 200.
2. `/` renders and the tables have data.
3. `/api/v1/operations` reports freshness as `CURRENT`.
4. Security headers are present: `curl -I https://host/api/v1/health` should
   show `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` and a CSP.
5. `APIX_CONTACT_URL` is set — otherwise collection silently collects nothing,
   and the run log will say so.
