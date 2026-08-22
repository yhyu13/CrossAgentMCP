"""Unit tests for the pool control plane (crossagent.pool.PoolStore)."""
from fastapi.testclient import TestClient

from crossagent.pool import PoolStore, make_pool_app


def test_register_and_list():
    s = PoolStore()
    s.register("a", url="http://a")
    s.register("b")
    assert [r.agentId for r in s.list_agents()] == ["a", "b"]
    assert s.get_agent("a").url == "http://a"
    assert s.unregister("a") is True
    assert s.get_agent("a") is None
    assert s.heartbeat("missing") is False


def test_session_join_and_activity_seq():
    s = PoolStore()
    s.create_session("goal", members=["a", "b"], session_id="s1")
    s.join("s1", "c")
    assert s.get_session("s1").members == ["a", "b", "c"]

    s.post_activity("s1", "a", "started")
    s.post_activity("s1", "b", "artifact")
    # "joined" (seq 1), "started" (seq 2), "artifact" (seq 3)
    events = s.activity_since("s1", 1)
    assert [e.type for e in events] == ["started", "artifact"]
    assert [e.seq for e in events] == [2, 3]


def test_critique_flow_blocks_then_unblocks_satisfaction():
    s = PoolStore()
    s.create_session("goal", members=["a", "b"], session_id="s1")
    s.declare_satisfaction("s1", "a", True)
    s.declare_satisfaction("s1", "b", True)
    assert s.session_status("s1")["allSatisfied"] is True

    c = s.critique("s1", "a", "b", "fix this section")
    assert c is not None
    assert s.session_status("s1")["allSatisfied"] is False
    assert s.session_status("s1")["openCritiques"] == [c.id]
    # a critique invalidates the target's satisfaction until they re-confirm
    assert s.session_status("s1")["satisfaction"]["b"] is None

    # only the target may resolve; a third party cannot close b's critique
    assert s.resolve_critique("s1", c.id, "a", "nope") is None
    assert s.session_status("s1")["openCritiques"] == [c.id]

    s.resolve_critique("s1", c.id, "b", "fixed now")
    assert s.session_status("s1")["openCritiques"] == []
    assert s.session_status("s1")["allSatisfied"] is False  # b must re-confirm
    s.declare_satisfaction("s1", "b", True)
    assert s.session_status("s1")["allSatisfied"] is True


def test_not_all_satisfied_until_every_member():
    s = PoolStore()
    s.create_session("goal", members=["a", "b", "c"], session_id="s1")
    s.declare_satisfaction("s1", "a", True)
    s.declare_satisfaction("s1", "b", True)
    assert s.session_status("s1")["allSatisfied"] is False
    s.declare_satisfaction("s1", "c", True)
    assert s.session_status("s1")["allSatisfied"] is True


def test_mark_failed_is_terminal():
    s = PoolStore()
    s.create_session("goal", members=["a", "b"], session_id="s1")
    s.mark_failed("s1", "stalled")
    assert s.get_session("s1").state == "failed"
    # no later event may auto-recover a failed session
    s.declare_satisfaction("s1", "a", True)
    s.declare_satisfaction("s1", "b", True)
    assert s.get_session("s1").state == "failed"
    # a failed session must never report convergence even if all members agree
    assert s.session_status("s1")["allSatisfied"] is False


def test_max_critiques_cap_fails_session():
    s = PoolStore()
    s.create_session("goal", members=["a", "b"], session_id="s1", max_critiques=2)
    assert s.critique("s1", "a", "b", "c1") is not None
    assert s.get_session("s1").state != "failed"
    assert s.critique("s1", "b", "a", "c2") is not None
    # the 2nd critique crosses the cap -> failed, terminal
    assert s.get_session("s1").state == "failed"
    assert s.session_status("s1")["iteration"] == 2
    # a failed session rejects further critiques
    assert s.critique("s1", "a", "b", "c3") is None


def _http_client(agents=None, orchestrator_token=None):
    return TestClient(make_pool_app(PoolStore(), agents=agents,
                                    orchestrator_token=orchestrator_token))


def test_missing_params_returns_invalid_params():
    c = _http_client()
    r = c.post("/", json={"jsonrpc": "2.0", "id": 1, "method": "Register", "params": {}})
    assert r.status_code == 200
    assert r.json()["error"]["code"] == -32602


