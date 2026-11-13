"""Contract tests over the ASGI app (no streaming - see test_sse.py for that)."""

from __future__ import annotations

import asyncio
import uuid

import pytest

KEY = lambda: {"Idempotency-Key": uuid.uuid4().hex}  # noqa: E731


# --- age gate ------------------------------------------------------------

@pytest.mark.parametrize(
    "method,path",
    [
        ("post", "/api/v1/conversations"),
        ("get", "/api/v1/conversations"),
        ("get", "/api/v1/conversations/c-1"),
        ("post", "/api/v1/conversations/c-1/messages"),
        ("get", "/api/v1/conversations/c-1/stream"),
        ("post", "/api/v1/turns/t-1/cancel"),
        ("post", "/api/v1/messages/m-1/feedback"),
    ],
)
async def test_every_chat_route_is_gated(client, method, path):
    kwargs = {"json": {}} if method in ("post", "patch") else {}
    r = await getattr(client, method)(path, **kwargs)
    assert r.status_code == 403
    assert r.json()["code"] == "age_not_confirmed"


@pytest.mark.parametrize(
    "path",
    ["/api/v1/healthz", "/api/v1/readyz", "/api/v1/meta/taste-axes",
     "/api/v1/meta/dataset-version", "/openapi.json"],
)
async def test_open_routes_need_no_age_gate(client, path):
    assert (await client.get(path)).status_code == 200


async def test_age_gate_requires_explicit_confirmation(client):
    r = await client.post("/api/v1/age-gate", json={"confirmed": False})
    assert r.status_code == 400 and r.json()["code"] == "age_not_confirmed"


async def test_forged_age_cookie_is_rejected(client):
    client.cookies.set("wa_age", "1")
    r = await client.post("/api/v1/conversations", json={})
    assert r.status_code == 403, "an unsigned cookie must not pass the guard"


async def test_every_response_carries_a_request_id(client):
    r = await client.post("/api/v1/conversations", json={})
    assert r.headers["X-Request-Id"].startswith("req-")
    assert r.json()["request_id"] == r.headers["X-Request-Id"]


# --- conversations -------------------------------------------------------

async def test_create_and_fetch(aged):
    r = await aged.post("/api/v1/conversations", json={})
    assert r.status_code == 201
    body = r.json()
    assert body["title"] == "New conversation"
    assert body["dataset_version"] == "seed-0.1"
    r = await aged.get(f"/api/v1/conversations/{body['id']}")
    assert r.status_code == 200
    assert r.json()["taste_profile"]["style"] is None
    assert r.json()["dataset_version_stale"] is False


async def test_unknown_conversation_404s(aged):
    assert (await aged.get("/api/v1/conversations/c-nope")).status_code == 404


async def test_keyset_pagination_has_no_overlap(aged):
    for i in range(7):
        await aged.post("/api/v1/conversations", json={"title": f"c{i}"})
    seen: list[str] = []
    cursor = None
    for _ in range(5):
        url = "/api/v1/conversations?limit=3" + (f"&cursor={cursor}" if cursor else "")
        page = (await aged.get(url)).json()
        seen += [i["id"] for i in page["items"]]
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert len(seen) == len(set(seen)) == 7


async def test_search_filters_by_title(aged):
    await aged.post("/api/v1/conversations", json={"title": "Pinot evening"})
    await aged.post("/api/v1/conversations", json={"title": "Riesling hunt"})
    items = (await aged.get("/api/v1/conversations?q=pinot")).json()["items"]
    assert [i["title"] for i in items] == ["Pinot evening"]


async def test_archive_hides_from_default_list(aged):
    cid = (await aged.post("/api/v1/conversations", json={"title": "x"})).json()["id"]
    await aged.patch(f"/api/v1/conversations/{cid}", json={"archived": True})
    assert (await aged.get("/api/v1/conversations")).json()["items"] == []
    arch = (await aged.get("/api/v1/conversations?archived=true")).json()["items"]
    assert [i["id"] for i in arch] == [cid]


async def test_soft_delete_then_404(aged):
    cid = (await aged.post("/api/v1/conversations", json={})).json()["id"]
    assert (await aged.delete(f"/api/v1/conversations/{cid}")).status_code == 204
    assert (await aged.get(f"/api/v1/conversations/{cid}")).status_code == 404
    assert (await aged.delete(f"/api/v1/conversations/{cid}")).status_code == 404


# --- session scoping -----------------------------------------------------

