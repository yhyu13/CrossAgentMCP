# A2A Review — 3D Radiance Cascades Documentation Tree

**Reviewed by:** writer / critic / lead (three-role A2A session)
**Target:** `D:/GitRepo-My/radiance-cascades-demo/3d/doc/`
**Scope:** 591 `.md` files (588 excluding the three root review documents) + 3 non-markdown artifacts (2 `.py`, 1 `.skill`), across 12 numbered subdirectories + 2 root documents
**Method:** direct read of the spine (`journey.md`), the RenderDoc note, and a representative sample of each subdirectory.

---

## 1. Overview

The tree documents the construction of a C++17 / OpenGL 4.3 radiance-cascades global-illumination demo. It is an unusually complete *process* archive: not just design documents, but the chronological record of a human steering an AI through ~12 "eras" of work — from a 2D→3D migration, through cascade architecture, a ShaderToy-reference pivot, a data-driven-kernel refactor, and a final Cornell-box audit that is still open.

Organization is **layered by era, then by role**:

- **Root spine** — `journey.md` (a two-column "ME / YOU" chronology, the single most important file) and `13_renderdoc_auto_rdoc.md` (a standalone note on the `--auto-rdoc` capture flag).
- **Numbered subdirectories** — `1`–`7`, then `8_shadertoy`, `9_shadertoy2`, `10_refactor`, `11_generalization`, `12_cornell_rc_audit`. Each holds the plan/impl/critic/reply documents for one phase of work.
- **The `plan/impl/critic/reply` motif** — most directories carry paired `*_plan.md` and `*_impl.md` files, with a `critic/` subdirectory (or a `codex_critic` subdirectory) holding numbered review→reply exchanges.

The dominant theme across the tree is a deliberate **measurement-first, reference-diff-first working discipline**: the project repeatedly records itself killing work (v2.4 "DEAD", a 31-commit correction program "FAILED", four named lever axes "eliminated") and encodes corrections as durable "do-not-repeat" rules. The documentation is as much a treatise on AI-assisted development as a graphics log — `journey.md:187-220` explicitly reframes the whole repo as "one long A/B test" of "vibe coding."

---

## 2. Structure & coverage

### Directory map

| Dir | Theme (from `journey.md` era) | Contents (sample) |
|---|---|---|
| `1/` | Era 0 — 2D→3D migration, Phase 0–1.5 | `IMPLEMENTATION_SUMMARY.md`, `MIGRATION_TO_3D.md`, `QUICKSTART.md`, `BUILD_CHECKLIST.md`, `SHADER_REORGANIZATION.md` |
| `2/` | Phase 0–1.5 execution + error-fix log | `AI_Task*.md`, `error_fix_*.md`, `brainstorm_plan.md`, `human.skill`(+`.md`), `phase0/`, `phase1/`, `phase1.5/` |
| `3/` | Plan + critic + critic-of-critic chain | `cluade_plan/`, `codex_plan/`, `codex_plan_critic/`, `codex_plan_critic_critic/` |
| `4/` | Era 2 — Sponza SDF Steps 0–7 | `claude_plan/` (per-step `*_plan.md`/`*_impl.md` + `codex_critic/`) |
| `5/` | Era 2 — GPU SDF + perf (Steps 8–12) | `claude_plan/` (`gpu_sdf_step8`, `load_path_step9`, `gi_bake_strip_heatmap_step11`, `perf_tooling_step12`) |
| `6/` | Era 4 — visibility / leak fix | `claude_plan/` (visibility Phases 1–3), `kilo_plan/sponza_gi_quality_diagnosis.md` |
| `7/` | Era 5–8 — hybrid RC, PT reference, v3 M0/M1 stages | 51 files: `pt_reference_*.md`, `multi_bounce_temporal_*.md`, `v3_m0_*`, `v3_m1_stage*_plan/impl` pairs, `critic/` |
| `8_shadertoy/` | Era 8 — v4 ShaderToy adoption | `v4_phase{1..6}_{plan,impl}.md`, `01_audit_v3_status_and_gaps.md`, `v4_closeout_report.md` |
| `9_shadertoy2/` | Surface-attached ShaderToy refactor | `surface_attached_shadertoy_refactor_plan.md`, `phase2*`/`phase3*` plan/impl pairs, `critic/` |
| `10_refactor/` | Era 9 — data-driven kernel refactor | `3d_radiance_cascades_refactor_plan.md`, `phase0_5_learnings.md`, `semantic_parity_differences.md` |
| `11_generalization/` | Era 10 — mesh-surface generalization | `generalization_design.md` |
| `12_cornell_rc_audit/` | Era 11 — Cornell-box volumetric-RC audit | `rc_audit_report.md`, `renderdoc_report.md`, `octahedral_solid_angle{,_gen}.py` |

