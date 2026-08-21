# A2A Review #1 — Radiance Cascades 3D Documentation Tree

**Reviewers:** writer (draft) · critic (verification) · lead (integration/sign-off)
**Target:** `D:/GitRepo-My/radiance-cascades-demo/3d/doc`
**Method:** read the files directly — `journey.md` and `13_renderdoc_auto_rdoc.md` in full, plus the index/representative plan/impl/critic/reply documents of every numbered subdirectory. No summaries were relied upon.

---

## 1. Overview

The `3d/doc` tree is the written record of a multi-month effort to build a **C++17 / OpenGL 4.3 radiance-cascades global-illumination demo**, from an initial 2D→3D migration through to a current investigation comparing a *volumetric* radiance-cascade implementation against an in-tree ShaderToy reference. The documentation is organized as a chronological stack of numbered subdirectories (`1`…`7`, then `8_shadertoy`…`12_cornell_rc_audit`), each holding `plan`/`impl`/`critic`/`reply` documents, plus two top-level spines:

- **`journey.md`** — a two-column (`ME` / `YOU`) chronological narrative in thirteen "Eras" (Era 0 foundation → Era 12 RenderDoc tooling). This is the *spine*: every era is a two-column table of human steering vs. Claude execution, with dates and commit-level decisions.
- **`13_renderdoc_auto_rdoc.md`** — a standalone "how the in-process RenderDoc capture flag works" learning note (step-by-step flow, the two-Python split, and the "subtleties that bite").

The tree documents a project whose dominant lesson — stated in its own closing sections — is that **measurement and reference-diffing overturn intuition**: four named lever axes came up empty, the LDR metric saturated a real HDR signal, and a "consumer-side" bug turned out to be bake-side. The documentation is unusually self-aware about its own failures (DEAD / MARGINAL / FAILED verdicts are reported without flinching), and this is both its greatest strength and the source of several findings below.

The tree holds **592 Markdown files** at measurement time (now **593**, since this review document itself lives inside the counted tree — a self-inclusion noted in §4 L4), not the "~589" cited in the session goal — a trivial discrepancy noted in §4 (Low).

---

## 2. Structure & coverage

### 2.1 Directory map and themes

| Dir | Files (top-level) | Theme |
|---|---|---|
| `1/` | 6 | Foundation: build checklist, implementation summary, 2D→3D migration, quickstart, shader reorganization |
| `2/` | 19 (+ nested `phase0/`, `phase1/`, `phase1.5/`) | Phase 0–1.5: analytic SDF, debug views, Cornell box OBJ loading; `error_fix_*` series; `brainstorm_plan`, `refactor_plan` |
| `3/` | 4 dirs (`cluade_plan`, `codex_plan`, `codex_plan_critic`, `codex_plan_critic_critic`) | Phase 2–5 cascade architecture; the **codex critic review loop** (`plan` → `critic` → `critic_critic`) |
| `4/` | 1 dir (`claude_plan`, 15 files) | Sponza OBJ→SDF program, Steps 0–7 (plan/impl pairs) |
| `5/` | 1 dir (`claude_plan`, 16 files) | GPU SDF (JFA) Step 8, load-path Step 9, camera/GI Step 10, GI bake strip Step 11, perf tooling Step 12 |
| `6/` | 1 dir (`claude_plan`, 22 files) + `kilo_plan/` | Visibility / light-leak program (Phases 1–3) |
| `7/` | 51 (+ `critic/`, 08 review/reply pairs) | v3 ShaderToy adoption; the `v3_m0`/`v3_m1_stage*` measurement chain; `v20_shadertoy_diff`, `v25_*_failure_learnings` |
| `8_shadertoy/` | 19 | v4 phases 1–6; `01_audit` + `02_correction` + `03_quickref` + `04_reply` |
| `9_shadertoy2/` | 36 (+ `critic/`) | Surface-attached RC refactor; `phase2a–3e` debug/validation series |
| `10_refactor/` | 3 | The data-driven kernel refactor plan (G0–G10 semantic gates), `phase0_5_learnings`, `semantic_parity_differences` |
| `11_generalization/` | 1 | `generalization_design.md` — Cornell charts → real mesh surfaces |
| `12_cornell_rc_audit/` | 4 | `rc_audit_report.md` (volumetric RC vs ShaderToy audit + A0–A9 gap plan), `renderdoc_report.md`, 2 octahedral-solid-angle scripts |
| top level | — | `journey.md`, `13_renderdoc_auto_rdoc.md`, plus four prior review artifacts |

