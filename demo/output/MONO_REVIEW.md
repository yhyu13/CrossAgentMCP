# MONO_REVIEW — 3D Radiance Cascades Documentation Tree

**Reviewer:** senior graphics-engineer documentation reviewer (single agent, direct file read)
**Date:** 2026-08-21
**Target:** `D:/GitRepo-My/radiance-cascades-demo/3d/doc/` (~591 `.md` files across `1`–`7`, `8_shadertoy`, `9_shadertoy2`, `10_refactor`, `11_generalization`, `12_cornell_rc_audit`, plus `journey.md` and `13_renderdoc_auto_rdoc.md`).
**Method:** read `journey.md` and `13_renderdoc_auto_rdoc.md` in full; read the current-era docs (`12_cornell_rc_audit/*`, `10_refactor/*`, `11_generalization/*`) in full; mapped every numbered directory and read a representative sample of each plan/impl/critic/reply set. Every finding below was re-checked against the actual files during drafting.

---

## 1. Overview

The tree documents the construction, debugging, and eventual re-grounding of a C++17 / OpenGL 4.3 radiance-cascades global-illumination demo. It is a **process archive**, not a static reference manual: it records a human ("ME") steering an AI ("YOU") through ~12 eras, organized as **plan / impl / critic / reply** units, threaded by `journey.md` — a two-column chronology that is the de-facto index.

The arc the documents tell is unusually honest for a research project:

1. **2D→3D migration** (`1/`, `2/`) — analytic SDF, Cornell box, first cascade.
2. **Cascade architecture** (`3/`–`5/`) — directional storage, octahedral atlas, Sponza SDF, GPU SDF, perf.
3. **Visibility / leak** (`6/`) — bake-time per-bin visibility.
4. **Hybrid RC + MBRC correction** (`7/`) — path-traced reference, per-pixel correction, then a 31-commit measurement program (v2.0→v2.5) that is judged **FAILED** and closed (`7/v25_z_mbrc_correction_failure_learnings.md`).
5. **ShaderToy pivot** (`8_shadertoy/`, `9_shadertoy2/`) — adopt the reference implementation.
6. **Data-driven refactor** (`10_refactor/`) — strangler app-shell rebuild, parity gates G0–G10.
7. **Generalization design** (`11_generalization/`) — Cornell charts → real meshes.
8. **Cornell-box audit** (`12_cornell_rc_audit/`) — a 5-agent adversarial audit that surfaces the tree's headline defect.

The repeated lesson is a *methodology*, not a graphics trick: **diff against the reference first, measure only to validate the fix, and pre-commit the verdict band so a miss is a STOP, not a retry.** The tree is itself a product of that discipline — nearly every decision is paired with a critic and a reply, and failed lines are closed explicitly rather than silently dropped.

---

## 2. Structure & Coverage

### Directory map

| Dir | Era (`journey.md`) | Theme | Notes |
|---|---|---|---|
| `1/` | Era 0 | Quick-start / build scaffolding | 6 files; **heavily stale** (H-1). |
| `2/` | Era 0 | Phase 0–1.5 execution + error-fix log | 19 files + `phase0/ phase1/ phase1.5/`. |
| `3/` | Plan + critic-of-critic chain | Phases 6–14 (capture, temporal, banding) | `cluade_plan/`, `codex_plan/`, `codex_plan_critic/`, `codex_plan_critic_critic/`. |
| `4/` | Era 2 | Sponza SDF "Steps 0–7" | `claude_plan/` + 13 critic reviews + `claude_reply/`. |
| `5/` | Era 2 | GPU SDF + perf "Steps 8–12" | `claude_plan/` + `perf/` + 13 critic reviews. |
| `6/` | Era 4 | Visibility / leak fix | `claude_plan/`, `kilo_plan/`. |
| `7/` | Eras 5–8 | Hybrid RC, PT, v2.x, v3 M0/M1 | Flat plan/impl pairs + `critic/`. |
| `8_shadertoy/` | Era 8 | v4 ShaderToy adoption | plan/impl + audit/reply quartet. |
| `9_shadertoy2/` | Surface-attached refactor | phase2/phase3 debug ladder | `surface_attached_shadertoy_refactor_plan.md` + `critic/`. |
| `10_refactor/` | Era 9 | Data-driven kernel (G0–G10) | 3 dense, high-quality files. |
| `11_generalization/` | Era 10 | Mesh chart-provider design | 1 decision doc, no code. |
| `12_cornell_rc_audit/` | Era 11 | Volumetric-RC audit vs ShaderToy | 2 `.md` + 2 `.py` generators. |
| `journey.md` | — | Chronological spine | Master index, in effect. |
| `13_renderdoc_auto_rdoc.md` | Era 12 | `--auto-rdoc` capture how-to | 1 focused operational note. |

