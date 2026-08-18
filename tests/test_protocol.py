"""v1.0 wire-format tests for crossagent.a2a (over httpx ASGITransport, no live server)."""
import httpx
import pytest_asyncio

from crossagent.a2a import AgentCard, AgentInterface, TaskStore, make_app


@pytest_asyncio.fixture
async def client():
    card = AgentCard(name="test", description="t",
                     supportedInterfaces=[AgentInterface(url="http://test/")])
    app = make_app(card, TaskStore())
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _rpc(client, method, params):
    r = await client.post("/", json={"jsonrpc": "2.0", "id": "1",
                                     "method": method, "params": params})
    return r.json()


async def test_agent_card(client):
    r = await client.get("/.well-known/agent-card.json")
    assert r.status_code == 200
    assert r.json()["name"] == "test"


async def test_send_message_creates_input_required_task(client):
    res = await _rpc(client, "SendMessage",
                     {"message": {"role": "ROLE_USER", "parts": [{"text": "hi"}]}})
    task = res["result"]["task"]
    assert task["status"]["state"] == "TASK_STATE_INPUT_REQUIRED"
    assert task["history"][0]["parts"][0]["text"] == "hi"


async def test_get_task_roundtrip_and_context_continuity(client):
    res = await _rpc(client, "SendMessage",
                     {"message": {"role": "ROLE_USER",
                                  "contextId": "ctx-1",
                                  "parts": [{"text": "hi"}]}})
    task_id = res["result"]["task"]["id"]
    got = await _rpc(client, "GetTask", {"id": task_id})
    assert got["result"]["id"] == task_id
    assert got["result"]["contextId"] == "ctx-1"


async def test_unknown_method_returns_32601(client):
    res = await _rpc(client, "Nope", {})
    assert res["error"]["code"] == -32601


async def test_get_task_not_found_returns_32001(client):
    res = await _rpc(client, "GetTask", {"id": "missing"})
    assert res["error"]["code"] == -32001


async def test_respond_completes_task(client):
    res = await _rpc(client, "SendMessage",
                     {"message": {"role": "ROLE_USER", "parts": [{"text": "hi"}]}})
    task_id = res["result"]["task"]["id"]
    rep = await _rpc(client, "respond", {"id": task_id, "text": "done"})
    assert rep["result"]["status"]["state"] == "TASK_STATE_COMPLETED"
    assert rep["result"]["artifacts"][-1]["parts"][0]["text"] == "done"
    inbox = await _rpc(client, "inbox", {})
    assert inbox["result"] == []
