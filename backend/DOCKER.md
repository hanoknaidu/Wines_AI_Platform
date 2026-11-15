# Running the backend in Docker

Two-stage build: `uv sync --frozen` installs the locked dependencies into a
virtualenv, and the runtime stage copies only that onto `python:3.12.12-slim-bookworm`
and runs uvicorn as uid 10001. No uv, lockfile, tests or secrets in the shipped
image. **200MB** (linux/amd64, default extras).

## Build

```bash
cd "Wines AI Platform/backend"
docker build --platform linux/amd64 -t wines-ai-backend:local .
# with the real models:
docker build --platform linux/amd64 --build-arg EXTRAS="orchestrator retrieval" \
  -t wines-ai-backend:local-full .
```

`--platform linux/amd64` builds for AKS nodes; on Apple Silicon it runs under
emulation (slower, but identical). Drop it for a faster native arm64 dev image.

## Run

```bash
cp .env.docker.example .env.docker      # git-ignored; set WA_COOKIE_SECRET
docker volume create wines-data
docker run -d --platform linux/amd64 --name wines-ai-backend \
  -p 8010:8010 --env-file .env.docker -v wines-data:/data \
  wines-ai-backend:local
```

The volume is optional: without it the container is fully disposable (the
dataset is baked into the package), but conversations and ingested tastes are
lost on restart.

### Environment variables

All read by `Settings` (`src/wines_ai/config.py`) under the `WA_` prefix, except
the uvicorn ones. **Nothing is strictly required to boot**; one thing is required
to be safe:

| Variable | Default in image | Notes |
|---|---|---|
| `WA_COOKIE_SECRET` | `dev-only-change-me` | **Set it.** Signs session and age-gate cookies; the default is public. |
| `WA_COOKIE_SECURE` | `true` | Set `false` when reached over plain http (localhost), or the browser never returns the cookie. |
| `WA_CORS_ORIGINS` | localhost:5180/3000 | JSON list of browser origins. |
| `WA_ENGINE` | `deterministic` | or `orchestrated` |
| `WA_LLM_PROVIDER` | `offline` | `anthropic` needs `WA_ANTHROPIC_API_KEY` **and** `EXTRAS` incl. `orchestrator`. |
| `WA_ANTHROPIC_API_KEY` | — | Secret. Runtime only (`--env-file` / AKS Secret). |
| `WA_REQUIRE_LLM_PROVIDER` | `false` | `true` makes `/readyz` fail instead of silently falling back to offline. |
| `PORT` / `WORKERS` / `GRACEFUL_TIMEOUT` | `8010` / `1` / `30` | **Keep `WORKERS=1`** — SSE bus, turn registry, rate limiter are in-process; SQLite has one writer. |
| `WA_DATABASE_URL` | `sqlite+aiosqlite:////data/wines.db` | Overridden from the code default (cwd-relative). |
| `WA_INGEST_STORE_PATH` | `/data/ingested_tastes.jsonl` | Overridden: the code default resolves inside the installed package. |
| `FASTEMBED_CACHE_PATH` | `/data/models` | Only used with the `retrieval` extra. |

The remaining tuning knobs (model ids, cost ceilings, retrieval params) are listed
in `.env.example`.

## Check it works

```bash
curl -s localhost:8010/api/v1/healthz             # liveness  -> {"status":"ok"}
curl -s localhost:8010/api/v1/readyz | jq         # readiness -> 503 until dataset + db are up
open http://localhost:8010/docs                   # Swagger UI (/openapi.json)
curl -s localhost:8010/api/v1/meta/dataset-version | jq

# real flow: confirm age (sets a cookie), then start a conversation
curl -s -c jar -b jar -X POST localhost:8010/api/v1/age-gate \
  -H 'content-type: application/json' -d '{"confirmed":true}'
curl -s -c jar -b jar -X POST localhost:8010/api/v1/conversations \
  -H 'content-type: application/json' -d '{}' | jq
```

## Logs, shell, cleanup

```bash
docker logs -f wines-ai-backend                   # JSON lines on stdout
docker exec -it wines-ai-backend sh               # shell as uid 10001
docker stop wines-ai-backend                      # SIGTERM -> clean lifespan shutdown
docker rm wines-ai-backend
docker volume rm wines-data                       # deletes conversations + ingested tastes
docker image rm wines-ai-backend:local
```

## Models

The default image downloads nothing: the offline provider, BM25 and the hashed
embedder are pure Python. Only with `EXTRAS` containing `retrieval` (and
`WA_RETRIEVAL_BACKEND` `auto`/`qdrant`) does fastembed fetch
`BAAI/bge-base-en-v1.5` and `BAAI/bge-reranker-base` (ONNX, a few hundred MB) at
startup — then the corpus is embedded into an in-memory Qdrant.

**Recommendation: load at runtime into `FASTEMBED_CACHE_PATH` on a volume.**
Keeps the image small and the default build model-free; downloads once per
volume. Bake them in (a `RUN python -c "from fastembed import TextEmbedding; ..."`
layer) only if the cluster has no egress to HuggingFace or cold-start time
matters more than image size — the cost is a ~0.5–1GB larger image per model bump.

## AKS notes

- **Probes:** liveness `/api/v1/healthz`, readiness `/api/v1/readyz` (real 503 when not ready), port 8010.
- **Stateless-ish:** runs fine with no volume; with SQLite on `/data` it's one replica + one worker. Multi-replica needs Postgres and an external SSE bus.
- **SIGTERM:** uvicorn is PID 1 via `exec`; verified 0.55s clean stop, exit 0.
- **Non-root:** `runAsUser: 10001`, `runAsNonRoot: true`.
