"""The A2A pool — central control plane (registry + sessions + activity + critique + goal).

Exposed as a plain HTTP JSON-RPC 2.0 service (FastAPI), so every agent's stdio
MCP bridge can reach it via :class:`crossagent.pool_client.PoolClient`. Agents
also talk to each other peer-to-peer over A2A (``crossagent.a2a``); the pool only
holds coordination state, never routes work messages.

Session lifecycle (coordinator-enforced): ``forming -> working -> revising ->
satisfied`` (or a no-progress/timeout guard marks it ``failed``). The goal is met
when **every member declares satisfied AND there are zero open critique threads**.
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from crossagent.a2a import now_iso


# Activity types that represent real work toward the goal (vs. bookkeeping like
# joined/left/started/finished/satisfied/blocked).
PROGRESS_TYPES = frozenset({"artifact", "critique", "self-improved"})


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #

class AgentRecord(BaseModel):
    agentId: str
    card: dict[str, Any] | None = None
    url: str | None = None
    registeredAt: str = Field(default_factory=now_iso)
    status: str = "online"
    lastHeartbeat: str = Field(default_factory=now_iso)


class ActivityEvent(BaseModel):
    """Append-only entry in a session's activity log (``seq`` is monotonic)."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    sessionId: str
    agentId: str
    type: str  # joined | left | started | finished | artifact | critique | self-improved | satisfied | blocked
    targetAgentId: str | None = None
    taskId: str | None = None
    payload: dict[str, Any] | None = None
    seq: int = 0
    ts: str = Field(default_factory=now_iso)