async def test_sessions_are_isolated(client, settings):
    """FR-12: independent anonymous sessions. Existence is not leaked - 404, not 403."""
    import httpx

    await client.post("/api/v1/age-gate", json={"confirmed": True})
    cid = (await client.post("/api/v1/conversations", json={})).json()["id"]

    app = client._transport.app  # same app, a second cookie jar
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as other:
        await other.post("/api/v1/age-gate", json={"confirmed": True})
        assert (await other.get("/api/v1/conversations")).json()["items"] == []
        assert (await other.get(f"/api/v1/conversations/{cid}")).status_code == 404
        r = await other.patch(f"/api/v1/conversations/{cid}", json={"title": "x"})
        assert r.status_code == 404
        assert (await other.delete(f"/api/v1/conversations/{cid}")).status_code == 404


async def test_many_concurrent_sessions(client):
    """NFR-2: at least 20 simultaneous anonymous sessions."""
    import httpx

    app = client._transport.app

    async def one(n: int) -> bool:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as c:
            await c.post("/api/v1/age-gate", json={"confirmed": True})
            cid = (await c.post("/api/v1/conversations", json={"title": f"s{n}"})).json()["id"]
            r = await c.post(
                f"/api/v1/conversations/{cid}/messages",
                json={"content": "a bold red, not sweet"},
                headers=KEY(),
            )
            if r.status_code != 202:
                return False
            await asyncio.sleep(0.5)
            items = (await c.get("/api/v1/conversations")).json()["items"]
            return len(items) == 1 and items[0]["title"] == f"s{n}"

    assert all(await asyncio.gather(*[one(i) for i in range(20)]))


# --- turns ---------------------------------------------------------------

async def test_idempotency_key_is_required(aged):
    cid = (await aged.post("/api/v1/conversations", json={})).json()["id"]
    r = await aged.post(f"/api/v1/conversations/{cid}/messages", json={"content": "hi"})
    assert r.status_code == 400 and r.json()["code"] == "idempotency_key_required"


async def test_replayed_key_starts_one_turn(aged):
    cid = (await aged.post("/api/v1/conversations", json={})).json()["id"]
    headers = KEY()
    body = {"content": "a bold red"}
    r1 = await aged.post(f"/api/v1/conversations/{cid}/messages", json=body, headers=headers)
    await asyncio.sleep(0.6)
    r2 = await aged.post(f"/api/v1/conversations/{cid}/messages", json=body, headers=headers)
    assert r1.status_code == r2.status_code == 202
    assert r1.json() == r2.json()


async def test_same_key_different_body_conflicts(aged):
    cid = (await aged.post("/api/v1/conversations", json={})).json()["id"]
    headers = KEY()
    url = f"/api/v1/conversations/{cid}/messages"
    await aged.post(url, json={"content": "a"}, headers=headers)
    await asyncio.sleep(0.6)
    r = await aged.post(url, json={"content": "b"}, headers=headers)
    assert r.status_code == 409 and r.json()["code"] == "idempotency_key_reused"


async def test_second_turn_while_in_flight_conflicts(aged):
    cid = (await aged.post("/api/v1/conversations", json={})).json()["id"]
    r1 = await aged.post(
        f"/api/v1/conversations/{cid}/messages", json={"content": "a bold red"}, headers=KEY()
    )
    r2 = await aged.post(
        f"/api/v1/conversations/{cid}/messages", json={"content": "another"}, headers=KEY()
    )
    assert r1.status_code == 202
    assert r2.status_code == 409 and r2.json()["code"] == "turn_in_flight"
    assert r1.json()["turn_id"] in r2.json()["detail"]


async def test_cancel_unknown_turn_404s(aged):
    assert (await aged.post("/api/v1/turns/t-nope/cancel")).status_code == 404


async def test_turn_too_long_is_rejected(aged):
    cid = (await aged.post("/api/v1/conversations", json={})).json()["id"]
    r = await aged.post(
        f"/api/v1/conversations/{cid}/messages", json={"content": "x" * 5000}, headers=KEY()
    )
    assert r.status_code == 422 and r.json()["code"] == "validation_error"
    assert "errors" in r.json()


# --- the interview, through the API -------------------------------------

