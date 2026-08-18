"""Minimal A2A protocol implementation (Google Agent2Agent spec subset).

Implements:
- Agent Card discovery at /.well-known/agent-card.json
- JSON-RPC 2.0 endpoint at / supporting:
    message/send         — submit message, returns Task
    message/stream       — submit message, returns SSE stream of updates
    tasks/get            — fetch task by id
    tasks/cancel         — cancel a task
    tasks/resubscribe    — re-attach SSE stream to existing task
    tasks/pushNotificationConfig/set
    tasks/pushNotificationConfig/get
    tasks/respond        — non-standard helper: agent completes input-required task
    tasks/inbox          — non-standard helper: list tasks awaiting reply

Task states: submitted, working, input-required, completed, canceled, failed, rejected.
"""
from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Literal

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

TaskState = Literal[
    "submitted", "working", "input-required",
    "completed", "canceled", "failed", "rejected",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class TextPart(BaseModel):
    kind: Literal["text"] = "text"
    text: str


class Message(BaseModel):
    role: Literal["user", "agent"]
    parts: list[TextPart]
    messageId: str = Field(default_factory=lambda: str(uuid.uuid4()))
    taskId: str | None = None
    contextId: str | None = None


class TaskStatus(BaseModel):
    state: TaskState
    message: Message | None = None
    timestamp: str = Field(default_factory=now_iso)


class Artifact(BaseModel):
    artifactId: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str | None = None
    parts: list[TextPart]


class Task(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    contextId: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: TaskStatus
    history: list[Message] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    kind: Literal["task"] = "task"


class PushNotificationConfig(BaseModel):
    url: str
    token: str | None = None


class AgentCard(BaseModel):
    name: str
    description: str
    version: str = "1.0.0"
    url: str
    protocolVersion: str = "0.2.0"
    capabilities: dict[str, Any] = Field(default_factory=lambda: {
        "streaming": True,
        "pushNotifications": True,
    })
    defaultInputModes: list[str] = Field(default_factory=lambda: ["text/plain"])
    defaultOutputModes: list[str] = Field(default_factory=lambda: ["text/plain"])
    skills: list[dict[str, Any]] = Field(default_factory=list)


# ---------- Events emitted on the bus ----------

class TaskEvent(BaseModel):
    """Wire format for SSE / push payloads."""
    kind: Literal["task", "status-update", "artifact-update"]
    taskId: str
    contextId: str
    final: bool = False
    status: TaskStatus | None = None
    artifact: Artifact | None = None
    task: Task | None = None


# ---------- Store ----------

class TaskStore:
    def __init__(self) -> None:
        self.tasks: dict[str, Task] = {}
        self.push_configs: dict[str, PushNotificationConfig] = {}
        self._subscribers: list[asyncio.Queue[TaskEvent]] = []
        self._push_tasks: set[asyncio.Task[None]] = set()

    # -- pub/sub --
    def subscribe(self) -> asyncio.Queue[TaskEvent]:
        q: asyncio.Queue[TaskEvent] = asyncio.Queue()
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[TaskEvent]) -> None:
        with suppress(ValueError):
            self._subscribers.remove(q)

    def _publish(self, event: TaskEvent) -> None:
        for q in list(self._subscribers):
            q.put_nowait(event)
        cfg = self.push_configs.get(event.taskId)
        if cfg:
            self._schedule_push(cfg, event)

    def _schedule_push(self, cfg: PushNotificationConfig, event: TaskEvent) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        coro = _deliver_push(cfg, event)
        task = loop.create_task(coro)
        self._push_tasks.add(task)
        task.add_done_callback(self._push_tasks.discard)

    # -- task ops --
    def create_from_message(self, msg: Message, initial_state: TaskState = "input-required") -> Task:
        msg.taskId = msg.taskId or str(uuid.uuid4())
        msg.contextId = msg.contextId or str(uuid.uuid4())
        task = Task(
            id=msg.taskId,
            contextId=msg.contextId,
            status=TaskStatus(state=initial_state),
            history=[msg],
        )
        self.tasks[task.id] = task
        self._publish(TaskEvent(kind="task", taskId=task.id, contextId=task.contextId,
                                task=task, final=False))
        return task

    def get(self, task_id: str) -> Task | None:
        return self.tasks.get(task_id)

    def cancel(self, task_id: str) -> Task | None:
        t = self.tasks.get(task_id)
        if not t:
            return None
        if t.status.state in ("completed", "canceled", "failed"):
            return t
        t.status = TaskStatus(state="canceled")
        self._publish(TaskEvent(kind="status-update", taskId=t.id, contextId=t.contextId,
                                status=t.status, final=True))
        return t

    def respond(self, task_id: str, text: str) -> Task | None:
        t = self.tasks.get(task_id)
        if not t:
            return None
        reply = Message(role="agent", parts=[TextPart(text=text)],
                        taskId=t.id, contextId=t.contextId)
        t.history.append(reply)
        artifact = Artifact(name="response", parts=[TextPart(text=text)])
        t.artifacts.append(artifact)
        self._publish(TaskEvent(kind="artifact-update", taskId=t.id, contextId=t.contextId,
                                artifact=artifact))
        t.status = TaskStatus(state="completed", message=reply)
        self._publish(TaskEvent(kind="status-update", taskId=t.id, contextId=t.contextId,
                                status=t.status, final=True))
        return t

    def inbox(self) -> list[Task]:
        return [t for t in self.tasks.values() if t.status.state == "input-required"]

    def set_push_config(self, task_id: str, cfg: PushNotificationConfig) -> bool:
        if task_id not in self.tasks:
            return False
        self.push_configs[task_id] = cfg
        return True

    def get_push_config(self, task_id: str) -> PushNotificationConfig | None:
        return self.push_configs.get(task_id)

    async def aclose(self) -> None:
        for t in list(self._push_tasks):
            t.cancel()
            with suppress(BaseException):
                await t


async def _deliver_push(cfg: PushNotificationConfig, event: TaskEvent) -> None:
    headers = {"content-type": "application/json"}
    if cfg.token:
        headers["X-A2A-Notification-Token"] = cfg.token
    payload = event.model_dump(exclude_none=True)
    async with httpx.AsyncClient(timeout=10.0) as client:
        with suppress(Exception):
            await client.post(cfg.url, json=payload, headers=headers)


# ---------- SSE ----------

async def _sse_stream(store: TaskStore, q: asyncio.Queue[TaskEvent],
                      task_id: str, rpc_id: Any) -> AsyncIterator[dict[str, str]]:
    try:
        while True:
            event = await q.get()
            if event.taskId != task_id:
                continue
            payload = {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": event.model_dump(exclude_none=True),
            }
            yield {"event": event.kind, "data": json.dumps(payload, default=str)}
            if event.final:
                return
    finally:
        store.unsubscribe(q)


# ---------- JSON-RPC server ----------

def make_app(card: AgentCard, store: TaskStore) -> FastAPI:
    app = FastAPI(title=card.name)

    @app.get("/.well-known/agent-card.json")
    def agent_card() -> dict[str, Any]:
        return card.model_dump()

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
                 "error": {"code": code, "message": message}},
            )

        if method == "message/send":
            msg = Message(**params["message"])
            task = store.create_from_message(msg)
            return ok(task.model_dump())

        if method == "message/stream":
            msg = Message(**params["message"])
            q = store.subscribe()
            task = store.create_from_message(msg)
            return EventSourceResponse(_sse_stream(store, q, task.id, rpc_id))

        if method == "tasks/resubscribe":
            tid = params["id"]
            if tid not in store.tasks:
                return err(-32001, "Task not found")
            q = store.subscribe()
            return EventSourceResponse(_sse_stream(store, q, tid, rpc_id))

        if method == "tasks/get":
            t = store.get(params["id"])
            return ok(t.model_dump()) if t else err(-32001, "Task not found")

        if method == "tasks/cancel":
            t = store.cancel(params["id"])
            return ok(t.model_dump()) if t else err(-32001, "Task not found")

        if method == "tasks/respond":
            t = store.respond(params["id"], params["text"])
            return ok(t.model_dump()) if t else err(-32001, "Task not found")

        if method == "tasks/inbox":
            return ok([t.model_dump() for t in store.inbox()])

        if method == "tasks/pushNotificationConfig/set":
            cfg = PushNotificationConfig(**params["pushNotificationConfig"])
            ok_set = store.set_push_config(params["taskId"], cfg)
            if not ok_set:
                return err(-32001, "Task not found")
            return ok({"taskId": params["taskId"], "pushNotificationConfig": cfg.model_dump()})

        if method == "tasks/pushNotificationConfig/get":
            cfg = store.get_push_config(params["taskId"])
            if not cfg:
                return err(-32001, "Push config not found")
            return ok({"taskId": params["taskId"], "pushNotificationConfig": cfg.model_dump()})

        return err(-32601, f"Method not found: {method}")

    return app


