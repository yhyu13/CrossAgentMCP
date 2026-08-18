"""Client for the pool control plane (mirrors `shared.a2a.A2AClient` style).

Speaks JSON-RPC 2.0 over HTTP to the pool coordinator, plus an SSE watch stream.
"""
from __future__ import annotations

import json
import uuid
from typing import Any, AsyncIterator

import httpx


class PoolClient:
    def __init__(self, base_url: str, http: httpx.AsyncClient | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._http = http or httpx.AsyncClient(timeout=30.0)
        self._owns_http = http is None

    async def _rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        payload = {"jsonrpc": "2.0", "id": str(uuid.uuid4()),
                   "method": method, "params": params}
        r = await self._http.post(self.base_url + "/", json=payload)
        r.raise_for_status()
        data = r.json()
        if "error" in data:
            raise RuntimeError(data["error"])
        return data["result"]

    # ---- registry ----

    async def register(self, agent_id: str, card: dict[str, Any],
                       url: str) -> dict[str, Any]:
        return await self._rpc("agents/register",
                               {"agentId": agent_id, "card": card, "url": url})

    async def list_agents(self) -> list[dict[str, Any]]:
        return await self._rpc("agents/list", {})

    async def heartbeat(self, agent_id: str) -> dict[str, Any]:
        return await self._rpc("agents/heartbeat", {"agentId": agent_id})

    async def unregister(self, agent_id: str) -> dict[str, Any]:
        return await self._rpc("agents/unregister", {"agentId": agent_id})

    # ---- sessions ----

    async def create_session(self, goal: str,
                             creator: str | None = None) -> dict[str, Any]:
        return await self._rpc("sessions/create",
                               {"goal": goal, "creator": creator})

    async def join_session(self, session_id: str, agent_id: str) -> dict[str, Any]:
        return await self._rpc("sessions/join",
                               {"sessionId": session_id, "agentId": agent_id})

    async def leave_session(self, session_id: str, agent_id: str) -> dict[str, Any]:
        return await self._rpc("sessions/leave",
                               {"sessionId": session_id, "agentId": agent_id})

    async def set_goal(self, session_id: str, goal: str) -> dict[str, Any]:
        return await self._rpc("sessions/set_goal",
                               {"sessionId": session_id, "goal": goal})

    async def start_session(self, session_id: str) -> dict[str, Any]:
        return await self._rpc("sessions/start", {"sessionId": session_id})

    async def session_status(self, session_id: str) -> dict[str, Any]:
        return await self._rpc("sessions/status", {"sessionId": session_id})

    async def list_sessions(self) -> list[dict[str, Any]]:
        return await self._rpc("sessions/list", {})

    # ---- activity ----

    async def post_activity(self, session_id: str, agent_id: str, type_: str,
                            text: str = "", target: str | None = None,
                            task_id: str | None = None,
                            critique_id: str | None = None) -> dict[str, Any]:
        return await self._rpc("activity/post", {
            "sessionId": session_id, "agentId": agent_id, "type": type_,
            "text": text, "targetAgentId": target, "taskId": task_id,
            "critiqueId": critique_id,
        })

    async def activity_list(self, session_id: str,
                            since_seq: int = 0) -> list[dict[str, Any]]:
        return await self._rpc("activity/list",
                               {"sessionId": session_id, "sinceSeq": since_seq})

    async def activity_subscribe(self, session_id: str,
                                 since_seq: int = 0) -> AsyncIterator[dict[str, Any]]:
        url = f"{self.base_url}/activity/{session_id}?since_seq={since_seq}"
        async with self._http.stream("GET", url,
                                     headers={"accept": "text/event-stream"}) as r:
            r.raise_for_status()
            async for line in r.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                yield json.loads(line[5:].strip())

    # ---- critiques ----

    async def critique_send(self, session_id: str, author: str, target: str,
                            text: str) -> dict[str, Any]:
        return await self._rpc("critique/send", {
            "sessionId": session_id, "authorAgentId": author,
            "targetAgentId": target, "text": text,
        })

    async def critique_resolve(self, session_id: str, critique_id: str,
                               agent_id: str, text: str) -> dict[str, Any]:
        return await self._rpc("critique/resolve", {
            "sessionId": session_id, "critiqueId": critique_id,
            "agentId": agent_id, "text": text,
        })

    async def declare_satisfaction(self, session_id: str,
                                   agent_id: str) -> dict[str, Any]:
        return await self._rpc("sessions/satisfy",
                               {"sessionId": session_id, "agentId": agent_id})

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()