### 2.2 Coverage: what is documented vs. what is not

**Well covered:** the chronological narrative (journey.md), the volumetric-vs-ShaderToy conceptual and line-level diff (rc_audit_report.md §1–§2), the SDF correctness verdicts (§3), the RC-algorithm top-3 defects (§4), a fully specified gap-closing plan A0–A9 with pre-committed gates (§5), and the GPU capture pipeline (renderdoc_report.md, 13_renderdoc_auto_rdoc.md).

**Gaps / inconsistencies:**

1. **No top-level index or README.** The doc root has no `README.md` or `index.md`; a new reader must either read `journey.md` or guess directory meanings from the `8_shadertoy`/`9_shadertoy2` suffixes. `journey.md` is the only navigational aid, and it does not map eras → directories explicitly.
2. **Inconsistent naming schemes.** Directories `1`–`7` are bare integers; `8`–`12` carry descriptive suffixes (`8_shadertoy`, `9_shadertoy2`, `10_refactor`, `11_generalization`, `12_cornell_rc_audit`). A reader cannot infer the split point without opening them.
3. **Nested plan/critic layouts are non-uniform.** `3/` nests the codex loop as *four* sibling dirs (`cluade_plan`, `codex_plan`, `codex_plan_critic`, `codex_plan_critic_critic`), while `4/`–`6/` nest `claude_plan` (with a `codex_critic` sub-subdir) and `7/`/`9_shadertoy2/` keep `critic/` and `critic/reply/` subdirs. The same plan/impl/critic/reply discipline is expressed three different ways.
4. **The `3/cluade_plan` typo.** `cluade_plan` is an obvious misspelling of `claude_plan` (see §4, Low).
5. **Duplicate/ambiguous file in `2/`.** `2/human.skill` and `2/human.skill.md` both exist (see §4, Low).
6. **Review artifacts pollute the doc root.** `A2A_REVIEW.md`, `A2A_REVIEW.prev.md`, `MONO_REVIEW.md`, and `MONO_REVIEW_1.md` sit at the top level alongside the actual documentation. They are benchmark outputs, not documentation, and are ambiguous with the tree's own `12_cornell_rc_audit` reports (see §4, Low).
7. **The "critic" discipline is uneven.** Directories `7/`, `9_shadertoy2/` have dedicated `critic/` trees; `3/`–`6/` embed `codex_critic`/`critic` subdirs; but many impl documents (e.g. `4/claude_plan/sponza_sdf_step*_impl.md`, `7/v3_m1_stage*_impl.md`) have no visible paired critic at all. The `plan/impl/critic/reply` pairing claimed in the goal is not consistently present.

---

## 3. Strengths

1. **`journey.md` is an excellent spine.** It compresses 13 eras of work into a readable two-column narrative, records the *corrections* (not just the wins) — e.g. "cascade merging is bake-time, not consume-time" (journey.md:27) and the "never symmetric clamps on MC accumulators" rule (journey.md:64) — and closes with a portable "how to vibe-code with AI" set of rules that generalize beyond graphics.
2. **Honest failure reporting.** The project repeatedly writes DEAD / MARGINAL / FAILED verdicts instead of hand-waving: "the 31-commit program judged FAILED" (journey.md:90), "v2.4 (DEAD …), v2.4.b (DEAD …)" (journey.md:89). This is rare in engineering documentation and directly enables the later pivots.
3. **Concrete file:line grounding in the audit reports.** `rc_audit_report.md` cites exact shader lines (`raymarch.frag:431-456`, `radiance_3d.comp:316-327`, `reduction_3d.comp:41`) and even the `git log -S "4.0 / float(D * D)"` provenance check (rc_audit_report.md:25-26). Findings are falsifiable, not vibes.
4. **The critic/reply loop actually works.** `8_shadertoy/04_reply_to_audit.md` correctly refutes `01_audit_v3_status_and_gaps.md`'s stale claims (F1/F2/F4) by pointing at the `v3_m1_stage1_delta36_matrix_impl.md` DEAD verdict the auditor missed — demonstrating that a real reviewer disagreeing with a real document produces higher-quality documentation.
5. **Pre-committed gates and STOP discipline.** `rc_audit_report.md:203-216` specifies exact acceptance statistics (`p95(|ln|) ≤ 0.50`, `ratio_mean ∈ [0.95,1.05]`, `dim% ≤ 5%`, `bright% ≤ 5%`) *before* implementation, and §7.4 (rc_audit_report.md:366-388) enforces "a miss = STOP, not retry."
6. **Tooling transparency.** `13_renderdoc_auto_rdoc.md` documents not just the happy path but the failure modes (the `--exit-frames` < 8s warm-up trap at line 96-98, the Python 2.7 step-2 failure at 99-102, the `TriggerCapture()` +1-frame subtlety at 87-89).

