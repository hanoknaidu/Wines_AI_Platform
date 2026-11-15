# syntax=docker/dockerfile:1

# =============================================================================
# Wines AI backend. Two stages: uv installs the locked dependency set into a
# virtualenv; the runtime stage copies only that virtualenv onto a clean slim
# image and runs uvicorn as a non-root uid. See DOCKER.md.
#
# python:3.12-slim (Debian bookworm), not alpine: every locked dependency ships
# a manylinux wheel, so no compiler is needed; musl would force source builds
# (onnxruntime, under the `retrieval` extra, has no musl wheel at all).
# 3.12 matches the dev .venv and the lockfile's floor.
# =============================================================================
FROM python:3.12.12-slim-bookworm AS build

# Pinned uv binary from its own image: nothing extra lands in the Python env.
COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Optional dependency sets, space-separated (pyproject [project.optional-dependencies]):
#   ""                      default - offline provider, hashed embedder, no network
#   "orchestrator"          lets WA_LLM_PROVIDER=anthropic work
#   "orchestrator retrieval" adds embedded Qdrant + fastembed ONNX models
ARG EXTRAS=""

# Manifest + lockfile first: this layer survives any edit under src/.
# --frozen installs exactly uv.lock and fails if pyproject has drifted.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project \
        $(for e in ${EXTRAS}; do printf -- '--extra %s ' "$e"; done)

# Then the project. The seed dataset (dataset/seed/*.json) is package data and
# ships inside the wheel.
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable \
        $(for e in ${EXTRAS}; do printf -- '--extra %s ' "$e"; done)


# =============================================================================
FROM python:3.12.12-slim-bookworm AS runtime

# Numeric uid so an AKS securityContext can assert runAsNonRoot / runAsUser.
RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid 10001 --no-create-home --shell /usr/sbin/nologin app

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# ---- runtime settings, all overridable (none are secrets) ------------------
# WORKERS must stay 1: the SSE bus, the in-flight turn registry, the seq
# allocator and the rate limiter are in-process, and SQLite takes one writer.
#
# The two path overrides are not optional. The code defaults resolve relative to
# the cwd (./var/wines.db) and to the installed package (ingest store), which in
# an image would mean writing inside the virtualenv. /data is the one writable
# place; mount a volume there to keep conversations and ingested tastes.
ENV PORT=8010 \
    WORKERS=1 \
    GRACEFUL_TIMEOUT=30 \
    FORWARDED_ALLOW_IPS="*" \
    WA_DATABASE_URL="sqlite+aiosqlite:////data/wines.db" \
    WA_INGEST_STORE_PATH=/data/ingested_tastes.jsonl \
    FASTEMBED_CACHE_PATH=/data/models \
    WA_COOKIE_SECURE=true

COPY --from=build --chown=app:app /app/.venv /app/.venv
RUN install -d -o app -g app /data

WORKDIR /app
USER 10001
EXPOSE 8010

# Liveness target. /api/v1/readyz is the readiness target (503 until the dataset
# is loaded and the db answers). urllib, because slim ships no curl.
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-c", "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:'+os.environ['PORT']+'/api/v1/healthz',timeout=4).read()"]

# exec: uvicorn becomes PID 1 and receives SIGTERM directly. --timeout-graceful-
# shutdown bounds the wait on open SSE streams so a stopping pod does not hang.
CMD ["sh", "-c", "exec uvicorn wines_ai.main:app \
    --host 0.0.0.0 \
    --port ${PORT} \
    --workers ${WORKERS} \
    --proxy-headers \
    --forwarded-allow-ips ${FORWARDED_ALLOW_IPS} \
    --timeout-graceful-shutdown ${GRACEFUL_TIMEOUT}"]
