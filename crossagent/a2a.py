"""A2A v1.0 protocol library (JSON-RPC 2.0 over HTTP).

Faithful implementation of the A2A v1.0 data model and JSON-RPC method surface
per `D:\\GitRepo-AI\\A2A\\specification\\a2a.proto` + `docs/specification.md`:

- JSON field names are camelCase; enum values are SCREAMING_SNAKE_CASE strings
  (``"TASK_STATE_COMPLETED"``, ``"ROLE_USER"``).
- Core JSON-RPC methods (PascalCase): SendMessage, SendStreamingMessage, GetTask,
  ListTasks, CancelTask, SubscribeToTask, the four *TaskPushNotificationConfig*
  methods, and GetExtendedAgentCard.
- Two **non-standard** helpers kept for the agent-in-the-loop demo (as claude-a2a
  does): ``respond`` (complete an input-required task) and ``inbox`` (list tasks
  awaiting a reply).

Structure mirrors claude-a2a's ``shared/a2a.py`` (TaskStore pub/sub, ``make_app``
dispatch, ``A2AClient``, ``serve_blocking``) but with the v1.0 wire format.
"""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from contextlib import suppress
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Literal

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

# --------------------------------------------------------------------------- #
# Enums (serialized as SCREAMING_SNAKE_CASE strings per ProtoJSON)
# --------------------------------------------------------------------------- #

TaskState = Literal[
    "TASK_STATE_SUBMITTED",
    "TASK_STATE_WORKING",
    "TASK_STATE_COMPLETED",
    "TASK_STATE_FAILED",
    "TASK_STATE_CANCELED",
    "TASK_STATE_REJECTED",
    "TASK_STATE_INPUT_REQUIRED",
    "TASK_STATE_AUTH_REQUIRED",
]

Role = Literal["ROLE_USER", "ROLE_AGENT"]

# Terminal task states: the stream closes and no further messages are accepted.
TERMINAL_STATES: frozenset[str] = frozenset({
    "TASK_STATE_COMPLETED",
    "TASK_STATE_FAILED",
    "TASK_STATE_CANCELED",
    "TASK_STATE_REJECTED",
})

# A2A v1.0 JSON-RPC error codes (specification.md §3.3.2).
ERR_TASK_NOT_FOUND = -32001
ERR_TASK_NOT_CANCELABLE = -32002
ERR_PUSH_NOT_SUPPORTED = -32003
ERR_UNSUPPORTED_OPERATION = -32004
ERR_METHOD_NOT_FOUND = -32601

logger = logging.getLogger(__name__)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dump(model: BaseModel, **kw: Any) -> dict[str, Any]:
    return model.model_dump(exclude_none=True, **kw)


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #

class Part(BaseModel):
    """A2A Part. oneof {text, url, data}; text is the common case."""
    text: str | None = None
    url: str | None = None
    data: Any | None = None
    filename: str | None = None
    mediaType: str | None = None
    metadata: dict[str, Any] | None = None


class Message(BaseModel):
    role: Role
    parts: list[Part]
    messageId: str = Field(default_factory=lambda: str(uuid.uuid4()))
    contextId: str | None = None
    taskId: str | None = None
    metadata: dict[str, Any] | None = None
    extensions: list[str] | None = None
    referenceTaskIds: list[str] | None = None


class TaskStatus(BaseModel):
    state: TaskState
    message: Message | None = None
    timestamp: str = Field(default_factory=now_iso)


class Artifact(BaseModel):
    artifactId: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str | None = None
    description: str | None = None
    parts: list[Part]
    metadata: dict[str, Any] | None = None
    extensions: list[str] | None = None