### Coverage assessment

**Strong.** The tree is chronologically complete and heavily cross-referenced. `journey.md` names the era for every directory, and the audit cites concrete `file:line` references into shader source (`raymarch.frag:431-456`, `radiance_3d.comp:316-327`, `sdf_3d.comp:129`). The critic exchanges are substantive (e.g. `7/critic/01_pt_reference_plan_review.md`), not rubber-stamp. The latest-era docs (`10_refactor/`, `12_cornell_rc_audit/`) are models of rigor — locked golden fixtures, machine-readable gates, "a CPU oracle agreeing with itself is not evidence."

**Structural gaps / inconsistencies:**

1. **No top-level index** — no `doc/README.md`; `journey.md` is the only map (H-2).
2. **Naming drift** — `cluade_plan` typo; `claude_reply`/`cluade_reply`/`reply` reply-dir variants; fragmented critic trees in `3/` (M-1).
3. **Three numbering schemes** — Steps (`4`/`5`), Phases (`3`), Eras (`journey.md`) with no crosswalk (M-3).
4. **Duplicate critic sequence numbers** in `6/claude_plan/critic/` (M-2).
5. **Code/artifacts inside the doc tree** — `12_cornell_rc_audit/*.py`, `2/human.skill`.

---

## 3. Strengths

1. **Unflinching honesty.** Failures are first-class artifacts: `v25_z_mbrc_correction_failure_learnings.md` judges a 31-commit program FAILED, and `journey.md:205` states "killing a line of work is output, not failure." Genuinely rare.
2. **Adversarial review actually practiced.** Nearly every plan has a critic and a reply; `rc_audit_report.md:332-346` documents the process self-correcting when it violated its own "a miss = STOP" discipline.
3. **Line-level, auditable claims.** `rc_audit_report.md`, `10_refactor/`, and `13_renderdoc_auto_rdoc.md` cite `demo3d.cpp:6523-6548`, `main3d.cpp:359-371`, etc. The docs can be verified against source.
4. **Locked, falsifiable contracts.** Named gates (`p95(|ln|) ≤ 0.50`, `dim% ≤ 5%`, `bright% ≤ 5%`, `ratio_mean ∈ [0.95,1.05]`) are pre-committed before code (`rc_audit_report.md:196-198`, `10_refactor/` §10).
5. **Corrections are recorded, not hidden.** Inline "CORRECTED (2026-08-19)" entries preserve the reasoning trail so a future reader can see *why* a conclusion changed.
6. **Reusable learnings are banked.** `v25_z_mbrc_correction_failure_learnings.md` §4–§5 and `journey.md:209-220` distill portable rules (EXR-only verdicts, asymmetric HIGH-only clamps, bake-vs-consume separation).

---

## 4. Findings by Severity

### Critical