# ---------- A2A client ----------

class A2AClient:
    def __init__(self, base_url: str, http: httpx.AsyncClient | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._http = http or httpx.AsyncClient(timeout=30.0)
        self._owns_http = http is None

    async def get_card(self) -> dict[str, Any]:
        r = await self._http.get(f"{self.base_url}/.well-known/agent-card.json")
        r.raise_for_status()
        return r.json()

    async def _rpc(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        payload = {"jsonrpc": "2.0", "id": str(uuid.uuid4()),
                   "method": method, "params": params}
        r = await self._http.post(self.base_url + "/", json=payload)
        r.raise_for_status()
        data = r.json()
        if "error" in data:
            raise RuntimeError(data["error"])
        return data["result"]

    async def send_message(self, text: str, context_id: str | None = None) -> dict[str, Any]:
        msg = Message(role="user", parts=[TextPart(text=text)], contextId=context_id)
        return await self._rpc("message/send", {"message": msg.model_dump()})

    async def get_task(self, task_id: str) -> dict[str, Any]:
        return await self._rpc("tasks/get", {"id": task_id})

    async def cancel_task(self, task_id: str) -> dict[str, Any]:
        return await self._rpc("tasks/cancel", {"id": task_id})

    async def respond(self, task_id: str, text: str) -> dict[str, Any]:
        return await self._rpc("tasks/respond", {"id": task_id, "text": text})

    async def inbox(self) -> list[dict[str, Any]]:
        return await self._rpc("tasks/inbox", {})

    async def set_push_config(self, task_id: str, url: str,
                              token: str | None = None) -> dict[str, Any]:
        cfg: dict[str, Any] = {"url": url}
        if token:
            cfg["token"] = token
        return await self._rpc("tasks/pushNotificationConfig/set",
                               {"taskId": task_id, "pushNotificationConfig": cfg})

    async def get_push_config(self, task_id: str) -> dict[str, Any]:
        return await self._rpc("tasks/pushNotificationConfig/get", {"taskId": task_id})

    async def stream_message(self, text: str,
                             context_id: str | None = None,
                             ) -> AsyncIterator[dict[str, Any]]:
        """SSE stream. Yields parsed JSON-RPC results until a `final` event."""
        msg = Message(role="user", parts=[TextPart(text=text)], contextId=context_id)
        payload = {"jsonrpc": "2.0", "id": str(uuid.uuid4()),
                   "method": "message/stream",
                   "params": {"message": msg.model_dump()}}
        async with self._http.stream("POST", self.base_url + "/", json=payload,
                                     headers={"accept": "text/event-stream"}) as r:
            r.raise_for_status()
            ctype = r.headers.get("content-type", "")
            if "text/event-stream" not in ctype:
                body = await r.aread()
                data = json.loads(body)
                if "error" in data:
                    raise RuntimeError(data["error"])
                raise RuntimeError(f"unexpected response: {data}")
            async for line in r.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = json.loads(line[5:].strip())
                result = data.get("result", {})
                yield result
                if result.get("final"):
                    break

    async def resubscribe(self, task_id: str) -> AsyncIterator[dict[str, Any]]:
        payload = {"jsonrpc": "2.0", "id": str(uuid.uuid4()),
                   "method": "tasks/resubscribe", "params": {"id": task_id}}
        async with self._http.stream("POST", self.base_url + "/", json=payload,
                                     headers={"accept": "text/event-stream"}) as r:
            r.raise_for_status()
            ctype = r.headers.get("content-type", "")
            if "text/event-stream" not in ctype:
                body = await r.aread()
                data = json.loads(body)
                if "error" in data:
                    raise RuntimeError(data["error"])
                raise RuntimeError(f"unexpected response: {data}")
            async for line in r.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                data = json.loads(line[5:].strip())
                result = data.get("result", {})
                yield result
                if result.get("final"):
                    break

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()


async def run_server(app: FastAPI, host: str, port: int) -> None:
    import uvicorn
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


def serve_blocking(app: FastAPI, host: str, port: int) -> None:
    asyncio.run(run_server(app, host, port))
