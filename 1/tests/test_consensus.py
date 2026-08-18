"""Consensus / critique state machine + termination guard tests."""
from datetime import datetime, timedelta, timezone

import pytest

from pool.store import PoolStore
from shared.pool_client import PoolClient


async def _setup(client: PoolClient, *members: str) -> str:
    for m in members:
        await client.register(m, {}, f"http://{m}")
    s = await client.create_session("goal")
    for m in members:
        await client.join_session(s["id"], m)
    return s["id"]


async def test_full_critique_flow_converges(client: PoolClient) -> None:
    sid = await _setup(client, "a", "b")

    await client.post_activity(sid, "a", "finished", text="DRAFT proposal")
    c = await client.critique_send(sid, "b", "a", "missing APPROVED")

    st = await client.session_status(sid)
    assert st["satisfaction"]["a"] is False
    assert st["openCritiques"] == [c["id"]]

    await client.critique_resolve(sid, c["id"], "a", "APPROVED (revised)")
    await client.post_activity(sid, "a", "finished", text="APPROVED")

    await client.declare_satisfaction(sid, "b")
    assert (await client.session_status(sid))["state"] == "reviewing"

    await client.declare_satisfaction(sid, "a")
    st = await client.session_status(sid)
    assert st["state"] == "satisfied"
    types = [e["type"] for e in st["activity"]]
    assert "critique" in types
    assert "self-improved" in types
    assert "session-completed" in types


async def test_requires_unanimity(client: PoolClient) -> None:
    sid = await _setup(client, "a", "b", "c")
    await client.declare_satisfaction(sid, "a")
    await client.declare_satisfaction(sid, "b")
    assert (await client.session_status(sid))["state"] != "satisfied"


async def test_max_iterations_guard(client: PoolClient, store: PoolStore) -> None:
    sid = await _setup(client, "a", "b")
    store.get_session(sid).maxIterations = 2
    await client.critique_send(sid, "b", "a", "x")
    assert (await client.session_status(sid))["state"] != "failed"
    await client.critique_send(sid, "b", "a", "x again")
    st = await client.session_status(sid)
    assert st["state"] == "failed"
    assert "max iterations" in st["failedReason"]


async def test_many_concurrent_critiques_do_not_false_fail(client: PoolClient) -> None:
    # Regression: 7 peers critique one target before it gets a chance to respond.
    # This must NOT trip a premature "no progress" failure — the target can still
    # resolve and the session can converge.
    critics = [f"c{i}" for i in range(7)]
    sid = await _setup(client, "t", *critics)
    for c in critics:
        await client.critique_send(sid, c, "t", "please fix")
    st = await client.session_status(sid)
    assert st["state"] != "failed"
    assert len(st["openCritiques"]) == 7


async def test_timeout_guard(client: PoolClient, store: PoolStore) -> None:
    sid = await _setup(client, "a", "b")
    s = store.get_session(sid)
    s.startTs = (datetime.now(timezone.utc) - timedelta(seconds=999)).isoformat()
    await client.post_activity(sid, "a", "started")
    st = await client.session_status(sid)
    assert st["state"] == "failed"
    assert "timed out" in st["failedReason"]


async def test_blocked_fails(client: PoolClient) -> None:
    sid = await _setup(client, "a", "b")
    await client.post_activity(sid, "a", "blocked", text="cannot proceed")
    st = await client.session_status(sid)
    assert st["state"] == "failed"
    assert "blocked" in st["failedReason"]


async def test_critique_sets_revising_then_resolve_reviewing(client: PoolClient) -> None:
    sid = await _setup(client, "a", "b")
    await client.post_activity(sid, "a", "finished", text="DRAFT")
    assert (await client.session_status(sid))["state"] == "reviewing"

    c = await client.critique_send(sid, "b", "a", "fix this")
    assert (await client.session_status(sid))["state"] == "revising"

    await client.critique_resolve(sid, c["id"], "a", "fixed")
    assert (await client.session_status(sid))["state"] == "reviewing"


async def test_resolve_rejects_unknown_critique(client: PoolClient) -> None:
    sid = await _setup(client, "a", "b")
    with pytest.raises(RuntimeError):
        await client.critique_resolve(sid, "nonexistent", "a", "fixed")


async def test_resolve_rejects_wrong_target(client: PoolClient) -> None:
    sid = await _setup(client, "a", "b")
    c = await client.critique_send(sid, "a", "b", "please fix")
    # "a" tries to resolve a critique aimed at "b" -> rejected
    with pytest.raises(RuntimeError):
        await client.critique_resolve(sid, c["id"], "a", "hijack")
    st = await client.session_status(sid)
    assert st["openCritiques"] == [c["id"]]  # still open


async def test_post_activity_satisfied_unifies(client: PoolClient) -> None:
    sid = await _setup(client, "a", "b")
    ev = await client.post_activity(sid, "a", "satisfied", text="looks good")
    assert ev["type"] == "satisfied"
    st = await client.session_status(sid)
    assert st["satisfaction"]["a"] is True


async def test_post_activity_satisfied_non_member_rejected(client: PoolClient) -> None:
    sid = await _setup(client, "a", "b")
    with pytest.raises(RuntimeError) as ei:
        await client.post_activity(sid, "zzz", "satisfied", text="impostor")
    assert ei.value.args[0]["code"] == -32004


async def test_resolve_rejects_cross_session(client: PoolClient) -> None:
    sid_a = await _setup(client, "a", "b")
    sid_b = await _setup(client, "a", "b")
    c = await client.critique_send(sid_b, "b", "a", "fix this")

    # resolving a session-B critique through session A must be rejected
    with pytest.raises(RuntimeError) as ei:
        await client.critique_resolve(sid_a, c["id"], "a", "hijack")
    assert ei.value.args[0]["code"] == -32003

    st_b = await client.session_status(sid_b)
    assert st_b["openCritiques"] == [c["id"]]  # still open in session B
