# CVIP Pre-Implementation Architecture Review

**Reviewer stance**: Principal Software Architect, final review before implementation begins.
**Scope**: constitution.md, PRD.md, technical_plan.md, features.md, cli.md, MVP_PLAN.md, RISK_REGISTER.md, DEPENDENCIES.md, README.md, CLAUDE.md, config/default.yaml, requirements*.txt, setup.ps1, tests/README.md, and the full `specs/001-video-loader/` feature (spec, plan, tasks, data-model, research, quickstart, contract).
**Authority order applied**: Constitution > PRD > Technical Plan > Features (per instructions).

---

# Executive Summary

The project has one genuinely excellent, implementation-ready artifact — the Video Loader feature (`specs/001-video-loader/`) — and a well-reasoned constitution. Everything built *on top of* that foundation (technical_plan.md, cli.md, config/default.yaml) is internally consistent with each other and with Video Loader. That is the good news.

The bad news: the project has one **severe, unaddressed architecture gap** that must be resolved before Event Detection (Module 5) can be built — the data model has no way to capture *how* a wicket fell (bowled/caught/LBW/run out/stumped), who took a catch, or bowler-attributed consecutive wickets, yet the PRD's own ranking table and `config/default.yaml` assign importance scores to `RUN_OUT`, `CATCH`, `HAT_TRICK`, and `MATCH_WINNING_SHOT` as if they were independently detectable. As designed, they are not. This is not a polish issue; it is a load-bearing gap.

Second, there is no persisted `matches` table anywhere in the schema, which means Video Loader's own `file_hash` (built specifically to support the constitution's Single-Pass Analysis principle) has nothing to be checked against — the re-analysis guard (`cvip analyze --force`, exit code 9) is currently unimplementable as specified.

Third, two files that exist specifically to orient a reader (or a future AI session) — `README.md` and `CLAUDE.md` — are stale relative to everything built since, containing broken paths, wrong module names, and a nonexistent `python -m src.analyzer` usage example.

None of this invalidates the architecture. Video Loader proves the team (and process) can produce rigorous, analyzable specs. The job now is to apply that same rigor to the two or three cross-cutting gaps below before Module 5 gets its own `/speckit-specify` pass, and to spend twenty minutes fixing the stale orientation files.

---

# Architecture Scorecard

| Dimension | Score /10 | Notes |
|---|---|---|
| Documentation Hierarchy & Consistency | 6 | Good reference-not-duplicate pattern for Video Loader/CLI; README and CLAUDE.md are stale |
| Naming & Terminology Consistency | 5 | Event taxonomy fragmented across 4 documents; module naming drifts (`video`/`video_loader`/`video-loader`) |
| Product ↔ Technical Alignment | 5 | "Resume interrupted processing" (PRD §16) has zero technical coverage; dismissal-type detection gap (see Executive Summary) |
| Architecture Soundness | 6 | Video Loader is an excellent template; no Orchestrator module is defined despite the CLI implying one exists |
| Data Model Quality | 5 | Missing `matches` table; `over REAL` stores non-decimal cricket notation as a float; no player/team name normalization |
| Pipeline Contract Completeness | 4 | Only Video Loader (1 of 9 modules) + CLI have explicit typed contracts; the rest are prose bullets |
| Configuration Management | 6 | Centralized in one file (good); no `config_version`; ranking includes scores for undetectable event types; hash sample size unspecified |
| Error Handling Standardization | 6 | Excellent for Video Loader; no cross-module exception hierarchy or complete CLI exit-code mapping yet |
| Logging & Observability | 6 | `ExecutionDiagnostics` is a strong, reusable foundation; no correlation/run ID; no mechanism to actually measure the ≥95%/≥90% accuracy targets |
| Testing Strategy | 5 | Exemplary TDD discipline for Video Loader; **golden-dataset/accuracy-verification tests are entirely absent project-wide** |
| Performance Planning | 5 | Video Loader's micro-budget (10s/200MB) is rigorous; no per-module time/memory budget exists for the other 8 modules, so the 40-min/6GB target is unverified on paper |
| Constitution Compliance (current) | 6 | Principles are well-applied where specs exist; Single-Pass and Detection-Accuracy principles are currently unenforceable/unverifiable at the platform level |
| Future/Extensibility Readiness | 6 | Module 6's v1-heuristic/future-AI swap point is a good model; "Cloud Acceleration" (PRD §17) directly conflicts with the ratified Offline-First principle |

