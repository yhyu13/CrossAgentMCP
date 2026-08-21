# Documentation Tree Review — 3D Radiance Cascades

**Reviewer:** senior graphics-engineer documentation reviewer (single agent)
**Date:** 2026-08-21
**Scope:** `D:/GitRepo-My/radiance-cascades-demo/3d/doc` (~591 markdown files, 13 numbered subdirectories + 2 spine files)
**Method:** read `journey.md` and `13_renderdoc_auto_rdoc.md` in full; enumerated every subdirectory; read a representative sample of plan/impl/critic/reply documents across all eras. No summaries were trusted; every file reference below was read or `find`/`grep`-verified against the working tree.

---

## 1. Overview

The tree documents the construction of a C++17 / OpenGL 4.3 radiance-cascades global-illumination demo, from a 2D→3D migration (Era 0) through the current Cornell-box audit against a ShaderToy reference (Era 11–12, 2026-08). It is organized as a **chronological spine plus numbered era-buckets**, where each era is a directory of `plan` / `impl` / `critic` / `reply` documents.

The spine is `journey.md` — a two-column "ME / YOU" table (human decisions vs. what Claude built/discovered/got wrong) that groups work into 12 named Eras and closes with a set of portable "vibe coding" lessons. `13_renderdoc_auto_rdoc.md` is a standalone operational how-to for the project's headless in-process RenderDoc capture flag.

The numbered directories (1..7, then 8–12 with name suffixes) each hold one era's artifacts:
- **1** — build/quickstart/setup (6 files)
- **2** — Phase 0–1.5: SDF, Cornell OBJ, error logs, and the `human.skill` interaction-pattern spec (19 files + `phase0/1/1.5`)
- **3** — Phase 2–5 cascade architecture, plan/impl/critic chains + a "class" teaching set (4 subdirs, ~65 files)
- **4** — Sponza SDF Steps 0–7 (15 files + critic)
- **5** — GPU SDF + performance Steps 8–12 (16 files + critic)
- **6** — visibility / leak program (25 files + critic)
- **7** — hybrid RC, PT reference, v2.x/v3.x measurement chain (51 files + critic/reply)
- **8_shadertoy** — v4 ShaderToy adoption scope + phases (19 files)
- **9_shadertoy2** — surface-attached refactor phases 2/3 + critic/reply (36 files)
- **10_refactor** — the data-driven-kernel refactor plan (3 files)
- **11_generalization** — mesh-surface generalization design (1 file)
- **12_cornell_rc_audit** — the Cornell RC audit + RenderDoc report + solid-angle scripts (4 files)

The tree is unusually good at capturing *process* (pre-committed verdict gates, honest DEAD/FAILED verdicts, critic chains that actually revise plans), not just results.

---

## 2. Structure & coverage

**Coverage is deep and largely complete** along the eras it documents. Each era has a coherent plan→impl→critic→reply loop, and the later eras (7–12) are exceptional in their rigor: critics cite file:line, plans carry "per critic-01 W6" annotations proving revisions were applied, and failed experiments (v2.2 KILLED, v2.4 DEAD, the 31-commit MBRC program FAILED) are reported rather than buried.

**The `class/` subdirectories are the one structural surprise.** Both `3/cluade_plan/class/` (19 files) and `3/codex_plan/class/` (13 files) are parallel "course" walkthroughs (jargon index, scene/pipeline, phase-by-phase). They cover overlapping ground under different filenames and are not cross-linked.

**Gaps and inconsistencies:**

1. **No entry point other than `journey.md`.** There is no top-level `README.md` or `index.md`. A newcomer must read the 220-line spine to discover the directory scheme.
2. **Numbering breaks at 13.** Directories are `1..12` (8–12 with name suffixes), but `13_renderdoc_auto_rdoc.md` is a top-level *file*, not a directory. The "numbered subdirectory" convention is not consistently applied.
3. **`phase2e` in `9_shadertoy2` has a plan but no impl** (`phase2e_plan_cascade_hierarchy.md` present, no `phase2e_impl`). This confirms — rather than contradicts — the refactor plan's own admission (`10_refactor/3d_radiance_cascades_refactor_plan.md` §3.2: "No Phase 2E implementation report proves the hierarchy"). It is a real, acknowledged hole in the surface-RC line.
4. **Naming drift in `9_shadertoy2`:** `phase2_impl_ring_packed_index_debug.md` is referred to as "phase2a" by its own critic (`02_critique_phase2a_ring_packed_index_debug.md`).
5. **Era 7 in `journey.md` is not reconciled with Era 11.** The spine states a headline result as settled (see Critical finding below) without a forward-pointer to the later audit that reverses it.

Duplication is modest but present (see High finding H3 and Medium finding M3).

---

## 3. Strengths

