# Deploying APIx

A live URL, in about thirty minutes. Any container host works; Render is written
out because it provides managed PostgreSQL alongside the service.

**Why not a serverless platform.** APIx is a long-running process with a
database and a scheduler. On serverless the scheduler has nothing to run in
between invocations, and each cold start opens a new database connection unless
a pooler sits in front. Both are solvable and neither is worth solving for a
prototype.

---

## Render

1. Push to GitHub — done.
2. Sign in at `render.com` with GitHub.
3. **New → Blueprint**, pick the repo. It reads `render.yaml` and creates the
   web service and a PostgreSQL 16 instance.
4. Set the two variables it asks for:

   | Variable | Value |
   |---|---|
   | `APIX_CONTACT_URL` | `https://github.com/sujal128005/apix` |
   | `APIX_CORS_ORIGINS` | your Render URL, e.g. `https://apix.onrender.com` |

   Everything else is wired from the database or generated.
5. Deploy. The health check points at `/api/v1/ready`, which fails until the
   database is migrated — expected on first boot.

### After the first deploy

Open a shell on the service:

```bash
python -m alembic -c db/alembic.ini upgrade head
python -c "from db.seed import seed_all; seed_all()"
```

`/api/v1/ready` turns green once migrations finish.

**Note that `scripts/` is not in the image.** The demo pipeline cannot be run in
production, by design — the container carries no path from synthetic data to a
published figure, and `APIX_ENV=production` refuses to load the mock adapter
even if it were present.

So a production deployment starts **empty**, and the dashboard says so. That is
correct: there is no permitted live source yet, and an empty production system is
more honest than one seeded with generated fares.

---

## Two deployments, not one

| | Purpose | `APIX_ENV` | Data |
|---|---|---|---|
| **Demo** | Judging, walkthroughs | `development` | 21 days simulated, labelled `SIMULATED_DEMO` |
| **Production** | The eventual live index | `production` | Empty until a source agreement exists |

For SIH, deploy the **demo**. It shows the whole system working end to end. Use
the standard Docker build with `APIX_ENV=development`, include `scripts/`, and
run the pipeline once after migrating:

```bash
python scripts/run_demo_pipeline.py --days 21 --reset
```

Every page will carry its `SIMULATED_DEMO` provenance tags, the headline index
will stay withheld, and the banner will explain why. That is the demo — a system
that refuses to publish an unjustifiable number, demonstrated rather than
described.

---

## Any other host

The requirements are small:

- PostgreSQL 16
- A persistent process, not a lambda
- The environment variables in `docs/DEPLOYMENT.md`
- Port 8000, or `PORT` honoured by your platform

```bash
docker build -t apix .
docker run -p 8000:8000 --env-file .env apix
```

---

## After it is live

1. `/api/v1/ready` returns 200.
2. All eight pages render: `/`, `/routes`, `/heatmap`, `/lead-time`,
   `/scenario`, `/quality`, `/methodology`, `/operations`.
3. Security headers present:
   `curl -I https://your-url/api/v1/health`
4. `/api/v1/operations` reports freshness.
5. Put the URL in the repository description and the README.

---

## What deployment does not change

The data is still simulated. A live URL makes the system *visible*, not *valid*.

Both remain true and should be said in the same breath: the pipeline is real and
running, and it has never seen a real fare, because no source APIx is permitted
to collect from currently exists. `docs/DATA-REQUEST.md` is what changes the
second half.
