"""Registry + activity bus tests."""
import asyncio

from pool.store import PoolStore
from shared.pool_client import PoolClient


async def test_register_and_list(client: PoolClient) -> None:
    await client.register("a", {"name": "A"}, "http://127.0.0.1:9001")
    await client.register("b", {"name": "B"}, "http://127.0.0.1:9002")
    agents = await client.list_agents()
    assert {a["agentId"] for a in agents} == {"a", "b"}
    a = next(a for a in agents if a["agentId"] == "a")
    assert a["card"]["name"] == "A"
    assert a["url"] == "http://127.0.0.1:9001"


async def test_heartbeat(client: PoolClient) -> None:
    await client.register("a", {}, "http://x")
    before = (await client.list_agents())[0]["lastHeartbeat"]
    await asyncio.sleep(0.01)
    await client.heartbeat("a")
    after = (await client.list_agents())[0]["lastHeartbeat"]
    assert after != before


async def test_unregister(client: PoolClient) -> None:
    await client.register("a", {}, "http://x")
    assert (await client.unregister("a"))["removed"] is True
    assert await client.list_agents() == []


async def test_activity_post_and_list(client: PoolClient) -> None:
    s = await client.create_session("goal")
    await client.register("a", {}, "http://x")
    await client.join_session(s["id"], "a")
    ev = await client.post_activity(s["id"], "a", "started", text="hello")
    assert ev["seq"] == 1  # seq 0 is the 'joined' event
    events = await client.activity_list(s["id"], since_seq=0)
    types = [e["type"] for e in events]
    assert "joined" in types and "started" in types
    assert events[-1]["payload"] == "hello"


async def test_activity_watch_replay(live_client) -> None:
    pool, _ = live_client
    s = await pool.create_session("goal")
    await pool.register("a", {}, "http://x")
    await pool.join_session(s["id"], "a")
    await pool.post_activity(s["id"], "a", "started", text="replay-me")

    seen = []

    async def _drain():
        async for ev in pool.activity_subscribe(s["id"], since_seq=0):
            seen.append(ev)
            if ev["type"] == "started":
                return

    await asyncio.wait_for(_drain(), timeout=5)
    assert seen[0]["type"] == "joined"
    assert any(e["type"] == "started" for e in seen)


async def test_activity_watch_live(live_client) -> None:
    pool, _ = live_client
    s = await pool.create_session("goal")
    await pool.register("a", {}, "http://x")
    await pool.join_session(s["id"], "a")

    # Subscribe with since_seq=1 (skip the buffered 'joined' event at seq 0).
    # The 'finished' event (seq 1) is posted after subscribing -> must arrive live.
    async def _first():
        async for ev in pool.activity_subscribe(s["id"], since_seq=1):
            return ev

    task = asyncio.create_task(_first())
    await asyncio.sleep(0.1)
    await pool.post_activity(s["id"], "a", "finished", text="live-event")
    ev = await asyncio.wait_for(task, timeout=5)
    assert ev["type"] == "finished"
    assert ev["payload"] == "live-event"


async def test_subscribe_snapshot_is_frozen(store: PoolStore) -> None:
    store.register("a", {}, "http://x")
    s = store.create_session("goal")
    store.join(s.id, "a")

    q, snapshot = store.subscribe(s.id)
    store.post_activity(s.id, "a", "started", text="after-subscribe")

    # snapshot is frozen at join time -> must not contain the new event
    assert all(ev.type != "started" for ev in snapshot)
    # the live queue gets it exactly once
    assert q.get_nowait().type == "started"
    assert q.empty()