1. **`journey.md` is a genuinely excellent spine.** The two-column ME/YOU format cleanly separates human intent from AI execution, dates every era, and — most unusually — *leads with failures*. The "recurring lesson" section correctly identifies the project's actual through-line: intuition-driven fixes repeatedly overturned by measurement or reference diffs.

2. **The critic discipline is real, not performative.** `7/critic/01_pt_reference_plan_review.md` is a substantive review (2 HIGH + 3 MEDIUM + 4 LOW) with concrete line-level fixes; the plan it reviews (`7/pt_reference_plan.md` rev 2) visibly applies them, annotating each change "per critic-01 W6" and even self-correcting its own TL;DR ("overhead is ~25-40%, not 0.5% as I initially claimed").

3. **Measurement-first ethos is documented end-to-end.** The v2.0-pre "measurement before features" contract, the HDR-EXR honest metric that exposed the LDR colormap saturation, and the Σ+/Σ− cross-check rule are all captured as *durable rules*, not one-off notes.

4. **The Cornell audit (`12_cornell_rc_audit/rc_audit_report.md`) is exemplary.** It pins claims, freezes invariants (`L_o = (ρ/π)·Σ L cos⁺ ΔΩ`), pre-commits all four acceptance statistics, and — critically — **corrects its own false premise** (the "walls black" misdiagnosis is explicitly retracted in §7.5 after re-sampling at actual wall positions).

5. **Precise code anchoring.** Later-era documents cite `file:line` throughout (`raymarch.frag:431-456`, `radiance_3d.comp:316-327`, `reduction_3d.comp:41`), making findings auditable against the source.

