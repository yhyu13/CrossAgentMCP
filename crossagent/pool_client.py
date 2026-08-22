"""Client for the A2A pool control plane (mirrors :class:`crossagent.pool.PoolStore`)."""
from __future__ import annotations

import uuid
from typing import Any

import httpx


class PoolClient:
    def __init__(self, base_url: str, http: httpx.AsyncClient | None = None,
                 token: str | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._http = http or httpx.AsyncClient(timeout=30.0)
        self._owns_http = http is None
        self._token = token

    async def _rpc(self, method: str, params: dict[str, Any]) -> Any:
        payload = {"jsonrpc": "2.0", "id": str(uuid.uuid4()),
                   "method": method, "params": params}
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else None
        r = await self._http.post(self.base_url + "/", json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
        if "error" in data:
            raise RuntimeError(data["error"])
        return data["result"]

    # -- registry --
    async def register(self, agent_id: str, card: dict[str, Any] | None = None,
                       url: str | None = None) -> dict[str, Any]:
        return await self._rpc("Register", {"agentId": agent_id, "card": card, "url": url})

    async def unregister(self, agent_id: str) -> bool:
        return await self._rpc("Unregister", {"agentId": agent_id})

    async def list_agents(self) -> list[dict[str, Any]]:
        return await self._rpc("ListAgents", {})

    async def get_agent(self, agent_id: str) -> dict[str, Any]:
        return await self._rpc("GetAgent", {"agentId": agent_id})

    async def heartbeat(self, agent_id: str) -> bool:
        return await self._rpc("Heartbeat", {"agentId": agent_id})

    # -- sessions --
    async def session_create(self, goal: str, members: list[str] | None = None,
                             session_id: str | None = None,
                             max_critiques: int = 200) -> dict[str, Any]:
        return await self._rpc("SessionCreate",
                               {"goal": goal, "members": members,
                                "sessionId": session_id, "maxCritiques": max_critiques})

    async def session_join(self, session_id: str, agent_id: str) -> dict[str, Any]:
        return await self._rpc("SessionJoin", {"sessionId": session_id, "agentId": agent_id})

    async def session_leave(self, session_id: str, agent_id: str) -> dict[str, Any]:
        return await self._rpc("SessionLeave", {"sessionId": session_id, "agentId": agent_id})

    async def session_list(self) -> list[dict[str, Any]]:
        return await self._rpc("SessionList", {})

    async def session_get(self, session_id: str) -> dict[str, Any]:
        return await self._rpc("SessionGet", {"sessionId": session_id})

    async def set_goal(self, session_id: str, goal: str) -> dict[str, Any]:
        return await self._rpc("SetGoal", {"sessionId": session_id, "goal": goal})

    # -- activity --
    async def post_activity(self, session_id: str, agent_id: str, type_: str,
                            payload: dict[str, Any] | None = None,
                            target_agent_id: str | None = None,
                            task_id: str | None = None) -> dict[str, Any]:
        return await self._rpc("PostActivity", {
            "sessionId": session_id, "agentId": agent_id, "type": type_,
            "payload": payload, "targetAgentId": target_agent_id, "taskId": task_id})

    async def activity_since(self, session_id: str, since_seq: int) -> list[dict[str, Any]]:
        return await self._rpc("ActivitySince", {"sessionId": session_id, "sinceSeq": since_seq})

    # -- critique --
    async def critique(self, session_id: str, from_agent: str, target_agent: str,
                       text: str, target_seq: int | None = None) -> dict[str, Any]:
        return await self._rpc("Critique", {
            "sessionId": session_id, "fromAgent": from_agent,
            "targetAgent": target_agent, "text": text, "targetSeq": target_seq})

    async def resolve_critique(self, session_id: str, critique_id: str,
                               resolver_agent_id: str, text: str) -> dict[str, Any]:
        return await self._rpc("ResolveCritique", {
            "sessionId": session_id, "critiqueId": critique_id,
            "resolverAgentId": resolver_agent_id, "text": text})

    async def list_critiques(self, session_id: str) -> list[dict[str, Any]]:
        return await self._rpc("ListCritiques", {"sessionId": session_id})

    async def mark_failed(self, session_id: str, reason: str | None = None) -> dict[str, Any]:
        return await self._rpc("MarkFailed", {"sessionId": session_id, "reason": reason})

    # -- goal --
    async def declare_satisfaction(self, session_id: str, agent_id: str,
                                   satisfied: bool = True,
                                   summary: str | None = None) -> dict[str, Any]:
        return await self._rpc("DeclareSatisfaction", {
            "sessionId": session_id, "agentId": agent_id,
            "satisfied": satisfied, "summary": summary})

    async def session_status(self, session_id: str) -> dict[str, Any]:
        return await self._rpc("SessionStatus", {"sessionId": session_id})

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()