### Coverage assessment

**Strong:** the tree is chronologically complete and internally cross-referenced. `journey.md` names the exact era each directory maps to, and the audit (`12_cornell_rc_audit/rc_audit_report.md`) cites concrete `file:line` references into the shader sources (`raymarch.frag:431-456`, `radiance_3d.comp:316-327`, `sdf_3d.comp:129`). The critic exchanges (`7/critic/`, `9_shadertoy2/critic/`, the `codex_critic*` chains) are substantive — e.g. `7/critic/01_pt_reference_plan_review.md` delivers nine findings (W1–W9) with concrete fixes, not rubber-stamp approval.

**Gaps / inconsistencies (structural):**

1. **No top-level index.** The root holds `journey.md`, `13_renderdoc_auto_rdoc.md`, and 12 directories, but there is no `README.md`/`index.md` that maps the numbered directories to their themes. `journey.md` is the de-facto index, but it does not enumerate the subdirectory contents.
2. **Inconsistent directory naming.** `1`–`7` are bare numbers; `8`–`12` carry suffixes (`8_shadertoy`, `10_refactor`, `12_cornell_rc_audit`). A reader cannot infer a directory's theme from a bare number without reading `journey.md` first.
3. **"13" is a file, not a directory.** `13_renderdoc_auto_rdoc.md` is a root-level file, but its leading `13` visually reads as a 13th numbered directory. There are 12 directories; the scope statement already enumerates them correctly, so this is only a naming-consistency nit.
4. **Inconsistent plan/impl/critic packaging.** The plan/impl/critic/reply motif is expressed three different ways: nested critic chains in `3/` (`codex_plan` → `codex_plan_critic` → `codex_plan_critic_critic`), a `codex_critic/` subdirectory in `4/`–`6/`, and flat numbered `*_plan.md`/`*_impl.md` pairs plus a `critic/` subdirectory in `7/` and `9/`. Each is coherent locally but there is no stated convention.
5. **Code lives inside the doc tree.** `12_cornell_rc_audit/` contains two Python scripts (`octahedral_solid_angle.py`, `octahedral_solid_angle_gen.py`) and `2/` contains a `human.skill` file. These are artifacts, not documentation — their presence blurs the "doc tree" boundary.
6. **File-count drift and self-review pollution.** The tree now holds **591 `.md` files** (588 excluding the three root review documents `A2A_REVIEW.md`, `A2A_REVIEW.prev.md`, `MONO_REVIEW.md`) plus 3 non-markdown artifacts (2 `.py` in `12_cornell_rc_audit/`, 1 `.skill` in `2/`). The scope statement's "~589 markdown files" is now slightly stale (actual 591, or 588 excluding the review docs), and the count moves as review documents accumulate — the review cannot cleanly count itself.

---

## 3. Strengths

1. **Honest, verdict-driven record.** The tree's defining trait is its refusal to paper over failure. `journey.md:89-90` records v2.2 "KILLED at Step 0", v2.4/v2.4.b "DEAD", and a 31-commit program "FAILED" — with the *reason* in each case. This is rare and genuinely valuable as an engineering artifact.

2. **Corrections are encoded as durable rules.** Rather than a bare fix log, the tree extracts reusable invariants: "never symmetric clamps on MC accumulators" (`journey.md:64`), "cascade merging is bake-time, not consume-time" (`journey.md:27`), "the chart is the radiance atom" (`11_generalization/generalization_design.md`). These are portable to any AI-coding project.

