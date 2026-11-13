from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

BACKEND = Path(__file__).resolve().parents[1]
SRC = BACKEND / "src"
sys.path.insert(0, str(SRC))

# The suite's ranking assertions were written against the dependency-free retrieval
# path. The Qdrant + cross-encoder path has its own tests (test_workflows_rag.py),
# which opt in explicitly and skip when the `retrieval` extra is not installed.
os.environ.setdefault("WA_RETRIEVAL_BACKEND", "local")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])




def _isolate_env(monkeypatch):
    """Cut the test suite off from the developer's own `.env`.

    `Settings` reads `.env` relative to the working directory, which is `backend/`
    when pytest runs - so the moment a real credential lands in that file, the suite
    starts behaving differently on one machine than another. A test that passes
    because of a key on someone's laptop is worse than no test: the provider-fallback
    tests below assert what happens when a key is ABSENT, and they silently stopped
    testing that the first time one was present.

    Called explicitly at the top of each settings fixture rather than as an autouse
    fixture, because ordering against the fixture that builds `Settings` has to be
    guaranteed, not hoped for.
    """
    from wines_ai.config import Settings

    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for name in ("WA_ANTHROPIC_API_KEY", "WA_LLM_PROVIDER", "WA_ENGINE",
                 "WA_REQUIRE_LLM_PROVIDER", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def settings(tmp_path, monkeypatch):
    from wines_ai.config import get_settings

    _isolate_env(monkeypatch)
    monkeypatch.setenv("WA_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/test.db")
    monkeypatch.setenv("WA_INGEST_STORE_PATH", str(tmp_path / "ingested.jsonl"))
    monkeypatch.setenv("WA_STREAM_TOKEN_DELAY_MS", "0")
    monkeypatch.setenv("WA_RATE_LIMIT_TURNS_PER_MIN", "500")
    monkeypatch.setenv("WA_RATE_LIMIT_READS_PER_MIN", "2000")
    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


@pytest.fixture
def demo_settings(tmp_path, monkeypatch):
    """Settings pointed at the demo artifact, which is the real deployment seam.

    Nothing in the app changes to serve it - `WA_DATASET_PATH` is the whole switch, as
    section 9 promised - so this fixture is also the test that the promise holds.
    """
    from wines_ai.config import get_settings
    from wines_ai.dataset.build_demo import OUT as DEMO_ARTIFACT

    _isolate_env(monkeypatch)
    monkeypatch.setenv("WA_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/test.db")
    monkeypatch.setenv("WA_INGEST_STORE_PATH", str(tmp_path / "ingested.jsonl"))
    monkeypatch.setenv("WA_DATASET_PATH", str(DEMO_ARTIFACT))
    monkeypatch.setenv("WA_STREAM_TOKEN_DELAY_MS", "0")
    monkeypatch.setenv("WA_RATE_LIMIT_TURNS_PER_MIN", "500")
    monkeypatch.setenv("WA_RATE_LIMIT_READS_PER_MIN", "2000")
    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


@pytest.fixture
async def demo_client(demo_settings):
    from wines_ai.main import create_app

    app = create_app(demo_settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest.fixture
async def demo_aged(demo_client):
    r = await demo_client.post("/api/v1/age-gate", json={"confirmed": True})
    assert r.status_code == 204
    return demo_client


@pytest.fixture
async def client(settings):
    """ASGI client with lifespan driven explicitly.

    Note: httpx's ASGITransport buffers the whole response body, so it cannot read an
    endless SSE stream - the `server` fixture below exists for that.
    """
    from wines_ai.main import create_app

    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            yield c


@pytest.fixture
async def aged(client):
    """A client that has confirmed age."""
    r = await client.post("/api/v1/age-gate", json={"confirmed": True})
    assert r.status_code == 204
    return client


@pytest.fixture(scope="session")
def server(tmp_path_factory):
    """A real uvicorn process - the only way to exercise streaming responses."""
    port = _free_port()
    db = tmp_path_factory.mktemp("sse") / "sse.db"
    env = {
        **{k: v for k, v in os.environ.items() if k != "WA_ANTHROPIC_API_KEY"},
        # Same isolation as `_isolate_env`, for the child process: it runs with
        # `cwd=backend`, so it would otherwise read the developer's `.env` too.
        "WA_ENGINE": "deterministic",
        "WA_LLM_PROVIDER": "offline",
        "WA_DATABASE_URL": f"sqlite+aiosqlite:///{db}",
        "WA_INGEST_STORE_PATH": str(db.parent / "ingested.jsonl"),
        "WA_STREAM_TOKEN_DELAY_MS": "3",
        "WA_RATE_LIMIT_TURNS_PER_MIN": "500",
        "WA_RATE_LIMIT_READS_PER_MIN": "2000",
        "PYTHONPATH": str(SRC),
    }
    proc = subprocess.Popen(
        [
            sys.executable, "-m", "uvicorn", "wines_ai.main:app",
            "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning",
        ],
        cwd=str(BACKEND), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{port}"
    for _ in range(120):
        try:
            if httpx.get(f"{base}/api/v1/healthz", timeout=1).status_code == 200:
                break
        except Exception:  # noqa: BLE001
            time.sleep(0.25)
    else:
        proc.kill()
        raise RuntimeError(f"server did not start: {proc.stdout.read().decode()[-2000:]}")
    yield base
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()


class Sse:
    """Minimal SSE reader that mirrors how a browser EventSource consumes the stream."""

    def __init__(self, base: str, client: httpx.AsyncClient) -> None:
        self.base = base
        self.client = client

    async def read(
        self,
        cid: str,
        after: int,
        *,
        until: str = "done",
        timeout: float = 20.0,  # noqa: ASYNC109 - a test reader, not library code
    ):
        import json

        events: list[dict] = []

        async def rd():
            url = f"{self.base}/api/v1/conversations/{cid}/stream?after={after}"
            async with self.client.stream("GET", url) as r:
                assert r.status_code == 200, r.status_code
                buf = ""
                async for chunk in r.aiter_text():
                    buf += chunk
                    while "\n\n" in buf:
                        raw, buf = buf.split("\n\n", 1)
                        if raw.startswith(": "):
                            continue
                        ev: dict = {}
                        for line in raw.split("\n"):
                            if line.startswith("id: "):
                                ev["seq"] = int(line[4:])
                            elif line.startswith("event: "):
                                ev["name"] = line[7:]
                            elif line.startswith("data: "):
                                ev["data"] = json.loads(line[6:])
                        if ev:
                            events.append(ev)
                        if ev.get("name") == until:
                            return

        try:
            await asyncio.wait_for(rd(), timeout=timeout)
        except TimeoutError:
            pass
        return events


@pytest.fixture
async def sse(server):
    async with httpx.AsyncClient(timeout=25.0) as c:
        await c.post(f"{server}/api/v1/age-gate", json={"confirmed": True})
        yield Sse(server, c), c


@pytest.fixture
def orchestrated_settings(tmp_path, monkeypatch):
    """The lane-3 serving path, with no credentials.

    `WA_ENGINE=orchestrated` is the whole switch - the routes, the schemas and the
    frontend do not know it was flipped. The provider stays `offline`, so the full
    A-to-K pipeline runs with no key and no network.
    """
    from wines_ai.config import get_settings

    _isolate_env(monkeypatch)
    monkeypatch.setenv("WA_DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path}/test.db")
    monkeypatch.setenv("WA_INGEST_STORE_PATH", str(tmp_path / "ingested.jsonl"))
    monkeypatch.setenv("WA_ENGINE", "orchestrated")
    monkeypatch.setenv("WA_STREAM_TOKEN_DELAY_MS", "0")
    monkeypatch.setenv("WA_RATE_LIMIT_TURNS_PER_MIN", "500")
    monkeypatch.setenv("WA_RATE_LIMIT_READS_PER_MIN", "2000")
    get_settings.cache_clear()
    yield get_settings()
    get_settings.cache_clear()


@pytest.fixture
async def orchestrated_aged(orchestrated_settings):
    from wines_ai.main import create_app

    app = create_app(orchestrated_settings)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            r = await c.post("/api/v1/age-gate", json={"confirmed": True})
            assert r.status_code == 204
            yield c