**Weighted overall: ~55/100** (platform-wide). See Implementation Readiness for a module-by-module breakdown — this number is dragged down by cross-cutting gaps, not by any single module's quality.

---

# Critical Issues (Must Fix)

**C1. The data model cannot produce several event types the PRD and config already rank.**
`scoreboard_readings` (technical_plan.md Database Schema) captures only `runs`, `wickets` (a count), `over`, `batter`, `non_striker`, `bowler`, `run_rate`. There is no dismissal-type field, no fielder-attribution field, and no ball-level (as opposed to over-level, once-per-second) granularity. Yet:
- PRD Module 7's ranking table scores `Hat Trick: 100`, `Run Out: 90`, `Catch: 85` as if independently detectable.
- `config/default.yaml`'s `events.ranking` block includes `HAT_TRICK`, `MATCH_WINNING_SHOT`, `RUN_OUT`, `CATCH`, `GREAT_FIELDING`.
- `technical_plan.md` Module 5's actual MVP event list is only `FOUR, SIX, WICKET, FIFTY, CENTURY, TEAM_MILESTONE` — a generic `WICKET`, not `RUN_OUT`/`CAUGHT`/`BOWLED`.
A wicket falling only increments `wickets` and swaps `batter`/`non_striker` in the OCR data — there is no source of "how" or "by whom." `Hat Trick` additionally requires ball-level, bowler-attributed consecutive-wicket tracking that a once-per-second over-level OCR feed cannot reconstruct.
**Fix before Module 5 is spec'd**: either (a) explicitly descope `RUN_OUT`/`CAUGHT`/`BOWLED`/`HAT_TRICK`/`CATCH`/`GREAT_FIELDING` detection from MVP and V1.5, remove their entries from `config/default.yaml`'s ranking dict, and keep `WICKET` generic until Fielding Detection (Module 6, deferred) or an enhanced OCR source exists — or (b) design the actual data source (e.g., OCR of a post-wicket "how out" scorecard overlay) that would make these detectable, and update Module 4/5's contracts accordingly. Right now the config quietly promises detection the architecture cannot deliver.

**C2. No `matches` table — Video Loader's `file_hash` (FR-014) has nothing to be checked against.**
FR-014 was built specifically so a re-analysis attempt "can be recognized as such" (Single-Pass Analysis, Constitution Principle III), and `cli.md` defines `--force` and exit code 9 ("Analysis already exists") around exactly this. But `data-model.md` explicitly states Video Loader "has no persistent storage of its own," and `technical_plan.md`'s schema has no table for match-level metadata (source path, `file_hash`, duration, resolution, analyzed-at timestamp) at all. `cvip inspect-db`'s required output ("Match ID, Source video path, Duration, FPS, Resolution, Analysis timestamp") cannot be satisfied by the current three tables (`events`, `replays`, `scoreboard_readings`) either.
**Fix**: add a `matches` table (or equivalent) to `technical_plan.md`'s Database Schema now, before the Event Database gets its own feature spec, so the Single-Pass Analysis guard and `inspect-db` are both actually implementable.

**C3. `CLAUDE.md` is stale and will actively mislead future sessions.**
It lists 8 modules (folding Fielding Detection into "Event Detection," omitting Module 1a and 4a and the CLI entirely), and ends with `## Reference: Full PRD in /mnt/project/` — a path from a different environment that doesn't exist in this repo. Since this file is auto-loaded into every future Claude Code session's context, it is currently a liability, not an asset.
**Fix**: regenerate it to match the current module list, `src/cvip/` package layout, and correct PRD path (`docs/PRD.md`).

