"""Smoke test: boot pool + 2 A2A servers in-process, scripted round-trip (no real Claude)."""
import asyncio

import httpx

from crossagent.a2a import (A2AClient, AgentCard, AgentInterface, TaskStore,
                            make_app, run_server)
from crossagent.pool import PoolStore, make_pool_app
from crossagent.pool_client import PoolClient

POOL = "http://127.0.0.1:9110"
A_URL = "http://127.0.0.1:9111"
B_URL = "http://127.0.0.1:9112"


async def _wait_get(url: str, ok_name: str | None = None) -> None:
    async with httpx.AsyncClient() as c:
        for _ in range(100):
            try:
                r = await c.get(url)
                if r.status_code == 200:
                    body = r.json()
                    if ok_name is None or body.get("name") == ok_name:
                        return
            except Exception:
                pass
            await asyncio.sleep(0.1)
    raise RuntimeError(f"server at {url} did not come up")


async def main() -> None:
    pool_store = PoolStore()
    cards = {
        "a": AgentCard(name="a", description="a",
                       supportedInterfaces=[AgentInterface(url=A_URL + "/")]),
        "b": AgentCard(name="b", description="b",
                       supportedInterfaces=[AgentInterface(url=B_URL + "/")]),
    }
    servers = [
        run_server(make_pool_app(pool_store), "127.0.0.1", 9110),
        run_server(make_app(cards["a"], TaskStore()), "127.0.0.1", 9111),
        run_server(make_app(cards["b"], TaskStore()), "127.0.0.1", 9112),
    ]
    tasks = [asyncio.create_task(s) for s in servers]
    try:
        await _wait_get(POOL + "/health")
        await _wait_get(A_URL + "/.well-known/agent-card.json", "a")
        await _wait_get(B_URL + "/.well-known/agent-card.json", "b")

        pool = PoolClient(POOL)
        await pool.register("a", url=A_URL)
        await pool.register("b", url=B_URL)
        s = await pool.session_create("smoke goal", members=["a", "b"])
        sid = s["id"]
        await pool.post_activity(sid, "a", "started")
        await pool.declare_satisfaction(sid, "a", True)
        await pool.declare_satisfaction(sid, "b", True)
        assert (await pool.session_status(sid))["allSatisfied"] is True
        await pool.aclose()
        print("[smoke] pool: register/session/activity/satisfaction OK")

        a = A2AClient(A_URL)
        sent = await a.send_message("hello from smoke")
        assert sent["task"]["status"]["state"] == "TASK_STATE_INPUT_REQUIRED"
        replied = await a.respond(sent["task"]["id"], "hi back")
        assert replied["status"]["state"] == "TASK_STATE_COMPLETED"
        await a.aclose()
        print("[smoke] A2A: send/respond round-trip OK")
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
