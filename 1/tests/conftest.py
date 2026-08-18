"""Test fixtures: in-process pool coordinator via httpx ASGI transport.

SSE watch tests use a real uvicorn server on a free loopback port.
"""
from __future__ import annotations

import asyncio
import socket
from contextlib import asynccontextmanager
from typing import AsyncIterator

import httpx
import pytest_asyncio
import uvicorn

from pool.coordinator import make_coordinator
from pool.store import PoolStore
from shared.pool_client import PoolClient


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest_asyncio.fixture
async def store() -> PoolStore:
    return PoolStore()


@pytest_asyncio.fixture
async def app(store: PoolStore):
    return make_coordinator(store)


@pytest_asyncio.fixture
async def client(app) -> AsyncIterator[PoolClient]:
    """ASGI-transport client: in-process, no socket. Non-streaming tests only."""
    transport = httpx.ASGITransport(app=app)
    http = httpx.AsyncClient(transport=transport, base_url="http://test")
    c = PoolClient("http://test", http=http)
    yield c
    await http.aclose()


@asynccontextmanager
async def _serve(app, port: int) -> AsyncIterator[None]:
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    for _ in range(50):
        if server.started:
            break
        await asyncio.sleep(0.05)
    try:
        yield
    finally:
        server.should_exit = True
        await task


@pytest_asyncio.fixture
async def live_client(app) -> AsyncIterator[tuple[PoolClient, str]]:
    """Real uvicorn server on loopback. Required for SSE watch tests."""
    port = _free_port()
    base = f"http://127.0.0.1:{port}"
    async with _serve(app, port):
        c = PoolClient(base)
        try:
            yield c, base
        finally:
            await c.aclose()


async def make_agents(pool: PoolClient, *ids: str) -> None:
    """Register N agents so sessions can be created and joined."""
    for i, agent_id in enumerate(ids):
        await pool.register(agent_id, {"name": agent_id}, f"http://127.0.0.1:{9000 + i}")


async def make_session(pool: PoolClient, goal: str, *members: str) -> dict:
    await make_agents(pool, *members)
    s = await pool.create_session(goal)
    for m in members:
        await pool.join_session(s["id"], m)
    return await pool.session_status(s["id"])