**C-1 — The spine records a falsified milestone as an achieved fix, with no inline correction.**
- **Files:** `journey.md:88` vs `12_cornell_rc_audit/rc_audit_report.md:21-27` (echoed at `journey.md:131`).
- **Problem:** `journey.md:88` (Era 7) states as fact that the paired fix landed and "Post-fix CV1 ratio 0.650 → **0.846**", locking the consumer contract `irrad = (4/D²)·Σ(L·cos⁺)`. The later, more rigorous audit proves this contract **"is not in the committed code"** — `raymarch.frag:431-456` still implements the renormalized mean `Σ(L·cos·α)/Σ(cos·α)`, `(4/D²)` "exists only in the unapplied `diff_remote.patch:37544`", and `git log -S "4.0 / float(D * D)"` is empty. Provenance is explicitly **UNCONFIRMED**. The correction is only recorded 43 lines later in Era 11, with no forward-reference or `[SUPERSEDED]` marker at line 88.
- **Why it matters:** This is the *only* pre-pivot result the project ever counted as a win, and it is the load-bearing premise of the v2.0-postfix → MBRC → pivot chain. A reader who stops at Era 7 carries away a false fact. Given the tree's own posture — "trust the contract, not the name" (`journey.md:215`) — this is the deepest integrity gap.
- **Fix:** Add an inline `> [!WARNING] superseded — see rc_audit_report.md §0` at `journey.md:88`, and cross-link both directions. Do not silently edit the historical row.

**C-2 — The spine still asserts the "walls black" diagnosis that its own audit formally corrected.**
- **Files:** `journey.md:138` vs `12_cornell_rc_audit/rc_audit_report.md:407-430`.
- **Problem:** `journey.md:138` (Era 11 "renderdoc before-state, locked") asserts the α-gate's signature is "**walls/box black, floor/ceiling ≈0.9**" and locks an A5 prediction that the fix "turns the ~57%-black walls back on." But `rc_audit_report.md:407` (dated 2026-08-19) records verbatim that "**the 'walls black' reading was wrong — a sampling error**", and `:423-425` concludes mode 0 renders the Cornell box correctly (the 56.9% `<5%` pixels are the background void, not walls). Commit `e76ffbe` ("Correct 'walls black' misdiagnosis; revert A5") fixed the audit but **not** the Era 11 row.
- **Why it matters:** `journey.md` is the tree's spine and "single most important file." A reader following only the spine takes away a *false* diagnosis and a *false* A5 prediction — the opposite of what the authoritative audit concluded.
- **Fix:** Rewrite the Era 11 row to state the bimodal histogram was real but the "walls black" reading was a background-void sampling error, that mode 0 renders correctly, and that A5 was attempted on this false premise and reverted.

### High

**H-1 — `1/` quick-start and summary docs describe a pre-Phase-1 codebase (multiple hard errors).**
- **Files:** `1/BUILD_CHECKLIST.md`, `1/IMPLEMENTATION_SUMMARY.md` (and `1/QUICKSTART.md`, `1/MIGRATION_TO_3D.md`, `1/SHADER_REORGANIZATION.md` by the same drift).
- **Problem:** `BUILD_CHECKLIST.md` asserts **6 cascade levels** (lines 180, 205, 315), shaders **`voxelize.comp` / `sdf_3d.comp` / `inject_radiance.comp`** (111-116, 172-179), a default **128³** volume (168-169), a **GLEW** dependency (24-25, 226-244), and a **raylib** tutorial panel (210), plus a stale repo path `c:\Git-repo-3rd\Radiance_Cascade_repos\…` (34). `IMPLEMENTATION_SUMMARY.md` adds: **C++23** requirement (line 314; the project is C++17 per the task brief and `CLAUDE.md`), `demo3d.cpp` "**1086+ lines**" (line 20/469; actual >6600, per `13_renderdoc_auto_rdoc.md:42` citing `demo3d.cpp:6523`), "**Last Updated: 2025-05-13**" (line 7 — a year before Era 6), a **GLEW** dependency (line 315; the app-shell clash is with *raylib*, per `13_renderdoc_auto_rdoc.md:39-40`), and a reference to a non-existent `README.md` (lines 39, 494). Cascade count is internally inconsistent: "up to 6" (line 61) vs "5 cascades" (line 280) vs the actual **4** (`renderdoc_report.md:6`).
- **Why it matters:** `1/` is the on-ramp. Anyone following it will target the wrong C++ standard, look for shaders that do not exist, and misconfigure the run.
- **Fix:** Banner `1/` as superseded (point to `journey.md` and `12_cornell_rc_audit/`), or delete it. At minimum correct the C++ standard, cascade count, shader list, and dependency list.