**C4. Golden-dataset / accuracy-verification tests do not exist anywhere in the plan.**
Constitution Principle IV and PRD §18 mandate ≥95% event-detection accuracy and ≥90% replay-removal accuracy as **MUST** requirements. `tests/README.md`'s four categories (unit/contract/integration/benchmark) have no "golden dataset" or "accuracy" category, and no document anywhere defines a labeled reference match to compare pipeline output against. As designed, these two headline numbers are currently unfalsifiable — there's no way to know if the built system meets them.
**Fix**: add a golden-dataset test category before Module 5 (Event Detection) or Module 3 (Replay Detection) reach implementation, since accuracy can only be measured against ground truth, and acquiring/annotating a reference match takes lead time.

---

# High Priority Improvements

**H1. No Pipeline Orchestrator module is defined.** `technical_plan.md`'s CLI section says `cvip analyze` "orchestrates Modules 1 → 1a → 2 → 3 → 4 → 4a → 5," implying a component that sequences them, handles partial failure, and would own PRD §16's "Resume interrupted processing" requirement — but no such module appears in the Module Specifications list. Without an explicit Orchestrator contract, that logic will likely get written directly into the CLI layer, undermining the "each module independently testable" principle (V).

**H2. PRD §16's "Resume interrupted processing" is an orphaned requirement.** It appears once, in the PRD's Non-Functional Requirements list, and is never mentioned again in `technical_plan.md`, `cli.md`, or any spec. Either design for it (likely an Orchestrator responsibility, per H1) or explicitly move it to `Deferred Until Later` in `technical_plan.md` with a stated reason.

**H3. No player/team name normalization.** Module 4 (OCR) reads names as free text with no roster or fuzzy-matching layer, yet `cli.md`'s `--player "Virat Kohli"` / `--team India` filters imply exact-string matching. An OCR misread or a "V Kohli" vs. "Virat Kohli" broadcast-graphic difference will silently produce zero results rather than a match. This needs at least a documented decision (exact match only for MVP, with a known limitation) before `generate --template player` ships.

**H4. `over REAL` stores non-decimal cricket notation as a float.** "18.4" means "18 overs, 4 balls" — not 18.4 as a real number (there is no `.6`–`.9`, and ball counts don't behave like a decimal fraction). Storing this as `REAL` will silently produce wrong results for any ball-count arithmetic or phase-boundary comparison (`--start-over`/`--end-over` in `cli.md`, Powerplay/Middle/Death-overs filtering in the PRD's Custom Highlight Builder). Recommend two integer columns (`over_number`, `ball_in_over`) or a computed `balls_bowled` column, with the `18.4` notation reserved for display only.

**H5. No per-module time/memory budget exists except for Video Loader's.** The 10,000+ Tesseract OCR calls implied by "once per second for a 3-4 hour match" (Module 4) is the single most obvious bottleneck candidate for the 40-minute budget (`RISK_REGISTER.md` R3 names this risk generically but no document estimates its actual cost). Recommend a rough per-module time/memory table in `technical_plan.md`, the same way Video Loader budgeted itself (SC-001/SC-005), so the aggregate 40-min/6GB target can be sanity-checked on paper before implementation.

**H6. `README.md` contains three broken/stale references.** (1) "See docs/technical_plan.md" — the real path is `specs/technical_plan.md`. (2) The Workflow section's `python -m src.analyzer` / `python -m src.highlight_generator` don't match the actual `src/cvip/` package or the `cvip` CLI defined in `specs/cli.md`. (3) "API Contracts" links to `./contracts/` — a location the project deliberately moved away from (contracts live in `specs/001-video-loader/contracts/`), yet `setup.ps1` still physically creates an empty top-level `contracts/` directory, actively reinforcing the wrong location.

**H7. `setup.ps1` no longer matches the real project structure.** It creates a flat `src/` (not `src/cvip/{video,ocr,replay,...}`), a stale top-level `contracts/` directory (see H6), and two directories (`memory/`, `scripts/`) that no other document defines a purpose for.

---

# Medium Priority Improvements

**M1. Module naming drifts across four spellings for the same feature**: package folder `src/cvip/video/`, spec directory `specs/001-video-loader/`, test/fixture naming `test_video_loader_*` / `tests/fixtures/video_loader/`, and the `ExecutionDiagnostics.module_name` example value `"video_loader"`. Recommend the diagnostics `module_name` and any future fixture naming use the short form (`video`) to match the actual package, reserving the hyphenated long form for spec directory names only.