---

## 4. Findings by severity

### Critical

**C1 — The documentation's central claim is contradicted by the code it documents.**
- **File:** `journey.md:88` and `12_cornell_rc_audit/rc_audit_report.md:21-27`.
- **Problem:** `journey.md:88` records as a completed, shipped result that the consumer contract became `irrad = (4/D²)·Σ(L·cos⁺)` with "CV1 ratio 0.650 → 0.846." `rc_audit_report.md:21-27` then establishes — with a `git log -S` provenance check — that this contract is **not in the committed code**: `raymarch.frag:431-456` still implements the pre-fix renormalized mean `Σ(L·cos·α)/Σ(cos·α)`, and `(4/D²)` exists only in the unapplied `diff_remote.patch`. The provenance gap is explicitly labeled **UNCONFIRMED** (fix measured on another branch, or reverted in `dd4f5df`).
- **Fix:** Annotate `journey.md:88` in place to flag the claim as *unverified against HEAD*, and add a dated cross-reference to `rc_audit_report.md` §0. The narrative should not present a reverted/unmerged fix as the current state without a caveat.

**C2 — Atlas `.a` payload: producer and consumer disagree on its semantics.**
- **File:** `12_cornell_rc_audit/rc_audit_report.md:118-133`.
- **Problem:** The bake classifies each bin `{sky→0, surface→0, miss→1}` and, under temporal accumulation, EMA-blends α into a soft visibility value (`radiance_3d.comp:826-840`), while `sampleUpperDirWeighted` (`radiance_3d.comp:316-327`) reads that same `.a` as a **signed hit distance** (`lProbeRayDist < 0` → sky). The sky branch is unreachable and surface bins are gated by a fixed `0 + 0.01`. The active consumer also depends on `.a` (`raymarch.frag:443` does `w = wcos * a.a`), so a naive fix breaks the render path.
- **Fix:** Implement the coordinated payload migration the report itself schedules as milestone **A5** — split distance (`t≥0` / `−1` sky) from transmittance/visibility (`α∈[0,1]`) into distinct channels and update every producer/consumer atomically. The doc is correct to insist this be one atomic change, not a step-wise toggle (see rc_audit_report.md:344-346 on the reverted `ddaa997`).

**C3 — A milestone is marked "IMPLEMENTED" while its own acceptance gate failed.**
- **File:** `12_cornell_rc_audit/rc_audit_report.md:279` vs. `rc_audit_report.md:310-330`.
- **Problem:** §7.1's header and the §7 execution-log row (line 279) mark **A2** as "✅ IMPLEMENTED", but the §7.1 measurement table (lines 312-315) shows the corrected A2 build at `ratio_mean = 0.43`, `dim% = 88.4%`, `bright% = 3.4%` — i.e. **dim% is 18× over the 5% gate**, and §7.1's own conclusion (line 330) states "**A2 does not pass its gate.**" The status symbol and the verdict are contradictory within the same file.
- **Fix:** Change the A2 row/header from "✅ IMPLEMENTED" to a distinct status (e.g. "⚠️ IMPLEMENTED — GATE FAILED (dim 88.4%)") so the execution log does not mislead a reader into thinking the fix landed.

### High

**H1 — Consumer integral is not solid-angle-normalized (no per-bin ΔΩ).**
- **File:** `12_cornell_rc_audit/rc_audit_report.md:135-144` (and §7.1 lines 292-299).
- **Problem:** `raymarch.frag:444-452` computes `irrad = Σ(L·cos⁺·α) / Σ(cos⁺·α)` — a renormalized mean with no per-bin solid angle. §7.1's own LUT measurement shows per-bin ΔΩ is strongly non-uniform (2.73× at D=8, 3.89× at D=16), so any uniform `(4/D²)` or `(1/D²)` weighting is quantitatively wrong.
- **Fix:** Land the per-bin ΔΩ LUT (the `octahedral_solid_angle.h` D8/D16 tables already exist per rc_audit_report.md:302-303) into the consumer as `L_o = (ρ/π)·Σ L_b cos⁺_b ΔΩ_b`, keeping the correct renormalized Lambert mean (the §7.1 correction already identified the raw-irradiance+`1/π` form as a bug).

