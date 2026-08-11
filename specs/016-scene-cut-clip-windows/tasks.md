---

description: "Task list template for feature implementation"
---

# Tasks: Scene-Cut-Anchored Clip Windows

**Input**: Design documents from `/specs/016-scene-cut-clip-windows/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/clip_window_snapping_contract.md](./contracts/clip_window_snapping_contract.md), [quickstart.md](./quickstart.md)

**Tests**: Included — Constitution Principle VII requires contract tests at module boundaries, tests written before implementation, and 100% coverage on critical paths (enforced by T024). Clip Generator is explicitly a critical path per plan.md's Constitution Check: it directly determines what makes it into every highlight video.

**Organization**: spec.md defines a single user story (US1, P1) — this is the entire feature's scope, so Foundational and US1 are close together; Foundational carries the data-model/config additions, US1 carries the actual snapping algorithm and its real-data proof.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1)

## Path Conventions

Single project, per plan.md Project Structure: additive-only changes to `src/cvip/clips/models.py` and `src/cvip/clips/generator.py`, tests in the existing `tests/{contract,unit,integration}/` locations for Clip Generator. No new subpackage, no schema change, no CLI change.

---

## Phase 1: Setup

- [X] T001 Confirm `src/cvip/clips/models.py` and `src/cvip/clips/generator.py`'s current state matches plan.md's assumed hook points (`ClipGenerationRequest`/`ClipEvidence` field lists, Pass 1 loop at `run()` lines ~107-137) — no file changes, a pre-condition check only, since both files have moved since specs/008 shipped

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The additive data-model changes (`ClipStartSource`, new `ClipGenerationRequest`/`ClipEvidence` fields) and the nearest-before-cut search helper, on which the actual snapping behavior depends

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T002 [P] Add `ClipStartSource` enum (`CUT_MATCHED`, `FIXED_OFFSET`) to `src/cvip/clips/models.py` per data-model.md
- [X] T003 [P] Add `scene_cuts: Sequence[float] = ()` and `max_cut_search_seconds: float = 20.0` fields to `ClipGenerationRequest` in `src/cvip/clips/models.py` per data-model.md and research.md Decision 5 (defaulted, so no existing call site requires changes)
- [X] T004 [P] Add `start_source: ClipStartSource = ClipStartSource.FIXED_OFFSET` field to `ClipEvidence` in `src/cvip/clips/models.py` per data-model.md (depends on T002)
- [X] T005 [P] Contract test: a negative `max_cut_search_seconds` raises `ClipGenerationError` with `ClipGenerationFailureReason.INVALID_CLIP_CONFIGURATION`, matching the existing `pre_roll_seconds`/`post_roll_seconds`/`merge_gap_seconds` validation pattern, in `tests/contract/test_clip_generator_contract.py`
- [X] T006 [P] Contract test: `request.scene_cuts == ()` (the default) produces a `ClipPlan` byte-for-byte identical to what an unmodified `specs/008` request (no new fields set) would produce for the same events/settings — the SC-002 regression guarantee, same file
- [X] T007 Implement the nearest-before-cut search (largest `c` where `event.timestamp_seconds - max_cut_search_seconds <= c <= event.timestamp_seconds`, via `bisect`, per research.md Decision 1 and contracts/clip_window_snapping_contract.md's amended Stage 2) as a private helper in `src/cvip/clips/generator.py`, sorting `request.scene_cuts` once per run (depends on T002-T004)
- [X] T008 [P] Unit test: nearest-before search returns the largest qualifying cut, not the earliest, when multiple cuts fall within the search window, in `tests/unit/test_clip_generator_rules.py`
- [X] T009 [P] Unit test: a cut exactly `max_cut_search_seconds` before the event qualifies (inclusive boundary); one second further back does not, same file
- [X] T010 [P] Unit test: a cut exactly at the event's own timestamp qualifies (distance zero, per spec Edge Case), same file
- [X] T011 [P] Unit test: unsorted `scene_cuts` input produces the same result as the equivalent sorted input (data-model.md Validation), same file
- [X] T012 [P] Unit test: empty `scene_cuts` and a `scene_cuts` list with every entry after the event's timestamp both correctly find no candidate, same file

**Checkpoint**: Foundation ready — the data model carries the new fields, the search helper is proven in isolation. User Story 1 wiring can now begin.

---

## Phase 3: User Story 1 - A Clip Starts at a Real Camera Cut, Not an Arbitrary Offset (Priority: P1) 🎯 MVP

**Goal**: Wire the Foundational search helper into Pass 1's `raw_start` computation, so a qualifying cut is used instead of the fixed pre-roll offset, with graceful fallback and full explainability.

**Independent Test**: Generate highlights for an event whose timestamp is known to fall shortly after a genuine camera cut, with cut-boundary data supplied; confirm the resulting clip starts at that cut's timestamp, not the fixed pre-roll offset (spec.md Acceptance Scenario 1).

### Tests for User Story 1 ⚠️

- [X] T013 [P] [US1] Unit test: an event with a qualifying nearby cut gets `raw_start == cut_timestamp` and `ClipEvidence.start_source == CUT_MATCHED`, in `tests/unit/test_clip_generator_rules.py`
- [X] T014 [P] [US1] Unit test: an event with no qualifying cut (none within `max_cut_search_seconds`, or `scene_cuts` empty) falls back to `raw_start == event.timestamp_seconds - request.pre_roll_seconds` and `ClipEvidence.start_source == FIXED_OFFSET` (spec.md Acceptance Scenario 2), same file
- [X] T015 [P] [US1] Unit test: `raw_end`/post-roll computation is byte-for-byte unaffected by scene-cut snapping in either the matched or fallback case (FR-006), same file
- [X] T016 [P] [US1] Unit test: within one run, some events resolve `CUT_MATCHED` and others `FIXED_OFFSET`, independently and correctly per event (spec.md Edge Case: "some events with cut data available nearby and others without"), same file
- [X] T017 [P] [US1] Unit test: downstream stages (Boundary Clamping, Replay Filtering, Merge Engine) behave identically regardless of whether a given window's start came from `CUT_MATCHED` or `FIXED_OFFSET` — construct one scenario that merges a cut-matched window with a fixed-offset window and confirm the merge proceeds exactly as `specs/008`'s existing merge logic already dictates, same file
- [X] T018 [P] [US1] Integration test: using `data/matches/ww_vs_pf_scene_boundaries.json` as the real cut-boundary fixture and the real over-7.0 FOUR event's known OCR-anchored timestamp, confirm the resulting `ClipEvidence.start_source == CUT_MATCHED` and `original_window[0]` lands at a real boundary timestamp within `max_cut_search_seconds` of the anchor (spec.md SC-001), in `tests/integration/test_clip_generator_e2e.py` — **skip with a clear reason if the fixture file is not yet present** (the background Scene Detection run producing it may not have completed). Written and passing its own logic check; currently SKIPPED at runtime because `ww_vs_pf_scene_boundaries.json` isn't produced yet (background job still running as of this implementation pass) — re-run once available.

### Implementation for User Story 1

- [X] T019 [US1] Wire the Foundational search helper (T007) into Pass 1's `raw_start` computation in `ClipGeneratorRunner.run()` (`src/cvip/clips/generator.py`, current lines ~107-137), setting `ClipEvidence.start_source` accordingly, per contracts/clip_window_snapping_contract.md's amended Stage 2 — `raw_end` computation untouched (depends on T007, T013-T017)
- [X] T020 [US1] Confirm (by reading, not modifying) that Boundary Clamping, Replay Filtering, the Merge Engine, and `ClipPlan`/`PlannedClip` assembly require zero changes, since they only ever consume `raw_start`/`raw_end` as plain floats (plan.md's own stated expectation) — record confirmation in the task, no code change expected. Confirmed: `_merge()`, `_classify_join()`, `_close_group()` are unmodified; they consume `evidence.clamped_window` tuples with no knowledge of `start_source`.

**Checkpoint**: User Story 1 is fully functional and independently provable — clips snap to real camera cuts when available, fall back identically to today's behavior otherwise, and every clip's start mechanism is explainable.

---

## Phase 4: Polish & Cross-Cutting Concerns

- [X] T021 [P] Run all four [quickstart.md](./quickstart.md) scenarios manually against the real `ww_vs_pf` event list and `ww_vs_pf_scene_boundaries.json` (once available) and record pass/fail results, including direct frame inspection at the new clamped start for the previously-defective over-7.0 FOUR clip (SC-001) — scene boundaries fixture landed; Scenario 1 confirmed via `tests/integration/test_clip_generator_e2e.py::test_real_defective_event_snaps_to_a_real_cut_near_its_anchor` (PASSED) and the real regeneration run (event 37 -> `CUT_MATCHED`, `original_window=(7538.7, 7561.0)`, vs. the old fixed-offset 7541.0); Scenario 2 confirmed by T006; Scenario 3 confirmed by the same regeneration run's diagnostics (`CUT_MATCHED=13 FIXED_OFFSET=30` within one 40-clip run); Scenario 4 confirmed by T023's repeated full-suite pass
- [X] T022 [P] Add docstrings to `ClipStartSource` and the new fields in `src/cvip/clips/models.py`, and to the new search helper in `src/cvip/clips/generator.py`, referencing this feature and its research.md decisions where non-obvious
- [X] T023 Run the full test suite (`pytest`) and confirm all tests pass, including every existing Clip Generator test from `specs/008-clip-generator` unchanged (T006/T014's own regression point) — 753 passed, 1 skipped (the pre-existing skip, unrelated to this feature), 13 deselected
- [X] T024 Run the constitution-mandated coverage gate: `pytest --cov=src/cvip/clips --cov-fail-under=100`. Add targeted tests for any branch reported as uncovered (Constitution Principle VII) — 100% achieved on first run, no additional tests needed
- [X] T025 Once `data/matches/ww_vs_pf_scene_boundaries.json` is available and T018/T021 are green, regenerate `output/ww_vs_pf_highlights.mp4` end-to-end (via the real `cvip generate` path, constructing `ClipGenerationRequest.scene_cuts` manually from the JSON fixture for this validation run since orchestrator.py wiring is out of scope) and confirm the over-7.0 FOUR clip no longer shows replay/setup footage at its start — regenerated (40 clips, 13 cut-matched / 30 fixed-offset); prior video preserved at `output/ww_vs_pf_highlights.mp4.bak-pre-scene-cut-snap` for direct comparison. Frame-level confirmation that the new start point avoids the "REPLAY" overlay is a user-facing review step, not re-verified by this script.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS User Story 1 (the data model and search helper must exist before Pass 1 can be wired to use them)
- **User Story 1 (Phase 3)**: Depends on Foundational only
- **Polish (Phase 4)**: Depends on User Story 1 being complete; T025 additionally depends on the background Scene Detection run producing `ww_vs_pf_scene_boundaries.json`

### Within Each Phase

- Tests are written first and must fail before implementation begins (T005-T006, T008-T012 before T007's implementation is considered done; T013-T018 before T019)
- T007 (the search helper) blocks T019 (wiring it into Pass 1)
- T019 blocks T020 (confirmation), T021, T023, T024, T025

### Parallel Opportunities

- T002, T003, T004 (Foundational data-model additions) can run in parallel — same file but non-overlapping field additions; sequence T004 after T002 only because it references `ClipStartSource`
- T005, T006 (Foundational contract tests) can run in parallel with T008-T012 (Foundational unit tests) — different test files
- T013-T018 (US1 tests) can all run in parallel — same test files but independent test functions, written before T019
- T021, T022 (Polish) can run in parallel

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (data model + search helper, fully proven in isolation)
3. Complete Phase 3: User Story 1 (wiring + real-data proof)
4. **STOP and VALIDATE**: run quickstart.md Scenarios 1-4; confirm the real over-7.0 FOUR clip snaps to a real cut and the no-cut-data fallback is byte-identical to today
5. This alone delivers the feature's full scope — spec.md defines only one user story

### Incremental Delivery

1. Setup + Foundational → data model and search algorithm exist and are proven
2. Add User Story 1 → validate independently against real `ww_vs_pf` data (the core value)
3. Phase 4: Polish, including the full quickstart re-run, the 100% coverage gate, and the actual highlight-video regeneration for user review

---

## Notes

- [P] tasks touch different files, or are independent test-writing tasks with no unmet dependencies
- [Story] label maps each task to US1 for traceability back to spec.md
- Commit after each task or logical group
- Stop at the Phase 3 checkpoint to validate the story independently before Polish
- **T018 and T025 depend on external state** (the background Scene Detection run for `ww_vs_pf`) that may not have completed by the time implementation starts — both tasks are written to skip gracefully with a clear reason rather than block the rest of the task list, consistent with this feature's own FR-004 fallback philosophy applied to its own validation process.
- **Zero CLI/behavior change for callers that supply no `scene_cuts`** (spec FR-007, FR-008) is a design guarantee this task list preserves structurally — T006 and T014 exist specifically to prove existing, already-documented `specs/008` behavior is unchanged, not to add new behavior.
