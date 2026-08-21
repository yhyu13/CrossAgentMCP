# JOURNEY — CrossAgentMCP

A chronological log of where this project came from, what it does now, and the
decisions measured along the way. Companion to [README.md](README.md)
(architecture reference) and [A2A.md](A2A.md) (the original vision).

---

## The vision (2026-08-18)

The idea, captured verbatim in [A2A.md](A2A.md):

1. any agent can register to an **A2A pool MCP**,
2. any agent can bind to a **session** among agents,
3. agents watch each other's activity, actively send **critique** after another
   agent finishes, critique each other, **self-improve**, and keep working with
   **no human intervention** until a shared goal satisfies all agents in the
   session.

That is the whole product: not "an AI that answers you", but a **swarm control
plane** where multiple specialized agents converge on a shared goal through
peer critique, and the only exit condition is *every member satisfied and zero
open critique threads*.

## Implementation (2026-08-18 → 08-19)

The minimal-but-faithful implementation landed in three layers:

| Layer | Component | Role |
|-------|-----------|------|
| Control plane | `crossagent/pool.py` (:9100) | registry / sessions / activity log / critique threads / per-agent satisfaction |
| Data plane | `crossagent/a2a.py` + `agents/*/server.py` (:9101..9103) | A2A v1.0 JSON-RPC per agent (SendMessage/GetTask/…), faithful to the spec |
| Orchestrator | `crossagent/orchestrator.py` | the only thing that advances time: round-robin headless `claude -p` turns until allSatisfied or a guard trips |

Key design constraints that held up:

- **The pool never routes work messages** — it is a coordination state store
  only. Peers talk A2A directly.
- **Per-agent identity** — with bearer tokens on, an agent cannot spoof
  another's activity/critique/satisfaction.
- **A critique invalidates the target's prior satisfaction** — you must
  re-confirm after fixing before the session converges. This is the mechanism
  that makes convergence meaningful instead of performative.
- **Session lifecycle**: `forming → working → revising → satisfied` (or
  `failed` on a no-progress guard).

The protocol surface (PascalCase methods, camelCase JSON, `SCREAMING_SNAKE_CASE`
enums) is exactly A2A v1.0.

## A2A MCP bridges (2026-08-19)

To make the pool usable *from* real agents, each role exposes the same stdio MCP
bridge (`crossagent/a2a_bridge.py`) with a different identity, port, and peer
map. The bridges expose two tool families:

- **Peer A2A** (data plane): `a2a_peers`, `a2a_send`, `a2a_stream`,
  `a2a_get_task`, `a2a_inbox`, `a2a_respond`, …
- **Pool** (control plane): `pool_register`, `session_*`, `activity_*`,
  `critique_*`, `resolve_critique`, `declare_satisfaction`.

Registered for three tools (paths pinned to `C:/Git-repo-AI/CrossAgentMCP`):

| Tool | Config | Servers |
|------|--------|---------|
| Kilo | `kilo.json` | `a2a-writer`, `a2a-critic`, `a2a-lead` |
| Claude Code | `agents/<role>/.mcp.json` | `a2a` |
| Codex | `.codex/config.toml` | `a2a-writer`, `a2a-critic`, `a2a-lead` |

Server lifecycle moved to `scripts/start-servers.ps1` / `stop-servers.ps1`
(background daemons, pid + logs under `.a2a/`).

---

## 2026-08-19 — A2A code-review demo against torchimpulse

**Goal:** prove the pool by having the three *real* agents (writer / critic / lead)
review a live codebase — `F:\XD\git-repo\torchimpulse` — and critique each other to
unanimous convergence, with no human in the loop.

### Built

- `demo/review_demo.py` — boots pool + 3 A2A servers in-process and runs the headless
  orchestrator with three real `claude -p` agents whose shared goal is to co-author a
  review of `torchimpulse` into `torchimpulse/A2A_REVIEW.md`.
- `demo/review_demo_scripted.py` — the same control-plane + data-plane lifecycle with
  deterministic stub agents (no claude, no token cost), replaying the real review
  findings as session content.

### Sequence

1. **First real run failed at the model layer, not the A2A layer.** Pool, register,
   session-create, and turn dispatch all worked; each `claude -p` turn died because the
   gateway (`llm-proxy.tapsvc.com`) returned 503 for every Claude-family model, and
   Claude Code's bare default (`claude-sonnet-4-6`) was rejected 403 (not in the
   gateway's `/v1/models`).