class CritiqueThread(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    sessionId: str
    targetAgentId: str
    authorAgentId: str
    targetSeq: int | None = None
    open: bool = True
    history: list[dict[str, Any]] = Field(default_factory=list)
    ts: str = Field(default_factory=now_iso)


class Session(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    goal: str
    members: list[str] = Field(default_factory=list)
    state: str = "forming"
    iteration: int = 0
    maxCritiques: int = 200
    startTs: str = Field(default_factory=now_iso)
    satisfaction: dict[str, bool | None] = Field(default_factory=dict)
    activityLog: list[ActivityEvent] = Field(default_factory=list)
    critiques: list[CritiqueThread] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Store
# --------------------------------------------------------------------------- #

class PoolStore:
    def __init__(self) -> None:
        self.agents: dict[str, AgentRecord] = {}
        self.sessions: dict[str, Session] = {}
        self._seq: dict[str, int] = {}

    # -- registry --
    def register(self, agent_id: str, card: dict[str, Any] | None = None,
                 url: str | None = None) -> AgentRecord:
        rec = AgentRecord(agentId=agent_id, card=card, url=url)
        self.agents[agent_id] = rec
        return rec

    def unregister(self, agent_id: str) -> bool:
        return self.agents.pop(agent_id, None) is not None

    def list_agents(self) -> list[AgentRecord]:
        return list(self.agents.values())

    def get_agent(self, agent_id: str) -> AgentRecord | None:
        return self.agents.get(agent_id)

    def heartbeat(self, agent_id: str) -> bool:
        rec = self.agents.get(agent_id)
        if not rec:
            return False
        rec.lastHeartbeat = now_iso()
        return True

    # -- sessions --
    def create_session(self, goal: str, members: list[str] | None = None,
                       session_id: str | None = None,
                       max_critiques: int = 200) -> Session:
        s = Session(id=session_id or str(uuid.uuid4()), goal=goal,
                    members=list(members or []),
                    satisfaction={m: None for m in (members or [])},
                    maxCritiques=max_critiques)
        self.sessions[s.id] = s
        self._seq[s.id] = 0
        return s

    def get_session(self, session_id: str) -> Session | None:
        return self.sessions.get(session_id)

    def list_sessions(self) -> list[Session]:
        return list(self.sessions.values())

    def join(self, session_id: str, agent_id: str) -> Session | None:
        s = self.sessions.get(session_id)
        if not s:
            return None
        if agent_id not in s.members:
            s.members.append(agent_id)
            s.satisfaction.setdefault(agent_id, None)
        self.post_activity(session_id, agent_id, "joined")
        return s

    def leave(self, session_id: str, agent_id: str) -> Session | None:
        s = self.sessions.get(session_id)
        if not s:
            return None
        if agent_id in s.members:
            s.members.remove(agent_id)
        self.post_activity(session_id, agent_id, "left")
        return s

    def set_goal(self, session_id: str, goal: str) -> Session | None:
        s = self.sessions.get(session_id)
        if not s:
            return None
        s.goal = goal
        return s

    # -- activity --
    def post_activity(self, session_id: str, agent_id: str, type_: str,
                      payload: dict[str, Any] | None = None,
                      target_agent_id: str | None = None,
                      task_id: str | None = None) -> ActivityEvent | None:
        s = self.sessions.get(session_id)
        if not s:
            return None
        self._seq[session_id] = self._seq.get(session_id, 0) + 1
        ev = ActivityEvent(sessionId=session_id, agentId=agent_id, type=type_,
                           targetAgentId=target_agent_id, taskId=task_id,
                           payload=payload, seq=self._seq[session_id])
        s.activityLog.append(ev)
        self._recompute_state(s)
        return ev

    def activity_since(self, session_id: str, since_seq: int) -> list[ActivityEvent]:
        s = self.sessions.get(session_id)
        if not s:
            return []
        return [e for e in s.activityLog if e.seq > since_seq]

    # -- critique --
    def critique(self, session_id: str, from_agent: str, target_agent: str,
                 text: str, target_seq: int | None = None) -> CritiqueThread | None:
        s = self.sessions.get(session_id)
        if not s:
            return None
        if s.state == "failed":
            return None  # terminal: a failed session accepts no new critiques
        thread = CritiqueThread(sessionId=session_id, targetAgentId=target_agent,
                                authorAgentId=from_agent, targetSeq=target_seq,
                                history=[{"role": from_agent, "text": text}])
        s.critiques.append(thread)
        # A defect report invalidates the target's prior satisfaction so they must
        # re-confirm after fixing before the session can converge (satisfaction is
        # not sticky across a critique aimed at them).
        s.satisfaction[target_agent] = None
        s.iteration += 1
        self.post_activity(session_id, from_agent, "critique",
                           payload={"critiqueId": thread.id, "text": text},
                           target_agent_id=target_agent)
        if s.iteration >= s.maxCritiques:
            self.mark_failed(session_id, f"max critiques reached ({s.maxCritiques})")
        return thread

    def resolve_critique(self, session_id: str, critique_id: str,
                         resolver_agent_id: str, text: str) -> CritiqueThread | None:
        s = self.sessions.get(session_id)
        if not s:
            return None
        for c in s.critiques:
            if c.id == critique_id:
                # Only the agent the critique targets may resolve it; a third party
                # cannot close a critique aimed at someone else.
                if c.targetAgentId != resolver_agent_id:
                    return None
                c.open = False
                c.history.append({"role": resolver_agent_id, "text": text})
                self.post_activity(session_id, resolver_agent_id, "self-improved",
                                   payload={"critiqueId": critique_id, "text": text},
                                   target_agent_id=c.authorAgentId)
                return c
        return None

    def list_critiques(self, session_id: str) -> list[CritiqueThread]:
        s = self.sessions.get(session_id)
        return list(s.critiques) if s else []

    # -- satisfaction --
    def declare_satisfaction(self, session_id: str, agent_id: str, satisfied: bool,
                             summary: str | None = None) -> Session | None:
        s = self.sessions.get(session_id)
        if not s:
            return None
        s.satisfaction[agent_id] = satisfied
        self.post_activity(session_id, agent_id,
                           "satisfied" if satisfied else "blocked",
                           payload={"summary": summary} if summary else None)
        return s

    def _recompute_state(self, s: Session) -> None:
        if s.state == "failed":
            return  # terminal: a failed session never auto-recovers
        open_critiques = [c for c in s.critiques if c.open]
        all_satisfied = bool(s.members) and all(
            s.satisfaction.get(m) is True for m in s.members)
        if all_satisfied and not open_critiques:
            s.state = "satisfied"
        elif open_critiques:
            s.state = "revising"
        elif s.activityLog:
            s.state = "working"
        else:
            s.state = "forming"

    def mark_failed(self, session_id: str, reason: str | None = None) -> Session | None:
        s = self.sessions.get(session_id)
        if not s:
            return None
        s.state = "failed"
        self.post_activity(session_id, "system", "blocked",
                           payload={"reason": reason} if reason else None)
        return s

    def session_status(self, session_id: str) -> dict[str, Any] | None:
        s = self.sessions.get(session_id)
        if not s:
            return None
        open_critiques = [c for c in s.critiques if c.open]
        all_satisfied = s.state != "failed" and bool(s.members) and all(
            s.satisfaction.get(m) is True for m in s.members) and not open_critiques
        return {
            "id": s.id,
            "goal": s.goal,
            "members": list(s.members),
            "state": s.state,
            "iteration": s.iteration,
            "startTs": s.startTs,
            "satisfaction": dict(s.satisfaction),
            "openCritiques": [c.id for c in open_critiques],
            "allSatisfied": all_satisfied,
            "activityCount": len(s.activityLog),
            "progressCount": sum(1 for e in s.activityLog if e.type in PROGRESS_TYPES),
        }


# --------------------------------------------------------------------------- #
# JSON-RPC control-plane server
# --------------------------------------------------------------------------- #

def make_pool_app(store: PoolStore, agents: dict[str, str] | None = None,
                  orchestrator_token: str | None = None) -> FastAPI:
    """Build the pool JSON-RPC app.

    When ``agents`` maps ``agentId -> bearer token`` (and optionally an
    ``orchestrator_token``), every request must present a valid token; the token
    resolves to a principal and identity-bearing methods are refused if the caller
    acts as anyone other than themself (or the orchestrator). With no tokens the
    pool runs open (local tests/smoke use).
    """
    app = FastAPI(title="A2A pool")
    principals: dict[str, str] = {}
    if agents:
        for agent_id, tok in agents.items():
            principals[tok] = agent_id
    if orchestrator_token:
        principals[orchestrator_token] = "orchestrator"
    auth_enabled = bool(principals)

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "agents": len(store.agents),
                "sessions": len(store.sessions)}

    @app.post("/")
    async def jsonrpc(req: Request) -> Any:
        principal: str | None = None
        if auth_enabled:
            authz = req.headers.get("authorization", "")
            tok = authz[7:].strip() if authz.lower().startswith("bearer ") else ""
            principal = principals.get(tok)
            if principal is None:
                return JSONResponse({"jsonrpc": "2.0", "id": None,
                                     "error": {"code": -32000, "message": "Unauthorized"}},
                                    status_code=401)

        def _bad(code: int, message: str, rpc_id: Any = None) -> JSONResponse:
            return JSONResponse({"jsonrpc": "2.0", "id": rpc_id,
                                 "error": {"code": code, "message": message}})

        try:
            body = await req.json()
        except ValueError:
            return _bad(-32700, "Parse error")
        if not isinstance(body, dict):
            return _bad(-32600, "Invalid Request")

        rpc_id = body.get("id")
        method = body.get("method")
        params = body.get("params")
        if params is None:
            params = {}
        if not isinstance(params, dict):
            return _bad(-32602, "Invalid params", rpc_id)

        def ok(result: Any) -> JSONResponse:
            return JSONResponse({"jsonrpc": "2.0", "id": rpc_id, "result": result})

        def err(message: str, code: int = -32000) -> JSONResponse:
            return JSONResponse({"jsonrpc": "2.0", "id": rpc_id,
                                 "error": {"code": code, "message": message}})

        def dump(model: BaseModel | list[BaseModel]) -> Any:
            if isinstance(model, list):
                return [m.model_dump(exclude_none=True) for m in model]
            return model.model_dump(exclude_none=True)

        def _forbidden(message: str) -> JSONResponse:
            return JSONResponse({"jsonrpc": "2.0", "id": rpc_id,
                                 "error": {"code": -32003, "message": message}},
                                status_code=403)

        def _authz(claimed: str) -> JSONResponse | None:
            """Refuse (403) if the caller may not act as ``claimed``."""
            if auth_enabled and principal != "orchestrator" and principal != claimed:
                return _forbidden(f"not authorized as {claimed}")
            return None

        try:
            # -- registry --
            if method == "Register":
                if (r := _authz(params["agentId"])):
                    return r
                rec = store.register(params["agentId"], params.get("card"), params.get("url"))
                return ok(dump(rec))
            if method == "Unregister":
                if (r := _authz(params["agentId"])):
                    return r
                return ok(store.unregister(params["agentId"]))
            if method == "ListAgents":
                return ok(dump(store.list_agents()))
            if method == "GetAgent":
                rec = store.get_agent(params["agentId"])
                return ok(dump(rec)) if rec else err("Agent not found")
            if method == "Heartbeat":
                if (r := _authz(params["agentId"])):
                    return r
                return ok(store.heartbeat(params["agentId"]))

            # -- sessions --
            if method == "SessionCreate":
                s = store.create_session(params.get("goal", ""), params.get("members"),
                                         params.get("sessionId"),
                                         params.get("maxCritiques", 200))
                return ok(s.model_dump(exclude_none=True))
            if method == "SessionJoin":
                if (r := _authz(params["agentId"])):
                    return r
                s = store.join(params["sessionId"], params["agentId"])
                return ok(s.model_dump(exclude_none=True)) if s else err("Session not found")
            if method == "SessionLeave":
                if (r := _authz(params["agentId"])):
                    return r
                s = store.leave(params["sessionId"], params["agentId"])
                return ok(s.model_dump(exclude_none=True)) if s else err("Session not found")
            if method == "SessionList":
                return ok(dump(store.list_sessions()))
            if method == "SessionGet":
                s = store.get_session(params["sessionId"])
                return ok(s.model_dump(exclude_none=True)) if s else err("Session not found")
            if method == "SetGoal":
                s = store.set_goal(params["sessionId"], params["goal"])
                return ok(s.model_dump(exclude_none=True)) if s else err("Session not found")

            # -- activity --
            if method == "PostActivity":
                if (r := _authz(params["agentId"])):
                    return r
                ev = store.post_activity(params["sessionId"], params["agentId"],
                                         params["type"], params.get("payload"),
                                         params.get("targetAgentId"), params.get("taskId"))
                return ok(dump(ev)) if ev else err("Session not found")
            if method == "ActivitySince":
                return ok(dump(store.activity_since(params["sessionId"], params.get("sinceSeq", 0))))

            # -- critique --
            if method == "Critique":
                if (r := _authz(params["fromAgent"])):
                    return r
                c = store.critique(params["sessionId"], params["fromAgent"],
                                   params["targetAgent"], params["text"],
                                   params.get("targetSeq"))
                return ok(dump(c)) if c else err("Session not found")
            if method == "ResolveCritique":
                if (r := _authz(params["resolverAgentId"])):
                    return r
                c = store.resolve_critique(params["sessionId"], params["critiqueId"],
                                           params["resolverAgentId"], params["text"])
                return ok(dump(c)) if c else err("Critique not found or not authorized")
            if method == "ListCritiques":
                return ok(dump(store.list_critiques(params["sessionId"])))

            # -- goal --
            if method == "DeclareSatisfaction":
                if (r := _authz(params["agentId"])):
                    return r
                s = store.declare_satisfaction(params["sessionId"], params["agentId"],
                                               params.get("satisfied", True),
                                               params.get("summary"))
                return ok(s.model_dump(exclude_none=True)) if s else err("Session not found")
            if method == "SessionStatus":
                st = store.session_status(params["sessionId"])
                return ok(st) if st else err("Session not found")
            if method == "MarkFailed":
                if auth_enabled and principal != "orchestrator":
                    return _forbidden("only the orchestrator may mark a session failed")
                s = store.mark_failed(params["sessionId"], params.get("reason"))
                return ok(s.model_dump(exclude_none=True)) if s else err("Session not found")

            return err(f"Method not found: {method}")
        except (KeyError, TypeError, ValueError) as e:
            return err(f"Invalid params: {e}", code=-32602)

    return app


# --------------------------------------------------------------------------- #
# Server launch
# --------------------------------------------------------------------------- #

def serve_blocking(app: FastAPI, host: str, port: int) -> None:
    from crossagent.a2a import serve_blocking as _serve
    _serve(app, host, port)


def main() -> None:
    import argparse
    import json

    parser = argparse.ArgumentParser(description="A2A pool control plane")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9100)
    parser.add_argument("--agents", default=None,
                        help="optional JSON {agentId: token} to require per-agent auth")
    parser.add_argument("--orchestrator-token", default=None,
                        help="optional privileged orchestrator token")
    args = parser.parse_args()
    agents = json.loads(args.agents) if args.agents else None
    serve_blocking(make_pool_app(PoolStore(), agents=agents,
                                 orchestrator_token=args.orchestrator_token),
                   args.host, args.port)


if __name__ == "__main__":
    main()
