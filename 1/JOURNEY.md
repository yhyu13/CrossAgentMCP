# JOURNEY — A2A Pool MCP (project under `1/`)

Two-column progress history of this collaboration.

| # | ME (you) | YOU (me) |
|---|---|---|
| 1 | Gave the 3 requirements — (1) any agent registers to an A2A pool MCP, (2) any agent binds to a session, (3) agents watch → critique → self-improve, no human intervention until the shared goal satisfies every member — plus the two repo paths, asked for a **plan** | Explored `D:\GitRepo-AI\A2A` and `D:\GitRepo-AI\claude-a2a`, read `shared/a2a.py`, `mcp_bridge.py`, servers, Makefile; produced the architecture plan (central control plane + P2P data plane, session FSM, consensus) |
| 2 | "dump plan first" | Wrote the plan to `plan.md` |
| 3 | "impl under 1, no question ask, do until done" | Built the whole project in `1/`: `pool/store.py` (registry + sessions + activity bus + consensus FSM), `pool/coordinator.py` (JSON-RPC + SSE), `pool/server.py`, `shared/pool_client.py`, extended `shared/mcp_bridge.py` (16 tools), `agent-template/` (+ `make_agent.py`), `demo/simulated_agent.py` + `run_session.py`, tests (pool/session/consensus/MCP-stdio). Fixed: `mcp` 2.0→1.x pin (decorator API), simulated-agent watch-cursor bug, demo convergence. Result: 20 tests green, demo converges to `satisfied` |
| 4 | "design some test cases and show me result (token spent, etc) each conversation, timing etc" | Added `demo/metrics.py` (token estimates ~4 chars/token + per-event timing) and `demo/benchmark.py` (7 scenarios: converge-3/5/8, contentious-3r, blocked, member-leave, max-iterations). Fixed: `maxIterations` 20→200, agent crash on transient SSE drop, removed false "no-progress" guard (max-iterations + timeout bound the loop instead). Produced the results table + per-agent breakdown |
| 5 | Pasted a benchmark failure (`email.message` import traceback) | Root-caused a **port collision**: a separate `CrossAgentMCP` project at the workspace root (`crossagent/`, its own `benchmark.py`, `hermes` runner) was live on 9100–9103 running `--case disagreement-3`. Made `demo/benchmark.py` + `run_session.py` auto-select free ports. Verified 20 tests + all 7 scenarios green (did not touch the root project's process) |
| 6 | "use journey skills to dump … JOURNEY.md, two col ME and YOU progress history" | Wrote this `JOURNEY.md` |
| 7 | Did a full code review of `1/`, reported 7 defects (dead `revising` state, stale no-progress docs, SSE replay race, `critique_resolve` fabrication/no-authz, missing auth, `satisfied` no-op, `server.py` never booted) + smaller items | Fixed the consensus-core defects (1/3/4/6) + docs (2) + benchmark expected-state aggregation (7/7) + make_agent launch hint; documented the no-auth scope; added 5 regression tests → **25 tests pass**; wrote `REVIEW.md` |
| 8 | Follow-up review: found `critique_resolve` was still not session-scoped (flat `_threads` keyed by id alone → cross-session resolve closes another session's thread) + two nits (`satisfied` non-member → misleading "session not found"; `-32003` conflated unknown-id vs wrong-target) | Added `thread.sessionId != session_id` guard; split errors into `-32003 "critique not found"` (unknown/cross-session) vs `-32004 "not authorized"`; fixed `activity/post` non-member error. Added 2 tests → **27 tests pass**, demo PASS, benchmark 7/7 |

## Current state

- `1/` — full implementation: pool + coordinator + MCP bridge + agent template + deterministic simulated agents + benchmark.
- **27 unit/integration tests pass**; end-to-end demo and all 7 benchmark scenarios converge/fail correctly.
- Ports are auto-selected (`--pool-port 0`), so it runs alongside the root `crossagent/` project without collision.
- Token figures are estimates (proxy) — real LLM token spend requires real Claude Code agents via `shared/mcp_bridge.py`.
- `REVIEW.md` records the review findings and resolutions (items 1/3/4/6 fixed; 2/7 fixed; 5 documented as loopback scope).