2. **Scripted demo** proved the full lifecycle end-to-end: register → session → writer
   artifact → critic critique (writer's early satisfaction reset to `None`) → spoofed
   `declare_satisfaction` rejected 403 → peer-A2A SendMessage/inbox/respond → resolve →
   unanimous convergence (`allSatisfied=true`, 0 open critiques).
3. **Gateway model discovery.** `/v1/models` exposes `deepseek/*`,
   `anthropic-claude/*` (haiku-4-5, opus-4-6..5, sonnet-5), `codex/*`, etc. — but no
   `claude-sonnet-4-6`.
4. **Repointed claude at deepseek.** Set `~/.claude/settings.json` `env` to
   `ANTHROPIC_MODEL=deepseek/deepseek-v4-pro` and the `*_DEFAULT_*_MODEL` variants to
   `deepseek/deepseek-v4-flash`. `claude -p` then answered correctly.
5. **Real 3-agent run converged after 5 turns** (writer → critic → lead → writer →
   critic): `satisfaction={writer,critic,lead: true}`, 0 open critiques, 11 progress
   events; produced a 223-line review with `file:line`-cited findings.

### Gotchas

- Claude Code's default model name is not gateway-portable. Pin `ANTHROPIC_MODEL` (and
  `ANTHROPIC_DEFAULT_{SONNET,OPUS,HAIKU}_MODEL`) to a fully-qualified gateway ID.
- The orchestrator's `_claude_runner` passes `dict(os.environ)` to the subprocess, so an
  `os.environ.setdefault("ANTHROPIC_MODEL", ...)` in a driver silently overrides
  `settings.json`. Keep the model config in exactly one place.
- Python stdout is block-buffered under a pipe, so orchestrator turn prints only flush
  on exit; add `flush=True` to watch turns live in a background process.
- `A2AClient(url)`'s URL is the *target* peer: `send_message` creates the task on the
  server at that URL (its inbox), not on "the sender".
- Agents run `claude -p --permission-mode bypassPermissions`; a review goal should be
  explicit about writing only the review file, otherwise agents may also edit the
  target repo.

---

## 2026-08-19 — A2A critic on M4_kimi