**M2. `events.confidence` derivation from Module 4's two OCR confidence fields is undefined.** Module 4 produces `ocr_confidence` and `parse_confidence` per reading; Module 5 writes a single `confidence` per event. No document states the formula (min? product? parse_confidence only?). Pin this down before Module 5's spec is written.

**M3. PRD's illustrative event JSON uses camelCase (`eventId`, `clipStart`) while the actual SQL schema uses snake_case (`event_id`, `clip_start_seconds`).** This is expected/fine internally, but `cli.md`'s `export-timeline --format json` will emit *something* — its casing convention is undefined. Decide now (recommend snake_case, matching the DB, for internal consistency) rather than after the exporter is built.

**M4. No `config_version` key in `config/default.yaml`.** If the config shape changes later, nothing can detect or warn about loading an old-format file.

**M5. FR-014's file-hash sample size is never pinned to a number.** `research.md` and `tasks.md` T015 both say "a fixed-size prefix... and the file size" without stating the actual byte count — two implementers could reasonably pick different values. Specify it (e.g., "first 1 MiB + last 1 MiB + exact byte size") in `data-model.md`.

**M6. No correlation/run ID in `ExecutionDiagnostics`.** A single `cvip analyze` invocation runs 6+ modules, each emitting its own diagnostics record — with no shared ID, two consecutive `analyze` runs' log lines can't be distinguished from each other by grepping the log file.

**M7. No mechanism reports the constitution-mandated accuracy percentages (≥95%/≥90%) for a given match.** Even once golden-dataset tests exist (C4), something in the running system (e.g., `cvip inspect-db` or a dedicated report command) should surface "this match: X% of expected events detected, Y% replay removed" so compliance is visible per-run, not just in CI.

**M8. No enum enforcement (CHECK constraint) on `event_type`/`detection_method` columns.** SQLite has no native enum type; a `CHECK (event_type IN (...))` constraint would catch a typo'd event type at insert time rather than silently corrupting query filters later.

**M9. Missing `created_at` on `replays` and `scoreboard_readings`.** `events` has it; the other two tables don't. Minor, but inconsistent and hampers debugging.

**M10. No index on `replays(start_seconds, end_seconds)`.** Module 5's is-this-a-replay cross-reference and Module 8's clip-overlap logic both do interval work against this table.

**M11. `technical_plan.md` Module 7 still lists all 10 importance-score values inline** even though it also says "see `config/default.yaml` for the live defaults" — meaning the numbers exist in two places and can silently drift. Keep the values in the config only; the doc should describe the mechanism, not repeat the numbers.

---

# Low Priority Improvements

**L1.** `technical_plan.md` uses "Module N:" while `PRD.md` uses "Module N –" (en-dash) — trivial style inconsistency.

**L2.** `README.md`'s "Development Phases" table (generic Week 1–10 phases) duplicates and conflicts with `docs/MVP_PLAN.md`'s actual Phase 1–6 breakdown. Remove the table and link to `MVP_PLAN.md` instead.

**L3.** `README.md`'s Testing section references `pytest tests/test_scene_detection.py`, a file that doesn't exist and doesn't match the established `tests/{unit,contract,integration,benchmark}/test_video_loader_*.py` layout.

**L4.** No `pyproject.toml` exists yet; `tasks.md` T003 still frames this as an open "or" between `pyproject.toml` / `pytest.ini`. Recommend committing to `pyproject.toml` now — it also gives a natural home for `black`/`pylint`/`mypy` config currently scattered as ad hoc CLI flags in README, and for a `cvip` console-script entry point.

**L5.** "Cloud Acceleration" (PRD §17, Future Enhancements) directly conflicts with the ratified Offline-First principle (Constitution I: "MUST NOT introduce cloud dependencies... at runtime"). Not urgent, but worth a one-line acknowledgment in `technical_plan.md`'s Deferred section that this would require a constitutional amendment, not just an engineering effort.

---

# Naming & Terminology Recommendations