class Task(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    contextId: str = Field(default_factory=lambda: str(uuid.uuid4()))
    status: TaskStatus
    artifacts: list[Artifact] = Field(default_factory=list)
    history: list[Message] = Field(default_factory=list)
    metadata: dict[str, Any] | None = None


class TaskStatusUpdateEvent(BaseModel):
    taskId: str
    contextId: str
    status: TaskStatus
    metadata: dict[str, Any] | None = None


class TaskArtifactUpdateEvent(BaseModel):
    taskId: str
    contextId: str
    artifact: Artifact
    append: bool = False
    lastChunk: bool = True
    metadata: dict[str, Any] | None = None


class StreamResponse(BaseModel):
    """oneof {task, message, statusUpdate, artifactUpdate}."""
    task: Task | None = None
    message: Message | None = None
    statusUpdate: TaskStatusUpdateEvent | None = None
    artifactUpdate: TaskArtifactUpdateEvent | None = None


class AuthenticationInfo(BaseModel):
    scheme: str
    credentials: str | None = None


class TaskPushNotificationConfig(BaseModel):
    tenant: str | None = None
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    taskId: str | None = None
    url: str
    token: str | None = None
    authentication: AuthenticationInfo | None = None


class AgentInterface(BaseModel):
    url: str
    protocolBinding: str = "JSONRPC"
    tenant: str | None = None
    protocolVersion: str = "1.0"


class AgentProvider(BaseModel):
    url: str
    organization: str


class AgentSkill(BaseModel):
    id: str
    name: str
    description: str
    tags: list[str] = Field(default_factory=list)
    examples: list[str] | None = None
    inputModes: list[str] | None = None
    outputModes: list[str] | None = None


class AgentCapabilities(BaseModel):
    streaming: bool = True
    pushNotifications: bool = True
    extensions: list[dict[str, Any]] | None = None
    extendedAgentCard: bool = False


class AgentCard(BaseModel):
    name: str
    description: str
    supportedInterfaces: list[AgentInterface]
    version: str = "1.0.0"
    provider: AgentProvider | None = None
    documentationUrl: str | None = None
    capabilities: AgentCapabilities = Field(default_factory=AgentCapabilities)
    defaultInputModes: list[str] = Field(default_factory=lambda: ["text/plain"])
    defaultOutputModes: list[str] = Field(default_factory=lambda: ["text/plain"])
    skills: list[AgentSkill] = Field(default_factory=list)
    iconUrl: str | None = None


# --------------------------------------------------------------------------- #
# Store (in-memory + pub/sub)
# --------------------------------------------------------------------------- #

class TaskStore:
    """In-memory task store with a pub/sub bus for SSE/push."""

    def __init__(self) -> None:
        self.tasks: dict[str, Task] = {}
        self.push_configs: dict[str, list[TaskPushNotificationConfig]] = {}
        self._subscribers: list[asyncio.Queue[StreamResponse]] = []
        self._push_tasks: set[asyncio.Task[None]] = set()
        self._push_client: httpx.AsyncClient | None = None

    # -- pub/sub --
    def subscribe(self) -> asyncio.Queue[StreamResponse]:
        q: asyncio.Queue[StreamResponse] = asyncio.Queue()
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[StreamResponse]) -> None:
        with suppress(ValueError):
            self._subscribers.remove(q)

    def _publish(self, ev: StreamResponse) -> None:
        for q in list(self._subscribers):
            q.put_nowait(ev)
        tid = self._event_task_id(ev)
        for cfg in self.push_configs.get(tid, []):
            self._schedule_push(cfg, ev)

    def _schedule_push(self, cfg: TaskPushNotificationConfig, ev: StreamResponse) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        client = self._push_client
        if client is None:
            client = self._push_client = httpx.AsyncClient(timeout=10.0)
        coro = _deliver_push(client, cfg, ev)
        task = loop.create_task(coro)
        self._push_tasks.add(task)
        task.add_done_callback(self._push_tasks.discard)

    @staticmethod
    def _event_task_id(ev: StreamResponse) -> str | None:
        if ev.task:
            return ev.task.id
        if ev.statusUpdate:
            return ev.statusUpdate.taskId
        if ev.artifactUpdate:
            return ev.artifactUpdate.taskId
        return ev.message.taskId if ev.message else None

    # -- task ops --
    def create_from_message(
        self, msg: Message, initial_state: TaskState = "TASK_STATE_INPUT_REQUIRED",
    ) -> Task:
        msg.taskId = msg.taskId or str(uuid.uuid4())
        msg.contextId = msg.contextId or str(uuid.uuid4())
        task = Task(
            id=msg.taskId,
            contextId=msg.contextId,
            status=TaskStatus(state=initial_state),
            history=[msg],
        )
        self.tasks[task.id] = task
        self._publish(StreamResponse(task=task))
        return task

    def get(self, task_id: str) -> Task | None:
        return self.tasks.get(task_id)

    def list_tasks(self) -> list[Task]:
        return list(self.tasks.values())

    def cancel(self, task_id: str) -> Task | None:
        t = self.tasks.get(task_id)
        if not t:
            return None
        if t.status.state in TERMINAL_STATES:
            return t
        t.status = TaskStatus(state="TASK_STATE_CANCELED")
        self._publish(StreamResponse(statusUpdate=TaskStatusUpdateEvent(
            taskId=t.id, contextId=t.contextId, status=t.status)))
        return t

    def respond(self, task_id: str, text: str) -> Task | None:
        t = self.tasks.get(task_id)
        if not t:
            return None
        reply = Message(role="ROLE_AGENT", parts=[Part(text=text)],
                        taskId=t.id, contextId=t.contextId)
        t.history.append(reply)
        artifact = Artifact(name="response", parts=[Part(text=text)])
        t.artifacts.append(artifact)
        self._publish(StreamResponse(artifactUpdate=TaskArtifactUpdateEvent(
            taskId=t.id, contextId=t.contextId, artifact=artifact)))
        t.status = TaskStatus(state="TASK_STATE_COMPLETED", message=reply)
        self._publish(StreamResponse(statusUpdate=TaskStatusUpdateEvent(
            taskId=t.id, contextId=t.contextId, status=t.status)))
        return t

    def inbox(self) -> list[Task]:
        return [t for t in self.tasks.values()
                if t.status.state == "TASK_STATE_INPUT_REQUIRED"]

    # -- push configs --
    def set_push_config(self, cfg: TaskPushNotificationConfig) -> bool:
        if not cfg.taskId or cfg.taskId not in self.tasks:
            return False
        self.push_configs.setdefault(cfg.taskId, []).append(cfg)
        return True

    def get_push_config(self, task_id: str, cfg_id: str) -> TaskPushNotificationConfig | None:
        for c in self.push_configs.get(task_id, []):
            if c.id == cfg_id:
                return c
        return None

    def list_push_configs(self, task_id: str) -> list[TaskPushNotificationConfig]:
        return list(self.push_configs.get(task_id, []))

    def delete_push_config(self, task_id: str, cfg_id: str) -> bool:
        cfgs = self.push_configs.get(task_id, [])
        before = len(cfgs)
        self.push_configs[task_id] = [c for c in cfgs if c.id != cfg_id]
        return len(self.push_configs[task_id]) < before

    async def aclose(self) -> None:
        for t in list(self._push_tasks):
            t.cancel()
            with suppress(BaseException):
                await t
        if self._push_client is not None:
            await self._push_client.aclose()
            self._push_client = None