**H2 — Source file:line references in the docs are unversioned and will rot.**
- **File:** pervasive — e.g. `12_cornell_rc_audit/rc_audit_report.md:23-24, 118-133, 146-151`; `8_shadertoy/01_audit_v3_status_and_gaps.md:44-72`.
- **Problem:** Findings cite `raymarch.frag:431-456`, `radiance_3d.comp:316-327`, `demo3d.cpp:186`, etc. These source files live *outside* the doc tree (`res/shaders/`, `src/`), and the line numbers are not pinned to any commit. The refactor (`10_refactor`, Phase 10) and generalization work have already touched these files, so many line references are already stale or will be within one more change.
- **Fix:** Adopt the discipline already used once in `rc_audit_report.md:8` (record the working-tree `HEAD` at the top of every report), and prefer symbol names over bare line numbers where feasible. At minimum, add a "verified against commit X" header to each finding-bearing document.

**H3 — The auto-analysis half of the capture pipeline is documented as routinely failing.**
- **File:** `13_renderdoc_auto_rdoc.md:22` and `13_renderdoc_auto_rdoc.md:99-102`; corroborated at `12_cornell_rc_audit/renderdoc_report.md:102-104`.
- **Problem:** Step 2 of the auto-analysis (`python analyze_renderdoc.py`) "usually doesn't [succeed]" (line 22) and "fails under Python 2.7 — non-ASCII source, no `# -*- coding -*-` declaration" (lines 99-102). The document describes a two-step pipeline whose *second* step (the Claude API analysis that produces `_pipeline.md`) is effectively broken in the default environment, yet the docs present the pipeline as operational.
- **Fix:** Either add the `# -*- coding: utf-8 -*-` declaration and pin Python 3, or explicitly mark step 2 as "known-broken in this environment" in the outputs table rather than burying it in the subtleties section.

### Medium

**M1 — No top-level index/README; the tree is navigable only through `journey.md`.**
- **File:** `D:/GitRepo-My/radiance-cascades-demo/3d/doc/` (absence of `README.md`/`index.md`).
- **Problem:** 592 files under 14+ directories with no directory map. `journey.md` maps *time* → *eras*, not *eras* → *directories*, so a reader seeking "the Sponza SDF work" cannot tell it is under `4/` + `5/` without reading every era.
- **Fix:** Add a one-page `README.md` mapping each numbered directory → theme → key files, mirroring §2.1 above.

**M2 — Non-uniform plan/impl/critic/reply structure.**
- **File:** `3/` (four sibling dirs), `4/claude_plan/`, `6/kilo_plan/`, `7/critic/`, `9_shadertoy2/critic/`.
- **Problem:** The same review discipline is expressed as sibling dirs in `3/`, as `claude_plan` + `codex_critic` subdirs in `4/`–`6/`, and as top-level `critic/` in `7/` and `9_shadertoy2/`. A contributor cannot predict where a critique lives.
- **Fix:** Standardize on one layout (recommend `critic/` + `critic/reply/` per directory, as in `7/`), and backfill an index note for the older dirs rather than moving 500+ files.

**M3 — The `kilo_plan` vs `claude_plan` split is unexplained.**
- **File:** `6/claude_plan/` and `6/kilo_plan/`.
- **Problem:** `6/` contains both `claude_plan/` (22 files) and `kilo_plan/` (1 file, `sponza_gi_quality_diagnosis.md`) with no document explaining what "kilo" denotes (a different model? a specific tool?). This is opaque to any reader.
- **Fix:** Add a one-line note in `6/` (or the proposed README) stating what `kilo_plan` is and why it is separate from `claude_plan`.

### Low

**L1 — Directory-name typo `cluade_plan`.**
- **File:** `3/cluade_plan/`.
- **Problem:** Misspelling of "claude". Harmless but inconsistent with `4/claude_plan/`, `5/claude_plan/`, `6/claude_plan/`.
- **Fix:** `git mv 3/cluade_plan 3/claude_plan` (and update the two cross-references if any exist).