3. **Concrete, line-level claims.** The audit reports do not assert "the consumer is wrong" — they cite `raymarch.frag:431-456`, `radiance_3d.comp:316-327`, `radiance_3d.comp:826-840`, and distinguish the confirmed-divergent from the confirmed-aligned (e.g. `rc_audit_report.md:67-69`). This is the correct density for a review target.

4. **The critic exchanges are real and adversarial.** `7/critic/01_pt_reference_plan_review.md` catches a genuine NEE/MIS terminology error (W1) and a "ground-truth" framing flaw (W2); `rc_audit_report.md:366-388` documents the process *self-correcting* when it discovers it violated its own "miss = STOP" discipline. The critique is not ceremonial.

5. **Measurement-first discipline is the through-line.** The recurring lesson (`journey.md:173-183`) — diff against the reference first, measure only to validate, cross-check visual conclusions against absolute numbers — is demonstrated repeatedly, not merely asserted.

6. **A working capture pipeline is documented to the line.** `13_renderdoc_auto_rdoc.md` explains the `--auto-rdoc` flow with specific source locations (`main3d.cpp:359-371`, `demo3d.cpp:6523-6548`) and catalogs the non-obvious failure modes (the 8s warm-up vs `--exit-frames`, the Python 2.7/3.6 two-interpreter split). This is genuinely useful operational documentation.

---

## 4. Findings by severity

### Critical

**C1 — The flagship "shipped fix" is not in the committed code (provenance gap, UNCONFIRMED).**
The tree's own headline finding, recorded in two places, is that the consumer contract the project believes it shipped — `irrad = (4/D²)·Σ(L·cos⁺)` — is absent from the code:
- `journey.md:88` records "CV1 ratio 0.650 → 0.846" as a derived-and-landed fix.
- `12_cornell_rc_audit/rc_audit_report.md:22-27` states `raymarch.frag:431-456` "still implements the pre-fix renormalized mean `Σ(L·cos·α)/Σ(cos·α)`", that the `(4/D²)` factor "exists only in the unapplied `diff_remote.patch:37544`", and that `git log -S "4.0 / float(D * D)"` is empty.
- The provenance is explicitly **UNCONFIRMED**: "the fix was measured on another branch/remote and never merged, or was reverted in `dd4f5df`."

This is the single most important open defect in the entire project, and it is *documented but not resolved*. Every downstream parity claim (the CV1 gates, the A2/A5 milestones) is premised on a code state that may never have existed on `HEAD`.
**Fix:** resolve the provenance question first — check whether `dd4f5df` reverted the fix, or whether the measurement branch still exists — and record the answer in the audit report before any further A-milestone work. The doc currently leaves the reader with two mutually exclusive histories.

### High

**H1 — Stale root summary claims auto-update but is frozen at the earliest phase.**
`1/IMPLEMENTATION_SUMMARY.md:7` says "Last Updated: 2025-05-13", and `1/IMPLEMENTATION_SUMMARY.md:540` closes with "*This document is automatically updated as implementation progresses.*" — but the file describes only Phase 1 "foundation" work (70%-stub `demo3d.cpp`) and has not tracked any of the subsequent eras. The auto-update claim is false in practice.
**Fix:** either delete the auto-update sentence, or add a "superseded by `journey.md`" banner pointing to the authoritative record.

**H2 — Cascade configuration contradicts across the tree (early vs late).**
`1/IMPLEMENTATION_SUMMARY.md:256-262` specifies **five** cascades (`Cascade 0: 32³, 1: 64³, 2: 128³, 3: 64³, 4: 32³`, `rays = 4` each), while `12_cornell_rc_audit/renderdoc_report.md:6` specifies **four** cascades (`C0 32³/D8, C1 16³/D16, C2 8³/D16, C3 4³/D16`). The early document is not marked superseded, so a reader can derive a wrong mental model of the shipping architecture.
**Fix:** mark `1/` as historical/Era-0 snapshot in a header note, and route readers to `12_cornell_rc_audit/` for the current cascade topology.

