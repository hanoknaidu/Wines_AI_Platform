"""Streaming tests against a real uvicorn process.

httpx's ASGITransport buffers the whole response body, so an endless SSE stream can
only be exercised over a real socket.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

pytestmark = pytest.mark.timeout(90)

NAMES = lambda ev: [e["name"] for e in ev]  # noqa: E731
CARDS = lambda ev: [e["data"] for e in ev if e["name"] == "card"]  # noqa: E731
TEXT = lambda ev: "".join(  # noqa: E731
    e["data"].get("text", "") for e in ev if e["name"] == "token"
)


async def new_conversation(c, base) -> str:
    return (await c.post(f"{base}/api/v1/conversations", json={})).json()["id"]


async def turn(sse, c, base, cid, content, chip=None, after=0):
    """Open the stream, then send - mirroring a client that holds a stream open."""
    task = asyncio.create_task(sse.read(cid, after))
    await asyncio.sleep(0.25)
    r = await c.post(
        f"{base}/api/v1/conversations/{cid}/messages",
        json={"content": content, "selected_chip_id": chip},
        headers={"Idempotency-Key": uuid.uuid4().hex},
    )
    assert r.status_code == 202, r.text
    return r.json(), await task


async def interview_to_results(sse, c, base, cid):
    _, ev = await turn(sse, c, base, cid, "I'd like a red", "style:red")
    last = max(e["seq"] for e in ev if "seq" in e)
    _, ev = await turn(sse, c, base, cid, "Not sweet at all", "sweetness:dry", after=last)
    last = max(e["seq"] for e in ev if "seq" in e)
    _, ev = await turn(sse, c, base, cid, "In the middle", "body:medium", after=last)
    return ev


async def test_frames_arrive_in_the_documented_order(sse, server):
    reader, c = sse
    cid = await new_conversation(c, server)
    ev = await interview_to_results(reader, c, server, cid)
    names = NAMES(ev)
    assert names[0] == "token", "prose streams before the cards"
    assert names[-1] == "done"
    assert names[-2] == "usage", "usage is emitted once, immediately before done"
    for required in ("card", "citation", "chips"):
        assert required in names, required
    assert names.index("token") < names.index("card") < names.index("citation")


async def test_seq_is_strictly_monotonic(sse, server):
    reader, c = sse
    cid = await new_conversation(c, server)
    ev = await interview_to_results(reader, c, server, cid)
    seqs = [e["seq"] for e in ev if "seq" in e]
    assert seqs == sorted(seqs)
    assert len(seqs) == len(set(seqs)), "a duplicate seq would break ?after="


async def test_cards_carry_grounding(sse, server):
    reader, c = sse
    cid = await new_conversation(c, server)
    ev = await interview_to_results(reader, c, server, cid)
    cards = CARDS(ev)
    assert 3 <= len(cards) <= 5
    for card in cards:
        assert card["row_id"].startswith("w-")
        assert card["dataset_version"] == "seed-0.1"
        assert card["review_status"] == "unreviewed"
        assert card["example_producers"] == []
        assert card["why_it_matches"]
    citation = [e["data"] for e in ev if e["name"] == "citation"][0]
    assert citation["row_ids"] == [card["row_id"] for card in cards]


async def test_resume_replays_without_gap_or_duplicate(sse, server):
    """Read a whole turn, then resume from 0 and from halfway."""
    reader, c = sse
    cid = await new_conversation(c, server)
    live = await interview_to_results(reader, c, server, cid)

    full = await reader.read(cid, 0, timeout=10.0)
    # A caught-up replay ends in an idle `done` so the client stops waiting.
    terminal = [e for e in full if e["name"] == "done"]
    assert terminal and terminal[-1]["data"]["status"] == "idle"
    assert terminal[-1]["data"]["replay"] is True
    # The idle frame carries no `id:`, so it cannot move the client's resume cursor.
    assert "seq" not in terminal[-1]
    full_seqs = [e["seq"] for e in full if "seq" in e]
    assert full_seqs == sorted(set(full_seqs)), "replay must be ordered and unique"
    # Replayed text lands before the replayed cards, exactly as it did live.
    assert NAMES(full).index("token") < NAMES(full).index("card")
    assert len(CARDS(full)) == len(CARDS(live))

    midpoint = full_seqs[len(full_seqs) // 2]
    tail = await reader.read(cid, midpoint, timeout=10.0)
    assert all(e["seq"] > midpoint for e in tail if "seq" in e), (
        "?after= must be exclusive"
    )


async def test_resume_mid_turn_loses_nothing(sse, server):
    """Drop the stream while a turn is still running, then reconnect.

    This is the case the live-buffer handoff exists for: without it there is a hole
    between the last committed part and the live tail.
    """
    reader, c = sse
    cid = await new_conversation(c, server)
    await turn(reader, c, server, cid, "I'd like a red", "style:red")
    ev = await turn(reader, c, server, cid, "Not sweet at all", "sweetness:dry")
    last = max(e["seq"] for e in ev[1] if "seq" in e)

    # The previous turn must finish first: one in-flight turn per conversation.
    await asyncio.sleep(0.6)

    # Start the turn, read a little, then abandon the connection.
    r = await c.post(
        f"{server}/api/v1/conversations/{cid}/messages",
        json={"content": "In the middle", "selected_chip_id": "body:medium"},
        headers={"Idempotency-Key": uuid.uuid4().hex},
    )
    assert r.status_code == 202
    early = await reader.read(cid, last, until="card", timeout=10.0)
    assert early, "should have received frames before dropping"
    seen = max(e["seq"] for e in early if "seq" in e)

    rest = await reader.read(cid, seen, timeout=15.0)
    assert "done" in NAMES(rest), "the turn completes for a reconnecting client"
    assert all(e["seq"] > seen for e in rest if "seq" in e), "no duplicate on reconnect"

    # Nothing was lost: a full replay has every card the turn produced.
    whole = await reader.read(cid, last, timeout=10.0)
    assert 3 <= len(CARDS(whole)) <= 5


async def test_token_frames_carry_a_run_anchor(sse, server):
    """A client that drops mid-run reconnects with ?after=anchor_seq-1."""
    reader, c = sse
    cid = await new_conversation(c, server)
    _, ev = await turn(reader, c, server, cid, "I'd like a red", "style:red")
    tokens = [e for e in ev if e["name"] == "token"]
    assert tokens
    anchors = {t["data"]["anchor_seq"] for t in tokens}
    assert len(anchors) == 1, "one text run in an interview turn"
    assert min(t["seq"] for t in tokens) == anchors.pop()


async def test_cancel_stops_the_turn_and_reports_it(sse, server):
    reader, c = sse
    cid = await new_conversation(c, server)
    _, first = await turn(reader, c, server, cid, "I'd like a red", "style:red")
    last = max(e["seq"] for e in first if "seq" in e)

    # From `last`, so the read tails the live turn instead of catching up on history
    # (a catch-up replay ends in an idle `done`, which is not what this asserts).
    task = asyncio.create_task(reader.read(cid, last, timeout=20.0))
    await asyncio.sleep(0.2)
    r = await c.post(
        f"{server}/api/v1/conversations/{cid}/messages",
        json={"content": "Not sweet at all", "selected_chip_id": "sweetness:dry"},
        headers={"Idempotency-Key": uuid.uuid4().hex},
    )
    tid = r.json()["turn_id"]
    await asyncio.sleep(0.05)
    await c.post(f"{server}/api/v1/turns/{tid}/cancel")
    ev = await task
    done = [e["data"] for e in ev if e["name"] == "done"]
    assert done, "done always arrives, even on cancel"
    assert done[-1]["status"] in ("cancelled", "ok")


async def test_turn_cache_makes_a_repeated_turn_free(sse, server):
    """Identical question, profile and dataset version -> replayed, not recomputed.

    Costs nothing today (the engine is free); under lane 3 this is the difference
    between paying twice for the same turn and paying once.
    """
    reader, c = sse
    a = await new_conversation(c, server)
    b = await new_conversation(c, server)
    _, ev1 = await turn(reader, c, server, a, "I'd like a red", "style:red")
    _, ev2 = await turn(reader, c, server, b, "I'd like a red", "style:red")
    assert TEXT(ev1) == TEXT(ev2), "the same question yields the same answer"

    usage = [e["data"] for e in ev2 if e["name"] == "usage"][0]
    assert usage["cache_hit"] is True, "the second identical turn came from the cache"
    assert usage["cost_usd"] == 0.0


async def test_out_of_scope_streams_without_retrieval(sse, server):
    reader, c = sse
    cid = await new_conversation(c, server)
    _, ev = await turn(reader, c, server, cid, "how much is a bottle?")
    assert not CARDS(ev)
    assert "Price is out of scope" in TEXT(ev)
    usage = [e["data"] for e in ev if e["name"] == "usage"][0]
    assert usage["intent"] == "out_of_scope"


async def test_empty_state_is_honest(sse, server):
    reader, c = sse
    cid = await new_conversation(c, server)
    _, ev = await turn(reader, c, server, cid, "a dessert wine", "style:dessert")
    last = max(e["seq"] for e in ev if "seq" in e)
    _, ev = await turn(reader, c, server, cid, "not sweet at all", "sweetness:dry", after=last)
    assert not CARDS(ev), "no match must not be served by widening the filter"
    text = TEXT(ev)
    assert "not covered" in text and "widen" in text
    assert "chips" in NAMES(ev), "the empty state still offers a way forward"


async def test_keepalive_comments_do_not_break_the_stream(sse, server):
    """An idle stream emits `: keep-alive` and stays usable."""
    reader, c = sse
    cid = await new_conversation(c, server)
    ev = await reader.read(cid, 0, until="never", timeout=2.0)
    assert ev == [], "an idle conversation yields no frames, only comments"
    _, ev = await turn(reader, c, server, cid, "I'd like a red", "style:red")
    assert "done" in NAMES(ev)