**H-2 — No top-level index; six numbered directories have no README.**
- **Files:** absence of `doc/README.md` and of `README.md` in `1/`, `2/`, `4/`, `5/`, `6/`, `7/`.
- **Problem:** The only map from directory number → theme → era is `journey.md`. A reader landing on any single directory cannot orient to the rest of the tree.
- **Fix:** Add a one-page `doc/README.md` with the directory→theme map (the §2 table) and a Step↔Phase↔Era crosswalk, plus a one-paragraph README in each numbered directory.

### Medium

**M-1 — Inconsistent plan/reply naming (including a persistent typo) and fragmented critic trees.**
- **Files:** `3/cluade_plan/` (typo for "claude"), `3/cluade_plan/AI/codex_critic/cluade_reply/`, `4/claude_plan/codex_critic/claude_reply/`, `5/claude_plan/codex_critic/reply/`, `6/claude_plan/critic/reply/`, `7/critic/reply/`, `9_shadertoy2/critic/reply/`.
- **Problem:** The reply directory is named `cluade_reply`, `claude_reply`, or `reply` depending on location; the plan directory is `cluade_plan` in `3/` but `claude_plan` in `4/`–`6/`. `3/` also holds *two* parallel critic trees (`cluade_plan/AI/codex_critic/` with 31 reviews *and* `cluade_plan/codex_critic_phase{123,4,5}/`) plus the separate `codex_plan`/`codex_plan_critic`/`codex_plan_critic_critic` chain. Grep-based navigation breaks on all of these.
- **Fix:** Rename `cluade_plan` → `claude_plan`, unify reply-dir naming to `reply/`, and add a one-line provenance note at `3/`.

**M-2 — Duplicate critic sequence numbers and missing replies break the pairing convention.**
- **Files:** `6/claude_plan/critic/` — `07_…` appears twice, `10_…` twice, `11_…` twice, `15_…` twice (e.g. `15_temporal_alpha_stability_impl_review.md` and `15_visibility_phase3_impl_rev2_review.md`). `7/critic/` — reviews `02_pt_reference_impl_review.md` and `04_multi_bounce_temporal_impl_review.md` have **no reply file** (replies 01/03/05 exist in `reply/`, 06/07/08 exist as flat `…_reply.md`).
- **Problem:** The tree advertises 1:1 critic↔reply pairing, but duplicated/gapped numbers make the mapping unreconstructable by filename.
- **Fix:** Renumber with unique contiguous prefixes; add the missing 02/04 replies or mark them "review-only."

**M-3 — Three overlapping numbering schemes with no translation table.**
- **Files:** `4/`/`5/` ("Steps 0–12"), `3/` ("Phases 6–14"), `journey.md` ("Eras 0–12").
- **Problem:** "Step 8" (GPU SDF, `5/`), "Phase 8" (GI banding, `3/`), and "Era 2" (`journey.md`) all refer to different bodies of work, and nothing maps them.
- **Fix:** Add a Step↔Phase↔Era crosswalk to the proposed `doc/README.md`.

**M-4 — The audit report spans two capture generations without a canonical frame.**
- **Files:** `12_cornell_rc_audit/rc_audit_report.md:236-270` (frame 420) vs `:390-405` (§7.5 "before state", frame 351).
- **Problem:** §6/§6.1 (embedded images `../../tools/captures/rdoc_frame_frame420_*.png`) use frame-420 artifacts, while §7.5 locks a *different* "before state" on frame 351. The embeds also point outside the doc tree (into `tools/captures/`), so they render only if the artifacts are present and not gitignored. The reader cannot tell which capture is authoritative.
- **Fix:** State one canonical capture frame per section; check in the referenced PNGs or replace embeds with artifact paths.

**M-5 — Stale cross-reference paths in the `3/` critic chain.**
- **Files:** `3/codex_plan_critic/README.md:208` (`3d/doc/codex_plan/` → should be `3d/doc/3/codex_plan/`), `3/codex_plan_critic_critic/README.md:3` (`doc/codex_plan_critic` → should be `doc/3/codex_plan_critic`).
- **Problem:** The paths predate the renumbering into `3/` and no longer resolve.
- **Fix:** Correct to relative paths so a directory move cannot strand them.