async def test_interview_fills_the_profile_and_recommends(aged):
    cid = (await aged.post("/api/v1/conversations", json={})).json()["id"]

    async def send(content, chip=None):
        r = await aged.post(
            f"/api/v1/conversations/{cid}/messages",
            json={"content": content, "selected_chip_id": chip}, headers=KEY(),
        )
        assert r.status_code == 202, r.text
        for _ in range(60):
            await asyncio.sleep(0.1)
            if aged._transport.app.state.services.registry.get(r.json()["turn_id"]) is None:
                return
    await send("I want a red", "style:red")
    await send("Not sweet at all", "sweetness:dry")
    await send("Rich and bold", "body:full")

    d = (await aged.get(f"/api/v1/conversations/{cid}")).json()
    assert d["taste_profile"]["style"] == "red"
    assert d["taste_profile"]["sweetness"] == "dry"
    assert d["taste_profile"]["body"] == "full"
    cards = [p for m in d["messages"] for p in m["parts"] if p["kind"] == "card"]
    assert 3 <= len(cards) <= 5
    assert all(c["row_id"] for c in cards)
    assert all(c["card"]["example_producers"] == [] for c in cards)
    assert d["title"] == "I want a red"


async def test_feedback_requires_the_row_to_be_cited(aged):
    cid = (await aged.post("/api/v1/conversations", json={})).json()["id"]
    r = await aged.post(
        f"/api/v1/conversations/{cid}/messages",
        json={"content": "a bold red, not sweet"}, headers=KEY(),
    )
    for _ in range(60):
        await asyncio.sleep(0.1)
        if aged._transport.app.state.services.registry.get(r.json()["turn_id"]) is None:
            break
    d = (await aged.get(f"/api/v1/conversations/{cid}")).json()
    mid = row = None
    for m in d["messages"]:
        for p in m["parts"]:
            if p["kind"] == "card":
                mid, row = m["id"], p["row_id"]
    assert mid, "the turn should have produced cards"
    url = f"/api/v1/messages/{mid}/feedback"
    assert (await aged.post(url, json={"row_id": row, "vote": "up"})).status_code == 204
    # Re-voting overwrites rather than erroring.
    assert (await aged.post(url, json={"row_id": row, "vote": "down"})).status_code == 204
    r = await aged.post(f"/api/v1/messages/{mid}/feedback", json={"row_id": "w-9999", "vote": "up"})
    assert r.status_code == 409 and r.json()["code"] == "row_not_cited"
    r = await aged.post("/api/v1/messages/m-nope/feedback", json={"row_id": row, "vote": "up"})
    assert r.status_code == 404


# --- meta ----------------------------------------------------------------

async def test_taste_axes_is_the_vocabulary_source(client):
    d = (await client.get("/api/v1/meta/taste-axes")).json()
    assert {a["id"] for a in d["axes"]} == {
        "style", "sweetness", "body", "oak", "tannin", "acidity", "fruit_savoury"
    }
    assert [c["id"] for c in d["refine_chips"]][:2] == ["less_sweet", "sweeter"]
    assert d["confidence_threshold"] == 0.75
    assert len(d["styles"]) == 5


async def test_dataset_version_reports_review_status(client):
    d = (await client.get("/api/v1/meta/dataset-version")).json()
    assert d["dataset_version"] == "seed-0.1"
    assert d["review_status_counts"] == {"unreviewed": 45}
    assert d["checksum"]


# --- title validation ----------------------------------------------------

async def test_title_is_bounded_on_create_and_patch(aged, settings):
    """`title_max_chars` used to be enforced only on auto-generated titles, so a
    client-supplied one was stored unchecked at any length."""
    limit = settings.title_max_chars

    r = await aged.post("/api/v1/conversations", json={"title": "T" * (limit + 1)})
    assert r.status_code == 422 and r.json()["code"] == "title_too_long"

    # Exactly at the limit is fine - the boundary is inclusive.
    r = await aged.post("/api/v1/conversations", json={"title": "T" * limit})
    assert r.status_code == 201 and len(r.json()["title"]) == limit
    cid = r.json()["id"]

    r = await aged.patch(f"/api/v1/conversations/{cid}", json={"title": "P" * (limit + 1)})
    assert r.status_code == 422 and r.json()["code"] == "title_too_long"
    # The rejected patch changed nothing.
    assert (await aged.get(f"/api/v1/conversations/{cid}")).json()["title"] == "T" * limit


