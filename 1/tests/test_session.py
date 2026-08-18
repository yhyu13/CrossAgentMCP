"""Session lifecycle tests."""
from shared.pool_client import PoolClient


async def test_create_session(client: PoolClient) -> None:
    s = await client.create_session("build a thing")
    assert s["id"]
    assert s["goal"] == "build a thing"
    assert s["state"] == "forming"


async def test_join_auto_starts_with_goal_and_two_members(client: PoolClient) -> None:
    await client.register("a", {}, "http://x")
    await client.register("b", {}, "http://y")
    s = await client.create_session("goal")
    await client.join_session(s["id"], "a")
    assert (await client.session_status(s["id"]))["state"] == "forming"
    await client.join_session(s["id"], "b")
    assert (await client.session_status(s["id"]))["state"] == "working"


async def test_set_goal_auto_starts(client: PoolClient) -> None:
    await client.register("a", {}, "http://x")
    await client.register("b", {}, "http://y")
    s = await client.create_session("")
    await client.join_session(s["id"], "a")
    await client.join_session(s["id"], "b")
    assert (await client.session_status(s["id"]))["state"] == "forming"
    await client.set_goal(s["id"], "now we have a goal")
    assert (await client.session_status(s["id"]))["state"] == "working"


async def test_leave_fails_session(client: PoolClient) -> None:
    await client.register("a", {}, "http://x")
    await client.register("b", {}, "http://y")
    s = await client.create_session("goal")
    await client.join_session(s["id"], "a")
    await client.join_session(s["id"], "b")
    await client.leave_session(s["id"], "a")
    st = await client.session_status(s["id"])
    assert st["state"] == "failed"
    assert "left" in st["failedReason"]


async def test_session_list(client: PoolClient) -> None:
    await client.create_session("one")
    await client.create_session("two")
    sessions = await client.list_sessions()
    assert len(sessions) == 2


async def test_creator_auto_added_as_member(client: PoolClient) -> None:
    await client.register("a", {}, "http://x")
    s = await client.create_session("goal", creator="a")
    st = await client.session_status(s["id"])
    assert st["members"] == ["a"]