def test_unauthenticated_request_401():
    c = _http_client(agents={"a": "ta"})
    r = c.post("/", json={"jsonrpc": "2.0", "id": 1, "method": "ListAgents", "params": {}})
    assert r.status_code == 401


def test_correct_token_allows_request():
    c = _http_client(agents={"a": "ta"})
    r = c.post("/", json={"jsonrpc": "2.0", "id": 1, "method": "ListAgents", "params": {}},
               headers={"Authorization": "Bearer ta"})
    assert r.status_code == 200
    assert r.json()["result"] == []


def test_cannot_spoof_another_agents_satisfaction():
    c = _http_client(agents={"a": "ta", "b": "tb"})
    r = c.post("/", json={"jsonrpc": "2.0", "id": 1, "method": "SessionCreate",
                          "params": {"goal": "g", "members": ["a", "b"]}},
               headers={"Authorization": "Bearer ta"})
    sid = r.json()["result"]["id"]
    # a's token acting as b -> forbidden even though the session is shared
    r = c.post("/", json={"jsonrpc": "2.0", "id": 2, "method": "DeclareSatisfaction",
                          "params": {"sessionId": sid, "agentId": "b", "satisfied": True}},
               headers={"Authorization": "Bearer ta"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == -32003


def test_cannot_spoof_resolve_critique():
    c = _http_client(agents={"a": "ta", "b": "tb"})
    r = c.post("/", json={"jsonrpc": "2.0", "id": 1, "method": "SessionCreate",
                          "params": {"goal": "g", "members": ["a", "b"]}},
               headers={"Authorization": "Bearer ta"})
    sid = r.json()["result"]["id"]
    r = c.post("/", json={"jsonrpc": "2.0", "id": 2, "method": "Critique",
                          "params": {"sessionId": sid, "fromAgent": "a",
                                     "targetAgent": "b", "text": "weak"}},
               headers={"Authorization": "Bearer ta"})
    cid = r.json()["result"]["id"]
    # a's token claiming to resolve as b -> forbidden
    r = c.post("/", json={"jsonrpc": "2.0", "id": 3, "method": "ResolveCritique",
                          "params": {"sessionId": sid, "critiqueId": cid,
                                     "resolverAgentId": "b", "text": "fixed"}},
               headers={"Authorization": "Bearer ta"})
    assert r.status_code == 403
    assert r.json()["error"]["code"] == -32003


def test_mark_failed_requires_orchestrator():
    c = _http_client(agents={"a": "ta"}, orchestrator_token="orch")
    r = c.post("/", json={"jsonrpc": "2.0", "id": 1, "method": "SessionCreate",
                          "params": {"goal": "g", "members": ["a"]}},
               headers={"Authorization": "Bearer ta"})
    sid = r.json()["result"]["id"]
    # an agent cannot mark a session failed
    r = c.post("/", json={"jsonrpc": "2.0", "id": 2, "method": "MarkFailed",
                          "params": {"sessionId": sid, "reason": "x"}},
               headers={"Authorization": "Bearer ta"})
    assert r.status_code == 403
    # the orchestrator can
    r = c.post("/", json={"jsonrpc": "2.0", "id": 3, "method": "MarkFailed",
                          "params": {"sessionId": sid, "reason": "x"}},
               headers={"Authorization": "Bearer orch"})
    assert r.status_code == 200
    assert r.json()["result"]["state"] == "failed"


def test_orchestrator_may_act_on_behalf_of_agents():
    c = _http_client(agents={"a": "ta", "b": "tb"}, orchestrator_token="orch")
    r = c.post("/", json={"jsonrpc": "2.0", "id": 1, "method": "SessionCreate",
                          "params": {"goal": "g", "members": ["a", "b"]}},
               headers={"Authorization": "Bearer orch"})
    sid = r.json()["result"]["id"]
    r = c.post("/", json={"jsonrpc": "2.0", "id": 2, "method": "DeclareSatisfaction",
                          "params": {"sessionId": sid, "agentId": "a", "satisfied": True}},
               headers={"Authorization": "Bearer orch"})
    assert r.status_code == 200