**L2 — Duplicate `human.skill` files.**
- **File:** `2/human.skill` and `2/human.skill.md`.
- **Problem:** Two files with near-identical names (one extension-less, one `.md`) in the same directory; likely an accidental duplicate.
- **Fix:** Diff and delete the redundant one, or keep only `human.skill.md`.

**L3 — Prior review artifacts pollute the documentation root.**
- **File:** `A2A_REVIEW.md`, `A2A_REVIEW.prev.md`, `MONO_REVIEW.md`, `MONO_REVIEW_1.md` at `3d/doc/`.
- **Problem:** These are benchmark/comparison outputs, not documentation, yet they sit beside `journey.md` and the numbered directories. They are easily confused with the tree's own audit reports (e.g. `12_cornell_rc_audit/rc_audit_report.md`).
- **Fix:** Move them to a `review_artifacts/` subdirectory (or out of `doc/` entirely) so the doc tree contains only first-class documentation.

**L4 — File-count discrepancy.**
- **File:** session goal ("~589 markdown files") vs. measured **592** (`find . -name "*.md"`), now **593** once this review is written into the tree.
- **Problem:** The goal's stated count is slightly off from reality; minor, but the goal itself is a "source" future reviewers may cite. The count is also a moving target — the review artifacts (this file included) live inside the counted tree and inflate it.
- **Fix:** No action needed on the tree; note the corrected count in any meta-documentation, and count *source* docs separately from review/benchmark artifacts.

**L5 — Early documents predate and contradict the measurement-first posture.**
- **File:** `8_shadertoy/01_audit_v3_status_and_gaps.md` (refuted as stale by `8_shadertoy/04_reply_to_audit.md:11-16`).
- **Problem:** `01_audit`'s headline finding F1 ("flags implemented but never A/B tested") is demonstrably wrong — the `v3_m1_stage1_delta36_matrix_impl.md` matrix verdict (`DEAD`) was on disk a day earlier. Leaving a refuted audit un-annotated invites a future reader to act on false premises.
- **Fix:** Add a "superseded by `04_reply_to_audit.md`" banner at the top of `01_audit` (and any other refuted document), the same way `rc_audit_report.md` itself uses inline "CORRECTED" blocks (e.g. rc_audit_report.md:407).

---

## 5. Recommendations

1. **Add a root `README.md`** that maps directory → theme → key files (directly resolves M1, M2, M3).
2. **Adopt a "superseded/corrected" banner convention** for any document that a later reply refutes — the tree already does this inline in `rc_audit_report.md` (the "CORRECTED" block at line 407); extend it to the `8_shadertoy` audit/reply pairs (L5).
3. **Reconcile the doc-vs-code provenance gap (C1) as a priority.** Until `journey.md:88` carries a caveat and `rc_audit_report.md`'s A0–A9 plan is executed, the documentation's most important narrative claim is unverifiable.
4. **Pin every finding-bearing report to a commit.** Add a `HEAD <sha>` line (as `rc_audit_report.md:8` already does) to `renderdoc_report.md`, the `8_shadertoy` audit, and all `7/` stage reports, and prefer symbol names over line numbers (H2).
5. **Fix the A2 status/verdict contradiction (C3)** and re-run the gate discipline: a milestone should never display a green check while its own gate table shows failure.
6. **Standardize the critic/reply layout** going forward (recommend the `7/critic/` + `critic/reply/` shape) and stop creating new sibling-dir variants (M2).
7. **Repair the auto-analysis tooling** (`analyze_renderdoc.py` encoding, Python 3 pin) or downgrade step 2 to "known-broken" in the outputs table (H3).
8. **Minor hygiene:** rename `3/cluade_plan` (L1), de-duplicate `2/human.skill*` (L2), and move the four review artifacts out of the doc root (L3).

**Overall assessment:** This is a high-signal, unusually honest engineering record whose main liability is *internal consistency* — a shipped claim contradicted by the code (C1), a payload semantic split across producer/consumer (C2), and a green status over a failed gate (C3). The fixes are documentation-side and mechanical for most findings, with the substantive engineering work (the A0–A9 gap-closing plan) already well specified in `rc_audit_report.md`. The tree is close to excellent; it needs the provenance gap closed and the stale/contradictory entries annotated before it can be cited as authoritative.