async def test_blank_title_is_refused_rather_than_blanking_the_conversation(aged):
    """`repo.patch` writes any non-None title, so an empty string would wipe the
    sidebar entry with no way back. Omitting the field is how you leave it alone."""
    cid = (await aged.post("/api/v1/conversations", json={"title": "Keep me"})).json()["id"]

    for blank in ("", "   ", "\t\n"):
        r = await aged.patch(f"/api/v1/conversations/{cid}", json={"title": blank})
        assert r.status_code == 422, f"{blank!r} was accepted"
        assert r.json()["code"] == "title_blank"
    assert (await aged.get(f"/api/v1/conversations/{cid}")).json()["title"] == "Keep me"

    # Archiving without naming a title still works.
    r = await aged.patch(f"/api/v1/conversations/{cid}", json={"archived": True})
    assert r.status_code == 200 and r.json()["archived"] is True
    assert r.json()["title"] == "Keep me"


async def test_title_is_trimmed_not_stored_with_padding(aged):
    r = await aged.post("/api/v1/conversations", json={"title": "  Barolo night  "})
    assert r.status_code == 201 and r.json()["title"] == "Barolo night"


# --- the demo artifact, served through the API ---------------------------

async def test_demo_artifact_serves_producers_and_reports_them_as_unverified(demo_aged):
    """Section 9's promise, tested: swapping artifacts is a WA_DATASET_PATH change and
    nothing else. Cards come back with producer names, and every surface that could be
    read as "a person checked this" still says fixture."""
    d = (await demo_aged.get("/api/v1/meta/dataset-version")).json()
    assert d["dataset_version"] == "demo-0.1"
    assert d["review_status_counts"] == {"fixture": 45}

    cid = (await demo_aged.post("/api/v1/conversations", json={})).json()["id"]

    async def send(content, chip=None):
        r = await demo_aged.post(
            f"/api/v1/conversations/{cid}/messages",
            json={"content": content, "selected_chip_id": chip}, headers=KEY(),
        )
        assert r.status_code == 202, r.text
        for _ in range(60):
            await asyncio.sleep(0.1)
            if demo_aged._transport.app.state.services.registry.get(r.json()["turn_id"]) is None:
                return
    await send("I want a red", "style:red")
    await send("Not sweet at all", "sweetness:dry")
    await send("Rich and bold", "body:full")

    d = (await demo_aged.get(f"/api/v1/conversations/{cid}")).json()
    cards = [p for m in d["messages"] for p in m["parts"] if p["kind"] == "card"]
    assert 3 <= len(cards) <= 5
    # The point of the artifact: the producer slot is populated.
    assert all(c["card"]["example_producers"] for c in cards)
    # And the point of the status: it never claims that was checked.
    assert all(c["card"]["review_status"] == "fixture" for c in cards)
    assert all(c["card"]["dataset_version"] == "demo-0.1" for c in cards)


async def test_grounding_rewrites_producers_from_the_demo_row(demo_aged):
    """The grounding guard still owns the field. Producers on a card are whatever the
    row says, so a populated artifact widens what can be served without widening what
    an engine is able to assert."""
    cid = (await demo_aged.post("/api/v1/conversations", json={})).json()["id"]
    r = await demo_aged.post(
        f"/api/v1/conversations/{cid}/messages",
        json={"content": "a bold red, not sweet"}, headers=KEY(),
    )
    for _ in range(60):
        await asyncio.sleep(0.1)
        if demo_aged._transport.app.state.services.registry.get(r.json()["turn_id"]) is None:
            break

    index = demo_aged._transport.app.state.services.index
    d = (await demo_aged.get(f"/api/v1/conversations/{cid}")).json()
    cards = [p for m in d["messages"] for p in m["parts"] if p["kind"] == "card"]
    assert cards
    for card in cards:
        row = index.resolve(card["row_id"])
        assert row is not None
        assert card["card"]["example_producers"] == list(row.example_producers)


async def test_usage_reports_zero_on_the_free_engine(aged):
    d = (await aged.get("/api/v1/meta/usage")).json()
    assert d["cost_usd"] == 0.0 and d["engine"] == "deterministic"
    assert d["degraded"] is False


async def test_readyz_reports_the_loaded_index(client):
    d = (await client.get("/api/v1/readyz")).json()
    assert d["status"] == "ready" and d["row_count"] == 45
    assert d["indexes"]["by_row_id"] == 45


# --- errors --------------------------------------------------------------

async def test_errors_are_problem_json_without_stack_traces(aged):
    r = await aged.get("/api/v1/conversations/c-nope")
    assert r.headers["content-type"].startswith("application/problem+json")
    body = r.json()
    assert set(body) >= {"type", "title", "status", "detail", "code", "request_id"}
    assert "Traceback" not in r.text and "File \"" not in r.text