### Low

**L-1 — Near-duplicate `human.skill` pair.**
- **Files:** `2/human.skill` (13,881 B) and `2/human.skill.md` (13,456 B).
- **Problem:** Two files differing only by extension and ~3% in size, no stated relationship.
- **Fix:** Retain one canonical copy.

**L-2 — Empty file in the phase log.**
- **File:** `2/phase1/AI_Task_error_phase1.md` (0 bytes).
- **Problem:** Filename implies an error log that was never written.
- **Fix:** Delete it or replace with a one-line "no errors recorded" note.

**L-3 — Corrections are inline rather than consolidated.**
- **Files:** `rc_audit_report.md:407-430`, `:332-346`, `:348-364`; `journey.md:131-139`.
- **Problem:** Multiple "CORRECTED (2026-08-19)" / "(correction: …)" blocks interleave with the original text, so the final state of truth must be reconstructed by reading the corrections in order.
- **Fix:** Where a section has been corrected more than once, promote a "Current status" summary to the section top and demote the trail to a collapsible appendix.

---

## 5. Recommendations

1. **Fix C-1 and C-2 first — the spine must not contradict the audit.** Annotate `journey.md:88` with a superseded warning and rewrite the Era 11 "renderdoc before-state" row (`journey.md:138`). These are two small edits that restore the integrity of the one file every reader trusts most.
2. **Add a top-level `doc/README.md`** with the directory→theme map, the Step↔Phase↔Era crosswalk, and a "where to start" pointer (`journey.md` for narrative, `12_cornell_rc_audit/` for current state, `10_refactor/` for architecture). This is the highest-leverage single addition.
3. **De-fang `1/`.** Banner or delete the stale quick-start/summary docs so the on-ramp no longer points at `voxelize.comp`, "6 cascade levels", C++23, and a non-existent README.
4. **Standardize naming and numbering.** Rename `cluade_plan` → `claude_plan`; unify `reply/` naming; renumber the duplicate `6/` critic prefixes; add the missing `7/` replies.
5. **Add "current status" headers** to every v2.x/v3 frontier document (dirs `7` and `12_cornell_rc_audit/`) stating the latest verdict (DEAD / MARGINAL / ACTIVE / REVERTED) so living documents are distinguishable from closed ones without reading to the end.
6. **Re-home artifacts.** One `human.skill`; move the `.py` generators out of the doc tree or document their role; delete the empty `2/phase1/AI_Task_error_phase1.md`; fix the `3/` cross-ref paths.
7. **Keep the discipline; it is the asset.** The plan/impl/critic/reply structure and pre-committed gates are what make this tree trustworthy. Future phases should continue producing them — and, per the tree's own rule, continue recording DEAD/MARGINAL/FALSE verdicts as loudly as wins.

---

## Summary of findings

| Severity | Count | Headline |
|---|---|---|
| Critical | 2 | The spine (`journey.md`) contradicts its own subordinate audit in two places: it records the `(4/D²)` "0.650→0.846" fix as landed (proven not-in-code, UNCONFIRMED), and still asserts the "walls black" diagnosis that was formally corrected as a sampling error. |
| High | 2 | `1/` docs describe a pre-Phase-1 codebase (wrong C++ standard, cascade count, shaders); no top-level index/README. |
| Medium | 5 | Naming/typo + fragmented critic trees; duplicate critic numbers + missing replies; Step/Phase/Era drift; audit spans two capture frames; stale cross-ref paths. |
| Low | 3 | `human.skill` near-duplicate; empty `2/phase1/AI_Task_error_phase1.md`; inline corrections not consolidated. |

**Headline finding:** the tree's spine `journey.md` no longer matches its own most authoritative subordinate (`12_cornell_rc_audit/rc_audit_report.md`) on the two most important open questions — the `(4/D²)` consumer contract is recorded as a landed fix but is provably absent from committed code, and the "walls black" α-gate diagnosis is still asserted after being corrected as a background-void sampling error.
