# CrossAgentMCP — Journey

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
