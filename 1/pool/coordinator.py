"""Pool coordinator: FastAPI app exposing the control-plane JSON-RPC + SSE watch.

Reuses the JSON-RPC-over-HTTP style of `shared.a2a` but with its own method set:
  - agents/register, agents/list, agents/heartbeat, agents/unregister
  - sessions/create, sessions/join, sessions/leave, sessions/set_goal,
    sessions/start, sessions/status, sessions/list
  - activity/post, activity/list
  - critique/send, critique/resolve
  - sessions/satisfy

Watch (activity stream) is exposed as SSE at GET /activity/{session_id}?since_seq=N.
"""
from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sse_starlette.sse import EventSourceResponse

from pool.store import ActivityEvent, PoolStore


def _dumps(obj: Any) -> dict[str, Any]:
    return obj.model_dump()


def make_coordinator(store: PoolStore) -> FastAPI:
    app = FastAPI(title="agentpool")

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"agents": len(store.agents), "sessions": len(store.sessions)}

    @app.post("/")
    async def jsonrpc(req: Request) -> Any:
        body = await req.json()
        rpc_id = body.get("id")
        method = body.get("method")
        params = body.get("params") or {}

        def ok(result: Any) -> JSONResponse:
            return JSONResponse({"jsonrpc": "2.0", "id": rpc_id, "result": result})

        def err(code: int, message: str) -> JSONResponse:
            return JSONResponse(
                {"jsonrpc": "2.0", "id": rpc_id,
                 "error": {"code": code, "message": message}})

        def not_found(name: str) -> JSONResponse:
            return err(-32001, f"{name} not found")

        try:
            if method == "agents/register":
                rec = store.register(params["agentId"], params.get("card", {}),
                                     params.get("url", ""))
                return ok(_dumps(rec))
            if method == "agents/list":
                return ok([_dumps(a) for a in store.list_agents()])
            if method == "agents/heartbeat":
                rec = store.heartbeat(params["agentId"])
                return ok(_dumps(rec)) if rec else not_found("agent")
            if method == "agents/unregister":
                return ok({"removed": store.unregister(params["agentId"])})

            if method == "sessions/create":
                s = store.create_session(params.get("goal", ""),
                                         params.get("creator"))
                return ok(_dumps(s))
            if method == "sessions/join":
                s = store.join(params["sessionId"], params["agentId"])
                return ok(_dumps(s)) if s else not_found("session")
            if method == "sessions/leave":
                s = store.leave(params["sessionId"], params["agentId"])
                return ok(_dumps(s)) if s else not_found("session")
            if method == "sessions/set_goal":
                s = store.set_goal(params["sessionId"], params["goal"])
                return ok(_dumps(s)) if s else not_found("session")
            if method == "sessions/start":
                s = store.start(params["sessionId"])
                return ok(_dumps(s)) if s else not_found("session")
            if method == "sessions/status":
                s = store.get_session(params["sessionId"])
                return ok(_dumps(s)) if s else not_found("session")
            if method == "sessions/list":
                return ok([_dumps(s) for s in store.list_sessions()])

            if method == "activity/post":
                if store.get_session(params["sessionId"]) is None:
                    return not_found("session")
                ev = store.post_activity(
                    params["sessionId"], params["agentId"], params["type"],
                    text=params.get("text", ""),
                    target=params.get("targetAgentId"),
                    task_id=params.get("taskId"),
                    critique_id=params.get("critiqueId"))
                if ev is None:
                    return err(-32004, "agent not a member")
                return ok(_dumps(ev))
            if method == "activity/list":
                s = store.get_session(params["sessionId"])
                if not s:
                    return not_found("session")
                since = int(params.get("sinceSeq", 0))
                return ok([_dumps(e) for e in s.activity if e.seq >= since])

            if method == "critique/send":
                t = store.critique_send(params["sessionId"],
                                        params["authorAgentId"],
                                        params["targetAgentId"],
                                        params["text"])
                if t is None:
                    return err(-32002, "critique rejected")
                return ok(_dumps(t))
            if method == "critique/resolve":
                if store.get_session(params["sessionId"]) is None:
                    return not_found("session")
                t = store.critique_resolve(params["sessionId"],
                                           params["critiqueId"],
                                           params["agentId"], params["text"])
                if t is None:
                    thread = store.get_thread(params["critiqueId"])
                    if thread is None or thread.sessionId != params["sessionId"]:
                        return err(-32003, "critique not found")
                    return err(-32004, "not authorized to resolve this critique")
                return ok(_dumps(t))

            if method == "sessions/satisfy":
                s = store.satisfy(params["sessionId"], params["agentId"])
                return ok(_dumps(s)) if s else not_found("session")
        except KeyError as e:
            return err(-32602, f"missing param: {e}")
        except Exception as e:  # noqa: BLE001
            return err(-32603, str(e))

        return err(-32601, f"Method not found: {method}")

    @app.get("/activity/{session_id}")
    async def activity_stream(session_id: str, request: Request) -> EventSourceResponse:
        since = int(request.query_params.get("since_seq", 0))
        return EventSourceResponse(_watch(store, session_id, since))

    return app


async def _watch(store: PoolStore, session_id: str,
                 since: int) -> AsyncIterator[dict[str, str]]:
    s = store.get_session(session_id)
    if s is None:
        yield {"event": "error", "data": json.dumps({"error": "session not found"})}
        return

    # subscribe() returns the live queue plus a frozen snapshot taken atomically
    # at join time, so replay and live delivery are disjoint (no duplicates).
    q, snapshot = store.subscribe(session_id)
    try:
        for ev in snapshot:
            if ev.seq >= since:
                yield _sse(ev)
        while True:
            ev = await q.get()
            if ev.seq >= since:
                yield _sse(ev)
    finally:
        store.unsubscribe(session_id, q)


def _sse(ev: ActivityEvent) -> dict[str, str]:
    return {"event": ev.type, "data": ev.model_dump_json()}