Second real external task through the pool (critic role driven directly via the
pool's JSON-RPC, same surface the `a2a-critic` MCP bridge exposes): a 3-agent
session (`writer` / `critic` / `lead`) with goal = *critique the M4_kimi
project* (Moment Shadow Mapping for UE4.27 desktop point lights).

**Session** `ed1399c2-1f70-4f42-af34-9f5cd12e4ad1` — state `revising`, 8 open
critique threads, critic `satisfied=false` (correct: defects remain).

The critique was evidence-grounded, not doc-pilled:

- all 6 M4 engine files are **uncommitted** working-tree edits (no M4 commit in
  git history),
- `UE4Editor.exe` still dated 2026-03-12 (the "pre-fix blocker" binary) while
  try27 claims GPU-level verification,
- the real project lives at `C:\Epic\UE_Project\UE27Chaos\TopDown27Chaos`,
  not where try27's relative path suggests,
- radial-depth Phase B is already implemented in the working tree but
  `M4_FIX_PLAN.md` still marks it as future work,
- moment cubemap escalated 16F → 32F (~6.3 MB/light) with no measured
  justification (H2 precision test never run),
- `USE_M4` define overloaded for every point-light VS — collides with the
  project's own documented include-guard bug,
- `-game` mode + M4 crash listed in try27 §5 but never filed as a blocker.

**Outcome**: the pool did exactly what it was designed for — an adversarial
review that *cannot* converge until the writer resolves every thread. The
session is parked in `revising` with the 8 threads waiting.

## Performance: measured, not vibes (2026-08-19)

Asked point-blank "is A2A faster than a single agent?", the honest answer came
from numbers, not marketing:

| Metric | Measured |
|--------|----------|
| Pool RPC latency (`ListAgents`/`SessionStatus`) | ~15 ms mean (p50 14.8, max 23.5) |
| Full register → session → activity → critique → satisfaction cycle | ~71 ms (~14 ms/call) |
| Stub 3-agent converged session (3 turns, no LLM) | 0.2 s wall |
| `benchmark.py --case stub-3` | 3 turns → converged, 1.3k in-tok total |

**Conclusion recorded for posterity**: A2A is *not* faster than a single agent
on the same task — it is strictly slower, because this orchestrator runs agents
**serially** (round-robin, one headless `claude -p` per turn) and each turn
re-feeds cumulative session context (token bloat: 284 → 434 → 582 input tokens
across 3 stub turns). The value A2A buys is **not speed**:

- role specialization (writer/critic/lead),
- adversarial peer critique with enforced re-confirmation,
- autonomous convergence with no human in the loop,
- explicit failure isolation (no-progress guard → `failed`).

**The next lever** if A2A ever needs to beat single-agent wall time:
decompose the goal into independent subtasks and run the agents **concurrently**
(the pool supports it architecturally; the orchestrator just does not exploit
it yet).

---

## 2026-08-21 — Repo migration, a real docs review, and measuring single-vs-multi

The repo moved from `C:/Git-repo-AI/` to `D:/GitRepo-AI/`. All hardcoded
`--directory` paths were repointed in `kilo.json` and the three
`agents/*/.mcp.json` (`.codex/config.toml` still pending if Codex is used).

### Second real external review: radiance-cascades-demo `3d/doc`

The three agents reviewed a 591-file documentation tree (a 3D radiance-cascades
GI demo's build log), driven against the *already-running* servers
(`scripts/start-servers.ps1`, open pool) via a new `demo/review_radiance.py` that
also dumps the full activity-log + critique-thread transcript. Converged:
`writer/critic/lead = true/true/true`, one critique opened and resolved. The
review (`…/3d/doc/A2A_REVIEW.md`) landed 1 Critical / 5 High / 4 Medium / 3 Low,
all `file:line`-cited — headline finding: the flagship `(4/D²)` consumer fix
documented in `journey.md:88` is absent from committed code.

### Measured single-agent vs 3-agent (same task, same model)

| mode | turns | wall | cost | judge /25 |
|---|---|---|---|---|
| single-monolithic | 1 | 38 s | $0.24 | 25 |
| single-iterative(6) | 6 | 650 s | $2.01 | 25 |
| 3-agent | 6 | 265 s | $2.13 | 10* |

`*` the 10/25 is a measurement artifact: the goal said "do not write files", so
the pool's reasoning stayed in the activity log and the judge only saw the lead's
status line — the pool holds coordination state, not the work product.

Two durable conclusions:

1. **Cost**: 3-agent ≈ single-iterative (~$2.1, ×1.06), both ~×9 the monolithic
   baseline. The pool sends ~1.06M prompt tokens (306K fresh + 755K cache-read)
   vs 260K all-fresh for iterative, but the prompt-cache discount flattens the bill.
2. **Time**: the pool is *faster* than a same-budget single self-reviewer
   (265 s vs 650 s) — a single agent re-reads its growing draft each round
   (output balloons 1.2K→6.7K tokens/round), while the pool keeps each turn flat.

### Head-to-head on the same tree: mono vs 3-agent (root pool)

`demo/compare_radiance.py` attached to the running stack and measured a **fused
single-agent** turn against the **3-agent orchestrator** on the same radiance
`3d/doc` review (same model, `claude -p --output-format json`):

| mode | turns | wall | in_tok | out_tok | cost | converged |
|---|---|---|---|---|---|---|
| mono-agent | 1 | 556 s | 128k | 33k | **$2.29** | yes (`MONO_REVIEW.md`) |
| 3-agent (root) | 5 | 855 s | 387k | 45k | **$4.56** | yes (all three true) |

Overhead vs mono: wall ×1.54, in_tok ×3.03, cost ×2.00. Artifacts:
`demo/output/{MONO_REVIEW,A2A_REVIEW,radiance_comparison}.json`. Committed
`ee9f8e7`.

This is the apples-to-apples measurement the toy payments-ledger run was not:
same heavy tree, same write-a-review goal. A2A is still not cheaper; it buys
role split + forced re-confirmation, and on this task it *did* produce a
comparable-length review (18.5 KB vs 19.2 KB).

### Same tree through the `1/` pool (first live `claude -p` loop)

`1/` previously only had simulated agents and JSON-payload replay. A new
`1/demo/compare_radiance.py` boots that pool on **auto-selected ports** (so it
does not collide with root :9100–9103) and runs real `claude -p` agents through
`shared.mcp_bridge`:

| impl | 3-agent turns | wall | cost | converged |
|---|---|---|---|---|
| root `crossagent/` | 5 | 855 s | $4.56 | **yes** `{w,c,l: true}` |
| `1/` pool | 9 | 1293 s | $7.57 | **no** — `reviewing`, lead false |

Not a systematic proof that `1/` is “worse.” The cost/wall gap is mostly *did
not stop*: root’s orchestrator **requires** `declare_satisfaction` every turn;
`1/`’s live prompt only asks, and `satisfy()` is one-way `True` (no
`satisfied=false`). Lead still wrote `A2A_REVIEW_1.md` (20 KB, C1/C2
`file:line`-cited). Structural deltas (protocol, auth, FSM, who advances time)
are in README § root vs `1/`.

### Executed the documented next lever: concurrent scheduling

`Orchestrator` gained `schedule: "parallel"` (default `"serial"` unchanged): each
round runs every agent concurrently on the same pre-round snapshot (bulk-
synchronous), then posts their `finished` events together. `maxTurns` and the
no-progress guard both count individual agent runs (a parallel round contributes
`len(agents)` runs to each), so serial/parallel are comparable — though a round is
atomic, so the turn budget overshoots by up to `len(agents)-1`. A mid-round
failure persists the round's successes, marks the session failed, and propagates
(same failure surface as serial, without discarding completed work). Covered by
`test_parallel_schedule_runs_agents_concurrently_and_converges` (max concurrency
== 3, convergence) and `test_parallel_schedule_persists_successes_when_an_agent_fails`
(mid-round failure keeps sibling work); 26 tests pass.

### Efficiency-only comparison + how-to-run guide (committed)

Three more artifacts landed the same day:

- `demo/compare_efficiency.py` — the head-to-head efficiency run *without* a judge:
  one fused single-agent turn vs the 3-agent orchestrator on the payments-ledger
  question. Measured: single 47.6 s / $0.24 (41.7k in-tok) vs 3-agent 313 s / $2.22
  (332k in-tok, 6 turns) — cost ×9.2, wall ×6.6. Same shape as the quality run
  above: the pool is strictly more expensive than one fused turn; it buys role
  split + enforced re-confirmation, not speed.
- `demo/compare_quality.py` + `demo/compare_efficiency.py` are now the canonical
  single-vs-multi harnesses (the quality one adds a blind judge; table above).
  `demo/review_radiance.py` attaches to the already-running stack to review a tree
  and dump the full activity/critique transcript.
- README gained a「快速上手 root vs `1/`」section: explicit
  `start-servers.ps1` / `stop-servers.ps1` commands for root, and
  `run_session.py` / `real_review.py` / `compare_radiance.py` / `pool.server` for
  `1/`, plus the `schedule: "parallel"` toggle.

Parallel scheduling, the path migration (`C:/Git-repo-AI` → `D:/GitRepo-AI`), and
the three new demo scripts + their output JSONs are committed together with this
entry; 26 tests pass.

---

## Where it stands

- [x] A2A pool control plane (registry / sessions / activity / critique / goal)
- [x] Faithful A2A v1.0 data plane per agent
- [x] Headless orchestrator with convergence + no-progress guards
- [x] MCP bridges for Kilo / Claude Code / Codex
- [x] Server start/stop scripts
- [x] Unit tests + smoke + benchmark harness
- [x] Real-agent review demo converging on torchimpulse (5 turns)
- [x] First real external critique run through the pool (M4_kimi, parked in `revising`)
- [x] Concurrent (parallel) agent scheduling (`schedule: "parallel"`; serial default)
- [x] Radiance `3d/doc` 3-agent review converging (root pool, 5 turns)
- [x] Mono vs 3-agent measured on that tree (root: cost ×2.00, wall ×1.54, converged)
- [x] First live `claude -p` loop through the `1/` pool (9 turns, lead never satisfied)
- [x] Payments-ledger single-vs-3-agent efficiency + quality comparison (blind judge)
- [ ] Long-term state persistence (pool is in-memory, resets on restart)
- [ ] A run where the writer actually *resolves* the 8 open M4_kimi critique threads
- [ ] `1/` live loop with a mandatory per-turn satisfaction contract (to match root)