async def _deliver_push(client: httpx.AsyncClient, cfg: TaskPushNotificationConfig,
                        ev: StreamResponse) -> None:
    headers = {"content-type": "application/json"}
    if cfg.token:
        headers["X-A2A-Notification-Token"] = cfg.token
    try:
        await client.post(cfg.url, json=_dump(ev), headers=headers)
    except Exception as e:  # noqa: BLE001 - a failed push must not break the session
        logger.warning("push notification to %s failed: %s", cfg.url, e)


def _is_terminal(ev: StreamResponse) -> bool:
    return bool(ev.statusUpdate and ev.statusUpdate.status.state in TERMINAL_STATES)


# --------------------------------------------------------------------------- #
# SSE
# --------------------------------------------------------------------------- #

async def _sse_stream(store: TaskStore, q: asyncio.Queue[StreamResponse],
                      task_id: str, rpc_id: Any) -> AsyncIterator[dict[str, str]]:
    try:
        while True:
            ev = await q.get()
            tid = store._event_task_id(ev)
            if tid != task_id:
                continue
            payload = {"jsonrpc": "2.0", "id": rpc_id, "result": _dump(ev)}
            yield {"data": json.dumps(payload, default=str)}
            if _is_terminal(ev):
                return
    finally:
        store.unsubscribe(q)


# --------------------------------------------------------------------------- #
# JSON-RPC server
# --------------------------------------------------------------------------- #