6. **`13_renderdoc_auto_rdoc.md` is a clear, correct operational write-up**, including the non-obvious two-Python split (qrenderdoc's embedded 3.6 vs system `python`) and the `--exit-frames` must-outlast-warmup trap.

---

## 4. Findings by severity

### Critical

**C1 — The spine's central claimed win contradicts the audit's headline finding, with no reconciliation in Era 7.**

- **File:** `journey.md:88` vs `12_cornell_rc_audit/rc_audit_report.md:21-27`.
- **Problem:** `journey.md` Era 7 states, as settled fact, that the consumer contract "became `irrad = (4/D²)·Σ(L·cos⁺)`" and that "Post-fix CV1 ratio 0.650 → **0.846**." The Cornell audit proves the `(4/D²)` factor is **not in the committed code** — `raymarch.frag:431-456` still implements the pre-fix renormalized mean `Σ(L·cos·α)/Σ(cos·α)`, and `(4/D²)` exists only in the unapplied `diff_remote.patch:37544` (provenance: fix measured on another branch or reverted in `dd4f5df`, unconfirmed). The retraction appears only in Era 11 (line 131). A reader who stops at Era 7 takes away a false headline result.
- **Suggested fix:** Add a one-line caveat to `journey.md:88` (e.g. "⚠️ later audit [12_cornell_rc_audit] found this fix absent from committed code") or fold the Era 11 retraction forward so the spine is self-consistent at any read point.

### High

**H1 — Stale absolute `file://` links to a different checkout (~20+ files).**

- **File:** `2/human.skill.md:395-405` (representative); also `1/BUILD_CHECKLIST.md`, `2/AI_Task.md`, `2/error_fix_*.md`, and most of `2/phase*`.
- **Problem:** Links point to `c:\Git-repo-3rd\Radiance_Cascade_repos\radiance-cascades-demo\3d\doc\...`, a path that does not exist — the repo lives at `D:\GitRepo-My\...`. Every such link is broken.
- **Suggested fix:** Replace with repo-relative links (`./2/...`) or bare filenames.

**H2 — Directory typo `3/cluade_plan` (should be `claude_plan`).**

- **File:** directory `3/cluade_plan/`; the misspelling is also baked into ~10+ files' own cross-references (e.g. `3/cluade_plan/AI/codex_critic/01_phase6a_..._review.md`).
- **Problem:** Breaks grep-navigation and looks like a data-quality error in an otherwise disciplined tree.
- **Suggested fix:** `git mv 3/cluade_plan 3/claude_plan` and update the internal references; or, if the rename is risky, add a `README` noting the historical spelling.

**H3 — Diverged duplicate files `2/human.skill` vs `2/human.skill.md`.**

- **File:** `2/human.skill` (13,881 B) and `2/human.skill.md` (13,456 B).
- **Problem:** Two near-identical files with different sizes (content has drifted). No indication which is canonical.
- **Suggested fix:** Keep one, delete the other (or reconcile and cross-reference).

### Medium

**M1 — No top-level index/README.**

- **File:** `doc/` root (verified: no `README*` / `index*`).
- **Problem:** The only entry point is `journey.md`; the 13-subdirectory scheme and the named-vs-numbered split are undiscoverable without reading the spine.
- **Suggested fix:** Add a short `doc/README.md` mapping each numbered directory to its era/theme, mirroring the §1 table here.

**M2 — Numbering convention breaks at 13.**

- **File:** `13_renderdoc_auto_rdoc.md` (top-level file) vs `1..12` (directories).
- **Problem:** "13" is a file, not a directory; readers expecting a numbered folder find a lone doc.
- **Suggested fix:** Either move it into `12_cornell_rc_audit/` (it documents the audit's tooling) or rename to a non-numbered name.

**M3 — Two parallel `class/` teaching sets with no cross-link.**

- **File:** `3/cluade_plan/class/` (19 files) and `3/codex_plan/class/` (13 files).
- **Problem:** Both contain a jargon index and a phase-by-phase walkthrough under different filenames, covering overlapping material; drift risk and duplicated maintenance.
- **Suggested fix:** Declare one canonical (the `cluade_plan` set is newer/larger), cross-link from the other, or merge.

**M4 — `phase2e` plan with no impl, and `phase2a` naming drift.**

- **File:** `9_shadertoy2/phase2e_plan_cascade_hierarchy.md` (no `phase2e_impl`); `9_shadertoy2/phase2_impl_ring_packed_index_debug.md` named "phase2a" by `9_shadertoy2/critic/02_critique_phase2a_ring_packed_index_debug.md`.
- **Problem:** Confirms the surface-RC hierarchy was never implemented (also admitted in `10_refactor/...refactor_plan.md` §3.2). The gap is real and should be flagged explicitly at the directory level, not only buried in a critic's title.
- **Suggested fix:** Add a `9_shadertoy2/README.md` or a status line noting phase2e was planned but not implemented.

**M5 — Process/meta artifact misplaced and stale.**

- **File:** `2/human.skill.md` (also `2/human.skill`).
- **Problem:** An AI interaction-pattern spec (not graphics documentation) sits in the middle of the graphics tree, dated 2026-04-18 with "Phase 0 COMPLETED" — stale by ~4 months relative to Era 12.
- **Suggested fix:** Move to a `process/` or `meta/` location and either archive or update its project-state section.

### Low

**L1 — Incorrect cross-reference path in `codex_plan_critic` README.**

- **File:** `3/codex_plan_critic/README.md:207-210`.
- **Problem:** References `3d/doc/codex_plan/`, which should be `3d/doc/3/codex_plan/`.
- **Suggested fix:** Correct the path.

**L2 — Style drift between early and late eras.**

- **File:** `2/phase1.5/README.md` (emoji-heavy, "Development Team" voice, ~280-line index) vs the terse line-cited style of `7/`–`12/`.
- **Problem:** Cosmetic, but the early docs read like a different project and inflate their own "length/reading-time" claims (`PHASE1_CONSOLIDATION.md` "~800 lines").
- **Suggested fix:** Optional; note the convention shift in the new root README.

**L3 — Review artifacts committed into the reviewed tree root.**

- **File:** `A2A_REVIEW.md`, `A2A_REVIEW.prev.md`, `MONO_REVIEW.md` (and this `MONO_REVIEW_1.md`).
- **Problem:** Meta-reviews of the documentation live at the same root as the source docs, with no separation or note.
- **Suggested fix:** Move reviews to a `doc/_reviews/` (or `meta/`) directory so the "source of truth" tree stays clean.

---

## 5. Recommendations

1. **Reconcile the spine with the audit (Critical C1) first.** The single highest-value edit is a caveat on `journey.md:88` pointing to `rc_audit_report.md`'s provenance finding. The tree's credibility rests on the spine not overstating its own results.
2. **Add a root `doc/README.md`** (fixes M1, and gives M3/M4/L2 a home). A 30-line era→directory map would materially lower the cost of entry to a 591-file tree.
3. **Run a one-time hygiene pass** over the mechanical issues: fix stale `c:\Git-repo-3rd\...` links (H1), rename `cluade_plan` (H2), collapse the `human.skill` duplicate (H3), move `13_*` into a directory (M2), and relocate `human.skill`/reviews out of the source root (M5/L3).
4. **Declare a canonical teaching set** between the two `class/` directories (M3) and add a status note for the un-implemented `phase2e` (M4) so future readers do not mistake the surface-RC hierarchy for shipped.
5. **Preserve what works.** The critic discipline, pre-committed-gate methodology, and honest-failure reporting are the tree's crown jewels — do not "clean up" the DEAD/FAILED/MARGINAL verdicts or the self-corrections (the "walls black" retraction in `rc_audit_report.md` §7.5 is a feature, not a flaw).

---

## Self-critique note

During drafting I initially flagged a suspected broken cross-reference: `8_shadertoy/v4_shadertoy_adoption_scope.md` and `7/critic/06_*` both point to `doc/7/v3_shadertoy_adoption_scope.md`, which was absent from my first `ls 7`. A `find` confirmed the file **does exist** (`7/v3_shadertoy_adoption_scope.md`), so that finding was dropped. Every other reference above was re-verified against the working tree (`find`/`grep`/direct read) before being committed to this review.