**Canonical event taxonomy** — the project currently has four different event lists (PRD Module 5's 6 detection types, PRD Module 7's 10 ranked types, PRD §8's 40+ item full taxonomy, and `config/default.yaml`'s 10 ranking keys). Recommend collapsing to a single tiered canonical list, tagged with what can *actually* be detected today:

| Event | MVP Detectable? | Data source needed |
|---|---|---|
| `FOUR`, `SIX` | Yes (Module 5) | Scoreboard OCR run delta |
| `WICKET` (generic) | Yes (Module 5) | Scoreboard OCR wicket-count delta |
| `FIFTY`, `CENTURY`, `TEAM_MILESTONE` | Yes (Module 5) | Scoreboard OCR run threshold |
| `RUN_OUT`, `BOWLED`, `CAUGHT`, `LBW`, `STUMPED`, `HIT_WICKET` | **No — see C1** | Undefined; needs dismissal-type source |
| `CATCH`, `GREAT_FIELDING`, `DIVING_CATCH`, etc. | No (Module 6, deferred) | Fielding Detection (post-MVP) |
| `HAT_TRICK`, `MATCH_WINNING_SHOT` | **No — see C1** | Needs ball-level + bowler-attributed tracking |

Recommend: use `UPPER_SNAKE_CASE` everywhere code/config/DB-facing (already the majority convention), remove the not-yet-detectable rows from `config/default.yaml`'s ranking dict until their data source is designed, and keep PRD §8's full taxonomy clearly labeled as long-term vision rather than near-term scope.

**Module naming**: package folders should stay short (`video`, `ocr`, `replay`, `events`, `clips`) — already true in `src/cvip/`. Diagnostics `module_name` values and any future fixture directories should match that short form rather than the longer `video_loader` currently used in `ExecutionDiagnostics`'s example and test/fixture paths (M1).

**JSON export casing**: standardize on `snake_case` for `export-timeline --format json` output, matching the DB schema, and treat PRD §9's camelCase example as illustrative-only, not a field-naming mandate (M3).

---

# Missing Decisions

1. How is a wicket's dismissal type, and a catch's fielder, ever captured? (C1 — blocks Module 5/6 specs)
2. What table persists match-level metadata (`file_hash`, source path, analyzed-at) for `--force`/`inspect-db`? (C2 — blocks Event Database spec)
3. What is the Pipeline Orchestrator's contract, and does it own "resume interrupted processing"? (H1/H2)
4. What is `events.confidence`'s derivation formula from `ocr_confidence`/`parse_confidence`? (M2)
5. What is the exact byte count for FR-014's sampled file hash? (M5)
6. What casing convention does JSON export use? (M3)
7. What is the golden/reference dataset for accuracy verification, and who annotates it? (C4)
8. Is player/team filtering exact-match only for MVP, or is fuzzy matching in scope? (H3)
9. Per-module time/memory budgets for Modules 2–9 — what are they, and do they sum under 40 min/6GB? (H5)
10. `pyproject.toml` vs. `pytest.ini`/scattered config — pick one. (L4)

---

# Technical Debt Risks