def make_app(card: AgentCard, store: TaskStore) -> FastAPI:
    app = FastAPI(title=card.name)

    @app.get("/.well-known/agent-card.json")
    def agent_card() -> dict[str, Any]:
        return _dump(card)

    @app.post("/")
    async def jsonrpc(req: Request) -> Any:
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

        def err(code: int, message: str) -> JSONResponse:
            return JSONResponse({"jsonrpc": "2.0", "id": rpc_id,
                                 "error": {"code": code, "message": message}})

        try:
            if method == "SendMessage":
                msg = Message(**params["message"])
                task = store.create_from_message(msg)
                return ok({"task": _dump(task)})

            if method == "SendStreamingMessage":
                msg = Message(**params["message"])
                q = store.subscribe()
                task = store.create_from_message(msg)
                return EventSourceResponse(_sse_stream(store, q, task.id, rpc_id))

            if method == "GetTask":
                t = store.get(params["id"])
                return ok(_dump(t)) if t else err(ERR_TASK_NOT_FOUND, "Task not found")

            if method == "ListTasks":
                tasks = store.list_tasks()
                return ok({"tasks": [_dump(t) for t in tasks],
                           "nextPageToken": "", "pageSize": len(tasks),
                           "totalSize": len(tasks)})

            if method == "CancelTask":
                t = store.cancel(params["id"])
                if not t:
                    return err(ERR_TASK_NOT_FOUND, "Task not found")
                return ok(_dump(t))

            if method == "SubscribeToTask":
                tid = params["id"]
                t = store.get(tid)
                if not t:
                    return err(ERR_TASK_NOT_FOUND, "Task not found")
                if t.status.state in TERMINAL_STATES:
                    return err(ERR_UNSUPPORTED_OPERATION, "Task is in a terminal state")
                q = store.subscribe()
                return EventSourceResponse(_sse_stream(store, q, tid, rpc_id))

            if method == "CreateTaskPushNotificationConfig":
                cfg = TaskPushNotificationConfig(**params)
                if not store.set_push_config(cfg):
                    return err(ERR_TASK_NOT_FOUND, "Task not found")
                return ok(_dump(cfg))

            if method == "GetTaskPushNotificationConfig":
                cfg = store.get_push_config(params["taskId"], params["id"])
                if not cfg:
                    return err(ERR_TASK_NOT_FOUND, "Push config not found")
                return ok(_dump(cfg))

            if method == "ListTaskPushNotificationConfigs":
                return ok({"configs": [_dump(c) for c in store.list_push_configs(params["taskId"])],
                           "nextPageToken": ""})

            if method == "DeleteTaskPushNotificationConfig":
                store.delete_push_config(params["taskId"], params["id"])
                return ok({})

            if method == "GetExtendedAgentCard":
                return ok(_dump(card))

            # -- non-standard helpers (agent-in-the-loop demo) --
            if method == "respond":
                t = store.respond(params["id"], params["text"])
                return ok(_dump(t)) if t else err(ERR_TASK_NOT_FOUND, "Task not found")

            if method == "inbox":
                return ok([_dump(t) for t in store.inbox()])

            return err(ERR_METHOD_NOT_FOUND, f"Method not found: {method}")
        except (KeyError, TypeError, ValueError) as e:
            return err(-32602, f"Invalid params: {e}")

    return app


# --------------------------------------------------------------------------- #
# A2A client
# --------------------------------------------------------------------------- #

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

    async def send_message(self, text: str, context_id: str | None = None,
                           task_id: str | None = None) -> dict[str, Any]:
        msg = Message(role="ROLE_USER", parts=[Part(text=text)],
                      contextId=context_id, taskId=task_id)
        return await self._rpc("SendMessage", {"message": _dump(msg)})

    async def get_task(self, task_id: str) -> dict[str, Any]:
        return await self._rpc("GetTask", {"id": task_id})

    async def list_tasks(self) -> dict[str, Any]:
        return await self._rpc("ListTasks", {})

    async def cancel_task(self, task_id: str) -> dict[str, Any]:
        return await self._rpc("CancelTask", {"id": task_id})

    async def respond(self, task_id: str, text: str) -> dict[str, Any]:
        return await self._rpc("respond", {"id": task_id, "text": text})

    async def inbox(self) -> list[dict[str, Any]]:
        return await self._rpc("inbox", {})

    async def _stream(self, method: str, params: dict[str, Any],
                      ) -> AsyncIterator[dict[str, Any]]:
        payload = {"jsonrpc": "2.0", "id": str(uuid.uuid4()),
                   "method": method, "params": params}
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
                yield data.get("result", {})

    async def stream_message(self, text: str, context_id: str | None = None,
                             ) -> AsyncIterator[dict[str, Any]]:
        msg = Message(role="ROLE_USER", parts=[Part(text=text)], contextId=context_id)
        async for result in self._stream("SendStreamingMessage", {"message": _dump(msg)}):
            yield result

    async def subscribe_to_task(self, task_id: str) -> AsyncIterator[dict[str, Any]]:
        async for result in self._stream("SubscribeToTask", {"id": task_id}):
            yield result

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()


# --------------------------------------------------------------------------- #
# Server launch
# --------------------------------------------------------------------------- #

async def run_server(app: FastAPI, host: str, port: int) -> None:
    import uvicorn
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()


def serve_blocking(app: FastAPI, host: str, port: int) -> None:
    asyncio.run(run_server(app, host, port))
