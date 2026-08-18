"""Pool control-plane state: registry, sessions, activity bus, consensus ledger.

All state is in-memory and single-process (loopback demo scale). The pool is the
central coordinator; agents keep their own A2A servers for the P2P data plane.
"""
from __future__ import annotations

import asyncio
import uuid
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


AgentStatus = Literal["active", "offline"]
ActivityType = Literal[
    "joined", "left", "started", "finished", "artifact",
    "critique", "self-improved", "satisfied", "blocked",
    "session-completed", "session-failed",
]
SessionState = Literal[
    "forming", "working", "reviewing", "revising", "satisfied", "failed",
]


class AgentRecord(BaseModel):
    agentId: str
    card: dict[str, Any] = Field(default_factory=dict)
    url: str = ""
    registeredAt: str = Field(default_factory=now_iso)
    lastHeartbeat: str = Field(default_factory=now_iso)
    status: AgentStatus = "active"


class ActivityEvent(BaseModel):
    seq: int = 0
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    sessionId: str
    agentId: str
    type: ActivityType
    targetAgentId: str | None = None
    taskId: str | None = None
    critiqueId: str | None = None
    payload: str = ""
    ts: str = Field(default_factory=now_iso)


class CritiqueThread(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    sessionId: str
    authorAgentId: str
    targetAgentId: str
    text: str
    open: bool = True
    history: list[dict[str, Any]] = Field(default_factory=list)
    ts: str = Field(default_factory=now_iso)


class Session(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    goal: str = ""
    members: list[str] = Field(default_factory=list)
    state: SessionState = "forming"
    iteration: int = 0
    startTs: str = Field(default_factory=now_iso)
    satisfaction: dict[str, bool] = Field(default_factory=dict)
    openCritiques: list[str] = Field(default_factory=list)
    activity: list[ActivityEvent] = Field(default_factory=list)
    maxIterations: int = 200
    timeoutSec: float = 300.0
    failedReason: str | None = None


class PoolStore:
    def __init__(self) -> None:
        self.agents: dict[str, AgentRecord] = {}
        self.sessions: dict[str, Session] = {}
        self._threads: dict[str, CritiqueThread] = {}
        self._subscribers: dict[str, list[asyncio.Queue[ActivityEvent]]] = {}

    # ---- registry ----

    def register(self, agent_id: str, card: dict[str, Any], url: str) -> AgentRecord:
        rec = AgentRecord(agentId=agent_id, card=card, url=url, status="active")
        self.agents[agent_id] = rec
        return rec

    def list_agents(self) -> list[AgentRecord]:
        return list(self.agents.values())

    def heartbeat(self, agent_id: str) -> AgentRecord | None:
        rec = self.agents.get(agent_id)
        if rec:
            rec.lastHeartbeat = now_iso()
            rec.status = "active"
        return rec

    def unregister(self, agent_id: str) -> bool:
        return self.agents.pop(agent_id, None) is not None

    def get_agent(self, agent_id: str) -> AgentRecord | None:
        return self.agents.get(agent_id)

    # ---- sessions ----

    def create_session(self, goal: str, creator: str | None = None) -> Session:
        s = Session(goal=goal)
        if creator and creator in self.agents:
            s.members.append(creator)
            s.satisfaction[creator] = False
            self._emit(s, "joined", creator)
        self.sessions[s.id] = s
        self._advance(s)
        return s

    def get_session(self, session_id: str) -> Session | None:
        return self.sessions.get(session_id)

    def list_sessions(self) -> list[Session]:
        return list(self.sessions.values())

    def join(self, session_id: str, agent_id: str) -> Session | None:
        s = self.sessions.get(session_id)
        if not s:
            return None
        if s.state in ("satisfied", "failed"):
            return None
        if agent_id not in s.members:
            s.members.append(agent_id)
            s.satisfaction[agent_id] = False
            self._emit(s, "joined", agent_id)
        self._advance(s)
        return s

    def leave(self, session_id: str, agent_id: str) -> Session | None:
        s = self.sessions.get(session_id)
        if not s:
            return None
        if agent_id in s.members:
            s.members.remove(agent_id)
            s.satisfaction.pop(agent_id, None)
            self._emit(s, "left", agent_id)
            self._fail(s, f"member {agent_id} left the session")
        return s

    def set_goal(self, session_id: str, goal: str) -> Session | None:
        s = self.sessions.get(session_id)
        if not s:
            return None
        s.goal = goal
        self._advance(s)
        return s

    def start(self, session_id: str) -> Session | None:
        s = self.sessions.get(session_id)
        if not s:
            return None
        if s.state == "forming":
            s.state = "working"
            self._advance(s)
        return s

    # ---- activity ----

    def post_activity(self, session_id: str, agent_id: str, type_: str,
                      text: str = "", target: str | None = None,
                      task_id: str | None = None,
                      critique_id: str | None = None) -> ActivityEvent | None:
        s = self.sessions.get(session_id)
        if not s:
            return None
        if type_ == "satisfied":
            if agent_id not in s.members:
                return None
            return self._satisfy(s, agent_id, text)
        event = self._emit(s, type_, agent_id, payload=text, target=target,
                           task_id=task_id, critique_id=critique_id)
        self._apply_activity(s, event)
        self._advance(s)
        return event

    # ---- critiques ----

    def critique_send(self, session_id: str, author: str, target: str,
                      text: str) -> CritiqueThread | None:
        s = self.sessions.get(session_id)
        if not s:
            return None
        if s.state in ("satisfied", "failed"):
            return None
        if author not in s.members or target not in s.members:
            return None
        thread = CritiqueThread(sessionId=session_id, authorAgentId=author,
                                targetAgentId=target, text=text)
        self._threads[thread.id] = thread
        s.openCritiques.append(thread.id)
        s.satisfaction[target] = False
        s.iteration += 1
        if s.state in ("working", "reviewing", "revising"):
            s.state = "revising"
        self._emit(s, "critique", author, payload=text, target=target,
                   critique_id=thread.id)
        self._advance(s)
        return thread

    def critique_resolve(self, session_id: str, critique_id: str, agent_id: str,
                         text: str) -> CritiqueThread | None:
        s = self.sessions.get(session_id)
        if not s:
            return None
        thread = self._threads.get(critique_id)
        if thread is None:
            return None  # unknown critique id — do not fabricate a thread
        if thread.sessionId != session_id:
            return None  # critique belongs to a different session
        if thread.targetAgentId != agent_id:
            return None  # only the target may resolve its own critique
        thread.open = False
        thread.history.append({"agentId": agent_id, "text": text, "ts": now_iso()})
        with suppress(ValueError):
            s.openCritiques.remove(critique_id)
        event = self._emit(s, "self-improved", agent_id, payload=text,
                           critique_id=critique_id)
        self._apply_activity(s, event)  # revising -> reviewing
        self._advance(s)
        return thread

    def get_thread(self, critique_id: str) -> CritiqueThread | None:
        return self._threads.get(critique_id)

    # ---- satisfaction ----

    def satisfy(self, session_id: str, agent_id: str) -> Session | None:
        s = self.sessions.get(session_id)
        if not s:
            return None
        if agent_id not in s.members:
            return s
        self._satisfy(s, agent_id)
        return s

    # ---- internals ----

    def _satisfy(self, s: Session, agent_id: str, text: str = "") -> ActivityEvent:
        s.satisfaction[agent_id] = True
        event = self._emit(s, "satisfied", agent_id, payload=text)
        self._advance(s)
        return event

    def _emit(self, s: Session, type_: str, agent_id: str, payload: str = "",
              target: str | None = None, task_id: str | None = None,
              critique_id: str | None = None) -> ActivityEvent:
        seq = len(s.activity)
        event = ActivityEvent(seq=seq, sessionId=s.id, agentId=agent_id,
                              type=type_, targetAgentId=target, taskId=task_id,
                              critiqueId=critique_id, payload=payload)
        s.activity.append(event)
        for q in self._subscribers.get(s.id, []):
            q.put_nowait(event)
        return event

    def _apply_activity(self, s: Session, event: ActivityEvent) -> None:
        t = event.type
        if t == "finished":
            if s.state in ("working", "revising", "reviewing"):
                s.state = "reviewing"
        elif t == "self-improved":
            if s.state == "revising":
                s.state = "reviewing"
        elif t == "blocked":
            self._fail(s, f"agent {event.agentId} blocked: {event.payload}")

    def _fail(self, s: Session, reason: str) -> None:
        if s.state in ("satisfied", "failed"):
            return
        s.state = "failed"
        s.failedReason = reason
        self._emit(s, "session-failed", "pool", payload=reason)

    def _check_timeout(self, s: Session) -> None:
        if s.state in ("satisfied", "failed"):
            return
        try:
            start = datetime.fromisoformat(s.startTs)
            elapsed = (datetime.now(timezone.utc) - start).total_seconds()
        except (ValueError, TypeError):
            return
        if elapsed > s.timeoutSec:
            self._fail(s, "session timed out")

    def _advance(self, s: Session) -> None:
        """Recompute state after a mutation; enforce guards and consensus."""
        if s.state in ("satisfied", "failed"):
            return

        if s.state == "forming" and s.goal and len(s.members) >= 2:
            s.state = "working"

        self._check_timeout(s)
        if s.state == "failed":
            return
        if s.iteration >= s.maxIterations:
            self._fail(s, "max iterations reached")
            return

        if (s.members
                and all(s.satisfaction.get(m) is True for m in s.members)
                and not s.openCritiques):
            s.state = "satisfied"
            self._emit(s, "session-completed", "pool",
                       payload="shared goal satisfied by all members")

    # ---- pub/sub for SSE watch ----

    def subscribe(self, session_id: str) -> tuple[asyncio.Queue[ActivityEvent],
                                                  list[ActivityEvent]]:
        """Return a live queue plus a frozen snapshot of current activity.

        The snapshot is captured atomically at subscription time (no `await`
        between appending the queue and copying the buffer), so replayed
        events (snapshot) and live events (queue) never overlap.
        """
        q: asyncio.Queue[ActivityEvent] = asyncio.Queue()
        self._subscribers.setdefault(session_id, []).append(q)
        s = self.sessions.get(session_id)
        snapshot = list(s.activity) if s else []
        return q, snapshot

    def unsubscribe(self, session_id: str, q: asyncio.Queue[ActivityEvent]) -> None:
        with suppress(ValueError):
            self._subscribers.get(session_id, []).remove(q)
