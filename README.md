# CrossAgentMCP — an A2A pool MCP

A minimal implementation of the [A2A.md](A2A.md) vision: an **A2A pool MCP** where

1. any agent can **register** into the shared pool,
2. any agent can **bind** into a multi-agent **session**,
3. agents **watch each other's activity**, **critique** peers after they finish,
   self-improve, and keep working with **no human intervention** until a shared goal
   is satisfied by every agent in the session.

## Architecture

Three process types:

```
        ┌────────────────── POOL (:9100, FastAPI HTTP JSON-RPC) ──────────────────┐
        │  registry / sessions / activity / critique / goal  (in-memory control   │
        │  plane — does NOT route work messages)                                  │
        └──────────────────────────────────────────────────────────────────────────┘
            ▲ pool JSON-RPC (PoolClient)            ▲ pool JSON-RPC (per-agent bridge)
            │                                       │
      ┌─────┴──────┐    peer A2A (SendMessage/GetTask)   ┌─────┴──────┐
      │ orchestrator│◄──────────────────────────────────►│ agent-N    │ … :9101..9103
      └────────────┘      each agent runs its own         └────────────┘
          headless            v1.0 A2A HTTP server
```

- **Pool** (`crossagent/pool.py`) — central control plane: registry, sessions, an
  append-only per-session activity log, critique threads, and per-agent satisfaction.
- **Agents** — each is a directory (`agents/<role>/`) with:
  - `server.py` — a v1.0 A2A HTTP server (peer data plane);
  - `.mcp.json` — registers the `a2a` stdio MCP bridge (`crossagent/a2a_bridge.py`);
  - `CLAUDE.md` — the role + per-turn contract.
- **Orchestrator** (`crossagent/orchestrator.py`) — the only component that advances
  time: registers agents, creates the session, then round-robin runs each agent
  headlessly (`claude -p`), feeding it the activity/critique delta since its last turn,
  until all members are satisfied (or a turn budget / no-progress guard trips).

## Protocol

Faithful to **A2A v1.0** (PascalCase JSON-RPC methods, camelCase JSON,
`SCREAMING_SNAKE_CASE` enums). See `crossagent/a2a.py`.

## Setup

```bash
uv sync          # Python 3.11+ venv + deps
```

## Usage

```bash
make test        # unit tests (protocol / pool / orchestrator with fake agents)
make smoke       # pool + 2 A2A servers up; scripted round-trip (no real Claude)
make demo        # full headless 3-agent demo (writer / critic / lead) — needs `claude`
```

### Demo goal

`demo/goal.json` asks three agents — **writer**, **critic**, **lead** — to co-author
`demo/output/design.md` (a URL-shortener design) until all three declare satisfied.

## Notes

- `.mcp.json` files hardcode the repo path `D:/GitRepo-AI/CrossAgentMCP` (matching the
  claude-a2a reference); update it if you relocate the repo.
- The pool and agent servers keep state **in memory**; they reset on restart.