- **Config/schema drift**: importance scores duplicated in `PRD.md`, `technical_plan.md`, and `config/default.yaml` (M11) — three places to update if a score changes, two of which (PRD, tech plan) will likely be forgotten.
- **Stale orientation files compounding over time**: `CLAUDE.md` and `README.md` are already behind actual project state after only one feature (Video Loader). Without a habit of updating them per feature, this gap will widen every subsequent feature.
- **`setup.ps1` structural drift**: already diverged from the real `src/cvip/` layout after one feature; will keep diverging unless it's either updated per-structure-change or retired once bootstrap is complete.
- **Orphaned config keys** (C1's `RUN_OUT`/`CATCH`/`HAT_TRICK`/etc.) will confuse a future implementer into building detection logic for events the architecture can't support, wasting effort mid-sprint.
- **Free-text player/team fields** (H3) will require a schema migration (roster table + FK) the moment fuzzy matching or player-recognition (PRD §17 Future Enhancement) is prioritized — not blocking now, but not free later either.
- **`over REAL`** (H4) is the kind of bug that won't surface until someone queries a specific over range and gets subtly wrong results — expensive to diagnose after the fact, cheap to fix now.

---

# Constitution Compliance Matrix

| Principle | Video Loader | Platform-wide |
|---|---|---|
| I. Offline-First, Always | ✅ Explicit (FR-009, no network calls) | ⚠️ No violations planned, but unverified for Modules 2-9 (no specs yet); PRD's "Cloud Acceleration" future item directly conflicts (L5) |
| II. Performance is Non-Negotiable | ✅ 10s/200MB micro-budget defined and gated | ⚠️ At risk — no per-module budget exists to confirm the 40-min/6GB aggregate is achievable (H5) |
| III. Single-Pass Analysis | ✅ `file_hash` (FR-014) designed for exactly this | ❌ Unenforceable as designed — no `matches` table to check the hash against (C2) |
| IV. Detection Accuracy Requirements | N/A (no cricket events detected by this module) | ❌ Unverifiable — no golden dataset exists to measure ≥95%/≥90% against (C4); confidence-score plumbing exists but its aggregation formula is undefined (M2) |
| V. Modular & Extensible Architecture | ✅ Clean `LoadResult` contract, independently testable | ⚠️ At risk — missing Orchestrator module (H1) risks the CLI becoming the de facto integration point for all 9 modules |
| VI. Fail Fast, Never Silently | ✅ 4-value deterministic failure taxonomy | ✅ Module 4's "one bad OCR reading ≠ pipeline failure" is a correct, well-reasoned application, not a violation |
| VII. Test-First Development | ✅ Full TDD task breakdown + 100% coverage gate | ⚠️ No tasks exist yet for Modules 2-9 (expected/pending); golden-dataset test category is absent even at the planning level (C4) |

---

# Implementation Readiness Checklist

- [x] Constitution ratified and internally consistent
- [x] PRD complete as a vision document
- [x] Video Loader: spec, plan, tasks, data model, contract, research, quickstart all present and cross-consistent
- [x] CLI command surface specified with MVP/V1.5 phasing
- [x] Central runtime configuration file exists
- [ ] `matches` table / persistence for Single-Pass re-analysis detection (C2)
- [ ] Dismissal-type / fielder-attribution data source decision (C1)
- [ ] Pipeline Orchestrator module defined (H1)
- [ ] Golden-dataset accuracy test strategy defined (C4)
- [ ] Per-module performance budget for Modules 2-9 (H5)
- [ ] `CLAUDE.md` regenerated to match current architecture (C3)
- [ ] `README.md` broken references fixed (H6)
- [ ] `setup.ps1` structure reconciled or retired (H7)
- [ ] Feature specs (`/speckit-specify`) written for Modules 2-9 individually

---

# Final Recommendation

**Do not start Module 5 (Event Detection) or the Event Database feature until C1 and C2 are resolved** — both require a scoping or schema decision that would otherwise force a rework mid-implementation. Video Loader itself is ready to implement today (`/speckit-implement` against `specs/001-video-loader/tasks.md`) with no blockers — nothing above touches its scope.

Suggested sequence:
1. Resolve C1 (descope or design dismissal-type detection) and C2 (add a `matches` table) in `technical_plan.md` — both are documentation-only decisions, no code yet.
2. Fix C3 (`CLAUDE.md`) and H6/H7 (`README.md`, `setup.ps1`) — low effort, high value for anyone (or any future session) orienting on this repo.
3. Implement Video Loader (`specs/001-video-loader/tasks.md`, T001-T032) — already fully specified.
4. Before writing Module 5's spec, resolve M2 (confidence formula) and define the Orchestrator's contract (H1/H2).
5. Stand up a golden-dataset test category (C4) in parallel with Module 3/4/5 development — it has long lead time (needs a labeled reference match) and should not be an afterthought once those modules are "done."

Overall: this is a well-run spec process that caught and fixed real issues at every prior step (the `/speckit-analyze` pass on Video Loader is genuine evidence of that discipline). The gaps above are exactly the kind of thing that discipline is good at catching — they just haven't been pointed at the *cross-module* and *orientation-file* layers yet. Fix the four Critical items and this becomes a genuinely strong pre-implementation baseline.