**H3 — Misspelled and inconsistent plan-directory names obscure provenance.**
`3/cluade_plan/` is a typo for "claude_plan" (compare `4/claude_plan`, `5/claude_plan`, `6/claude_plan`). Within it, the subdirectories `AI/` and `class/` are cryptic, lowercase names that don't self-describe. Across the tree the plan directories are named `cluade_plan`, `claude_plan`, `codex_plan`, and `kilo_plan` with no legend explaining which agent/role produced each.
**Fix:** rename `cluade_plan` → `claude_plan`, and add a one-line provenance note (e.g. "claude_plan = Claude-authored, codex_plan = Codex-authored, kilo_plan = …") at `3/` level.

**H4 — Near-duplicate files.**
`2/human.skill` (13,881 bytes) and `2/human.skill.md` (13,456 bytes) are near-identical skill definitions; `1/` holds both `IMPLEMENTATION_SUMMARY.md` and `IMPLEMENTATION_SUMMARY_QUICKSTART.md`, and both `QUICKSTART.md` and `IMPLEMENTATION_SUMMARY_QUICKSTART.md`. Duplication with no stated relationship invites divergence.
**Fix:** retain one canonical copy of each and either delete or cross-reference the other.

**H5 — Two disconnected RenderDoc narratives at root, no cross-link.**
`13_renderdoc_auto_rdoc.md` documents the *working* in-app `--auto-rdoc` pipeline, while `journey.md:144-169` (Era 12, dated 2026-08-20) argues the `renderdoc-gpu-debug` skill is a "documented superset, not yet a working replacement" because `rdc-cli` is not installed. Neither file links to the other, so a reader can't tell these are the same tooling thread reaching opposite conclusions.
**Fix:** add a cross-reference from `13_renderdoc_auto_rdoc.md` to `journey.md` Era 12 (and back), and state explicitly which of the two is the operational truth today.

### Medium

