# agentpool — multi-agent A2A pool with critique-and-converge sessions

Extends the `claude-a2a` P2P pattern into a multi-agent pool:

1. **Any agent can register** to the pool coordinator (exposed to each agent as MCP tools).
2. **Any agent can bind to a session** among agents (dynamic N-member sessions with a shared goal).
3. Agents **watch each other's activity**, **critique** after another finishes,
   **self-improve**, and keep working **with no human intervention** until the shared
   goal satisfies every member — enforced by a coordinator state machine with
   termination guards.

## Topology

```mermaid
flowchart TB
    subgraph Pool["pool/ — coordinator :9100"]
        R["Registry"]
        SM["SessionManager"]
        AB["ActivityBus (SSE)"]
        CL["ConsensusLedger"]
    end
    subgraph Agents
        A1["agent-1 :9101"]; A2["agent-2 :9102"]; A3["agent-N"]
    end
    A1 -- "MCP bridge" --> Pool
    A2 -- "MCP bridge" --> Pool
    A3 -- "MCP bridge" --> Pool
    A1 <-- "A2A P2P" --> A2
```

Control plane (register/session/activity/critique/consensus) is centralized in the
pool; real work + direct messaging stays P2P A2A.

## Layout

```
shared/a2a.py            A2A protocol (message/send, tasks/get, SSE, push, respond/inbox)
shared/pool_client.py    client for the pool control plane
shared/mcp_bridge.py     per-agent MCP bridge (pool tools + P2P tools)
pool/store.py            Registry, SessionManager, ActivityBus, ConsensusLedger, FSM
pool/coordinator.py      JSON-RPC control plane + SSE watch
pool/server.py           pool entry (default :9100)
agent-template/          parametrized agent (server.py, CLAUDE.md, .mcp.json, make_agent.py)
demo/simulated_agent.py  deterministic agent (no LLM) exercising the full loop
demo/run_session.py      end-to-end runner (pool + N agents -> satisfied/failed)
tests/                   pool / session / consensus tests
```

## Quick start

```bash
uv sync
uv run pytest                                   # unit tests
uv run python demo/run_session.py --num-agents 3   # full autonomous loop, no LLM
```

Run the pool standalone:

```bash
uv run python -m pool.server                     # pool on :9100
```

Generate a concrete agent (for real Claude Code sessions):

```bash
uv run python agent-template/make_agent.py --id agent-1 --port 9101 --role "writes section 1"
# boot the agent's own A2A server first (agentpool_inbox / agentpool_respond need it):
#   set AGENT_PORT=9101 && uv run python agents/agent-1/server.py
cd agents/agent-1 && claude                     # loads its .mcp.json MCP server
```

Note: `make_agent.py` only scaffolds the agent — it does **not** launch
`server.py`. Start that server with the matching `AGENT_PORT` before running
`claude`, or the peer-messaging tools will fail.

## Session state machine

`forming -> working -> reviewing -> revising -> satisfied | failed`

- An agent posts `finished` → session enters `reviewing`.
- Peers post `critique` against flawed output → opens a thread, revokes the target's
  approval, session enters `revising`.
- Target resolves critiques (`self-improved`, back to `reviewing`) and re-posts `finished`.
- A member posts `satisfied` when it has no objections.
- Session reaches `satisfied` when **all members are satisfied and no critique
  threads are open**.

Termination guards (exactly two): **max iterations** (a cap on total critiques,
`session.iteration` is incremented only in `critique_send`) and **global timeout**.
Both → `failed`. There is no separate no-progress detector.

## Security scope

Loopback-only demo. The pool has **no authentication or authorization**: any
process that can reach the pool port may register as any `agentId`, join any
session, send critiques, resolve them, or declare satisfaction on another agent's
behalf. `AgentStatus.offline` and `lastHeartbeat` are written but not enforced
(no liveness sweeper). Do not expose the pool beyond `127.0.0.1`.

## MCP tools (per agent)

`agentpool_register`, `agentpool_list_agents`, `agentpool_send_to`, `agentpool_inbox`, `agentpool_respond`,
`agentpool_session_create`, `agentpool_session_join`, `agentpool_session_leave`, `agentpool_session_status`,
`agentpool_session_list`, `agentpool_set_goal`, `agentpool_post_activity`, `agentpool_watch`, `agentpool_critique`,
`agentpool_resolve_critique`, `agentpool_declare_satisfaction`.
