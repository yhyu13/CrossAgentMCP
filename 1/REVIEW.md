# Code review findings & resolutions

Review of `1/` (A2A pool coordinator, MCP bridge, FSM, simulated agents, tests).
Items are listed by severity; each records the finding and what was done.

## Fixed

### 1. `revising` state was dead code — FSM now real
- **Finding**: `critique_send` never set `s.state`; `revising` appeared only in two
  unreachable `_apply_activity` conditionals, so the loop ran entirely in
  `working`/`reviewing`.
- **Fix** (`pool/store.py`): `critique_send` sets `state = "revising"` when in
  `working/reviewing/revising`; `critique_resolve` routes its `self-improved`
  event through `_apply_activity`, which transitions `revising → reviewing`.
- **Test**: `test_critique_sets_revising_then_resolve_reviewing`.

### 2. Docs claimed a removed guard
- **Finding**: README + plan advertised a "no-progress detector" that was removed
  during implementation; only timeout + max-iterations exist.
- **Fix**: README "Termination guards" + "Security scope" sections and plan.md
  now state exactly two guards, and note the removed no-progress detector.

### 3. SSE replay race → duplicate delivery
- **Finding**: `_watch` replayed the buffer and drained the live queue; the
  subscribe/snapshot pattern was fragile and could double-deliver an event.
- **Fix** (`pool/store.py`, `pool/coordinator.py`): `subscribe()` now returns a
  frozen snapshot captured atomically at join time alongside the live queue;
  replay uses the snapshot, live delivery uses the queue — disjoint by construction.
- **Test**: `test_subscribe_snapshot_is_frozen`.

### 4. `critique_resolve` fabricated threads + skipped authorization
- **Finding**: unknown `critique_id` manufactured a fake `CritiqueThread`
  (empty author) and emitted `self-improved`; no check that `agent_id ==
  thread.targetAgentId` — nor that the thread belongs to the given session
  (`_threads` is a flat, process-wide dict keyed by `critique_id` alone).
- **Fix** (`pool/store.py`): unknown id → `None` (no fabrication); wrong session →
  `None`; wrong target → `None`. `pool/coordinator.py` returns JSON-RPC
  `-32003 "critique not found"` for unknown id **or** cross-session id (info
  hiding), and `-32004 "not authorized to resolve this critique"` for a same-
  session wrong target.
- **Tests**: `test_resolve_rejects_unknown_critique`, `test_resolve_rejects_wrong_target`,
  `test_resolve_rejects_cross_session`.

### 6. `a2a_post_activity type:"satisfied"` was a silent no-op
- **Finding**: posting `type:"satisfied"` through the generic activity tool did
  nothing (no `_apply_activity` handler), so sessions never converged via that path.
- **Fix** (`pool/store.py`): `post_activity` routes `type == "satisfied"` to a
  shared `_satisfy()` helper (same code path as `satisfy`/`declare_satisfaction`).
  A non-member `satisfied` now returns `-32004 "agent not a member"` instead of a
  misleading "session not found".
- **Tests**: `test_post_activity_satisfied_unifies`,
  `test_post_activity_satisfied_non_member_rejected`.

### Benchmark conflated expected failures
- **Finding**: failure scenarios printed in the same PASS-style table with no
  "expected vs actual" terminal-state check.
- **Fix** (`demo/benchmark.py`): each scenario declares `expect`; the report shows
  the expected state and a `N/N scenarios reached their expected terminal state`
  summary (currently 7/7).

### 7. `server.py` never booted for real agents
- **Finding**: `make_agent.py` scaffolded `server.py` + `.mcp.json` but nothing
  launched the server, so `a2a_inbox`/`a2a_respond` fail without manual startup.
- **Fix**: `make_agent.py` prints the exact `AGENT_PORT=… uv run python
  agents/<id>/server.py` launch command; README documents the same.

## Documented (not implemented)

### 5. No authentication / authorization
- Loopback-only demo; any process on the pool port can register/join/critique/
  satisfy as any id. `AgentStatus.offline` and `lastHeartbeat` are written but not
  enforced (no liveness sweeper). Documented in README "Security scope" rather
  than implementing auth, which is out of scope for the demo. The `{ROOT}` in
  `.mcp.json` is an absolute path, so generated agents are not relocatable.

## Left as-is (minor, by design)

- `_check_timeout` swallows a malformed `startTs` (only reachable via manual
  corruption; `startTs` is always internally generated).
- `_free_port()` is bind-then-close (TOCTOU-raceable at demo scale).
- The simulated agent's convergence is a token-string game (magic `APPROVED`
  substring), not semantic critique — inherent to a deterministic no-LLM sim;
  it validates plumbing, not judgment.