**M1 — Stale path references in the critic chain.**
`3/codex_plan_critic/README.md:207-209` points readers to "`3d/doc/codex_plan/`", but the actual path is `3d/doc/3/codex_plan/` — the `codex_plan` directory was moved under `3/` when the tree was renumbered, and this reference was never updated. (`3/codex_plan_critic/README.md`'s sibling reference to "`3d/doc/2/`" is actually correct; only the `codex_plan` path is stale.) `3/codex_plan_critic_critic/README.md:3` likewise references "the critique in `doc/codex_plan_critic`" when the real path is `doc/3/codex_plan_critic`. These are pre-renumbering paths that were never updated.
**Fix:** correct the paths, or better, make them relative links so a directory move can't strand them.

**M2 — Inconsistent date coverage in `journey.md`.**
Eras 0–5 carry no dates; Eras 6–12 carry explicit `YYYY-MM-DD` ranges; Era 11 is dated "2026-08-17, current" while Era 12 is dated "2026-08-20" and `journey.md`'s own file mtime is 2026-08-20. The chronology is correct but the early eras lose the "when" that the later eras gain.
**Fix:** backfill approximate dates for Eras 0–5, or add a note that early dating was not captured.

**M3 — Code and skill artifacts inside the doc tree.**
`12_cornell_rc_audit/octahedral_solid_angle.py` and `octahedral_solid_angle_gen.py` are executable generators (they produce the ΔΩ LUT referenced at `rc_audit_report.md:284-299`); `2/human.skill` is a skill definition. Mixing runnable code into a documentation archive means the docs can't be copied/rendered as pure documentation, and the scripts' relationship to the tree is implicit.
**Fix:** either move the `.py` scripts to a `tools/` location and keep only a pointer, or add a short `12_cornell_rc_audit/README.md` explaining that the scripts are the authoritative ΔΩ source.

**M4 — Renormalization vs solid-angle contract is stated differently across docs.**
`rc_audit_report.md:135-153` carefully distinguishes the wrong form `Σ(L·cos⁺·α)/Σ(cos⁺·α)` from the correct physical invariant `L_o = (ρ/π)·Σ L cos⁺ ΔΩ`, and §7.1 (lines 301-330) records that even the "corrected" A2 form kept the renormalization. But `journey.md:88` still cites the simpler `(4/D²)` form as the "consumer contract". A reader who only reads `journey.md` gets the over-simplified (and per the audit, "do not lock") form.
**Fix:** align `journey.md:88` with the audit's "lock the physical integral, not the constant" framing.

### Low

**L1 — File-count drift in the scope statement.**
The task brief says "~589 markdown files" and correctly enumerates the directories ("1..7, then 8_shadertoy … 12_cornell_rc_audit"). The count is now slightly stale: actual is 591 `.md` (588 excluding the three review documents). The directory enumeration itself is accurate. Minor, but worth refreshing in any future hand-off of this tree.

**L2 — Redundant summary layering in `1/`.**
Six summary/checklist/quickstart documents in `1/` (`IMPLEMENTATION_SUMMARY`, `IMPLEMENTATION_SUMMARY_QUICKSTART`, `BUILD_CHECKLIST`, `QUICKSTART`, `MIGRATION_TO_3D`, `SHADER_REORGANIZATION`) overlap heavily for a phase that is a frozen snapshot. One consolidated "Era 0 summary" would serve better than six near-stale files.

**L3 — `13_renderdoc_auto_rdoc.md` uses two different placeholders for the frame number.** The `<F>` placeholder is defined at line 24 and used in the outputs table (lines 18-22, e.g. `rdoc_frame_frame<F>.rdc`), but line 25's `renderdoccmd.exe thumb` command uses a separate `<x>` placeholder (`<x>.png`/`<x>.rdc`) that the reader must reconcile against the concrete `frame420` example in the manual re-run block (lines 109-113). Substance is consistent; presentation is mildly confusing. Cosmetic.

**L4 — Multiple overlapping review documents at the root.**
The root now holds three near-overlapping review artifacts — `A2A_REVIEW.md` (this file), `A2A_REVIEW.prev.md` (a near-identical snapshot, same `writer/critic/lead` header), and `MONO_REVIEW.md` (a separate single-agent review of the same target, dated 2026-08-21). None cross-references the others, so a reader has no way to tell which is authoritative, and their presence inflates the `.md` count while blurring the "tree under review" boundary (a review cannot count or review itself cleanly).
**Fix:** delete the `.prev` snapshot once this review is signed off; either fold `MONO_REVIEW.md`'s findings into this document or add a one-line "see also" pointer, and record which is canonical in a root README.

---

## 5. Recommendations

1. **Resolve C1 before anything else.** The `(4/D²)` provenance question gates every downstream parity claim. A one-paragraph resolution (which branch, or whether `dd4f5df` reverted it) should be recorded at the top of `rc_audit_report.md` before further A-milestone work.

2. **Add a top-level `README.md` / index.** One table mapping `1`–`12` + the two root files to their era/theme, with the caveat that `journey.md` is the authoritative spine. This is the highest-leverage single addition for a tree of this size.

3. **Standardize the directory naming and the critic packaging.** Either all-numeric or all-suffixed directory names; pick one of the three plan/impl/critic layouts and migrate the outliers. Rename `cluade_plan` → `claude_plan`.

4. **Mark stale documents as superseded.** Add a banner to `1/` (and other early snapshots) pointing to `journey.md` and `12_cornell_rc_audit/`, so the cascade-count and "auto-update" contradictions (H1, H2) can't mislead.

5. **Deduplicate and re-home artifacts.** One `human.skill` (not two), and move the two `.py` generators out of the doc tree (or document their role explicitly).

6. **Fix the stale cross-reference paths** in the `3/codex_plan_critic*` chain (M1) and add the missing `13_renderdoc_auto_rdoc.md ↔ journey.md Era 12` link (H5).

7. **Reconcile the consumer-contract framing** between `journey.md:88` and `rc_audit_report.md` §4.2/§5.2 (M4) so the two authoritative documents don't state the fix differently.

---

*Drafted by writer; verified by critic; integrated and signed off by lead.*
