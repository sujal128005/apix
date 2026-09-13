# APIx production image.
#
# Two stages so the runtime carries no build toolchain: a compiler present in a
# deployed image is attack surface that serves no purpose once the wheels are
# built, and a CERT-In audit will ask about it.

FROM python:3.12-slim AS build

# Build-only dependencies. psycopg needs libpq to compile; the runtime needs
# only the shared library, which is installed separately in the final stage.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY pyproject.toml README.md ./
COPY packages/ packages/
COPY db/ db/
COPY apps/ apps/

RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir .


FROM python:3.12-slim AS runtime

RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 curl \
    && rm -rf /var/lib/apt/lists/*

# Never run as root. A container escape from an unprivileged process is a
# considerably smaller problem than one from root.
RUN useradd --create-home --shell /usr/sbin/nologin --uid 10001 apix

COPY --from=build /opt/venv /opt/venv
WORKDIR /app
COPY --chown=apix:apix packages/ packages/
COPY --chown=apix:apix apps/ apps/
COPY --chown=apix:apix db/ db/
COPY --chown=apix:apix data/reference/ data/reference/

# Demo tooling is deliberately absent from the image. `scripts/` contains the
# demo pipeline and the mock adapter's entry points, and the production guard in
# schemas/environment.py refuses to load them anyway - but the surest way to
# keep synthetic data out of a published statistic is for it not to be shipped.

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH="/app/packages:/app/apps" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APIX_ENV=production

USER apix
EXPOSE 8000

# Readiness, not liveness: /health returns 200 with the database down, so an
# orchestrator watching it would route traffic to an instance that cannot serve.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/api/v1/ready || exit 1

# One worker by default. The rate limiter is in-process, so N workers give N
# times the configured limit; scale with replicas behind a proxy that rate-limits
# at the edge, or raise APIX_RATE_LIMIT_PER_MINUTE knowingly.
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
