---

description: "Task list template for feature implementation"
---

# Tasks: Anchor Validation for Timeline Alignment

**Input**: Design documents from `/specs/014-anchor-validation/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/anchor_validation_contract.md](./contracts/anchor_validation_contract.md), [quickstart.md](./quickstart.md)

**Tests**: Included — Constitution Principle VII (Test-First Development) requires contract tests at module boundaries, tests written before implementation, and 100% coverage on critical paths (enforced by T046). Timeline Alignment is explicitly a critical path per plan.md's Constitution Check, since it now gates what makes it into a highlight video.

**Organization**: Tasks are grouped by user story (from spec.md) to enable independent implementation and testing of each story.

**Note on shared engine**: The candidate-ranking extension (Stage 2a) and the core anchor-validation decision engine (Stage 2b: signal evaluators, hard-reject logic, confidence-tier classification) are built once, in Foundational — all three user stories depend on this same engine identically (research.md Decision 1's "one reusable component" requirement, inherited from 013, is structural here too). This mirrors the precedent `specs/013-match-metadata-validation/tasks.md` itself set for Ground Truth Extraction/Timeline Alignment. Each user story's own phase adds only its story-specific *consumption* of the engine's output: US1 wires the accept/reject decision into `recovery_eligible` (the correctness fix itself), US2 surfaces the per-event diagnostic trail to the user, US3 adds the run-level aggregate summary.

**Note on existing-file changes**: `alignment.py`/`alignment_models.py`/`validation.py`/`validation_models.py` are modified in place (additive fields, per data-model.md) rather than duplicated — `recovery.py`/`recovery_models.py`/`enrichment.py`/`enrichment_models.py` are **not touched at all**, since `recovery_eligible` keeps its existing name/type and `find_recovery_candidates()` is a pure filter on it (research.md Decision 8).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)

## Path Conventions

Single project, per plan.md Project Structure: two new files in the existing `src/cvip/metadata/` subpackage, additive modifications to four existing files there, one additive config block, tests in the existing `tests/{contract,unit,integration}/`.

---

## Phase 1: Setup

**Purpose**: New files for this feature's two-file addition

- [X] T001 [P] Create empty `src/cvip/metadata/anchor_validation.py` and `src/cvip/metadata/anchor_validation_models.py` module files per plan.md Source Code layout
- [X] T002 [P] Create empty test file placeholders: `tests/contract/test_anchor_validation_contract.py`, `tests/unit/test_anchor_validation.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The shared validation engine every user story consumes identically — config, data model, candidate ranking, signal evaluators, the accept/reject decision, confidence-tier classification

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T003 [P] Add the `metadata.anchor_validation` config block (`ocr_confidence_high`/`_medium`/`_low`, `neighbor_pacing_tolerance`) to `config/default.yaml` per data-model.md's Configuration Additions and research.md Decision 4's calibration rationale — include the same "reasoned calibration from real samples, revisit if wrong" comment style as this file's existing `scene_threshold`/`replay.confidence_threshold` blocks
- [X] T004 [P] Implement `AnchorConfidenceTier` enum (`HIGH`/`MEDIUM`/`LOW`/`UNRESOLVED`) and the four `SignalVerdict` enums (OCR quality, score-state, ordering, neighbor pacing) per data-model.md, in `src/cvip/metadata/anchor_validation_models.py`
- [X] T005 [P] Implement `AnchorValidationSignals`, `CandidateAnchor`, `OrderingConflict`, `AlignmentValidationSummary` frozen dataclasses per data-model.md, same file (depends on T004)
- [X] T006 Extend `MatchAlignmentEvidence` in `src/cvip/metadata/alignment_models.py` with the three new fields (`validation_tier`, `validation_signals`, `rejected_candidates`) and update its docstring to document `recovery_eligible`'s changed meaning per data-model.md's "Changed Entities" section — additive only, no existing field removed or renamed (depends on T005)
- [X] T007 [US-shared] Contract test: `_rank_candidates()` is a strict generalization of today's `_search_reading()` — for any fixture where the old function returns a single reading, the new function's ranked output has that same reading first, per contracts/anchor_validation_contract.md Stage 2a's postcondition, in `tests/contract/test_metadata_alignment_contract.py`
- [X] T008 [P] Contract test: `validate_anchors()` never drops an input event (`len(result) == len(ranked_candidates)`), and every event with an empty candidate tuple is `UNRESOLVED` with `validation_signals=None` and `rejected_candidates=()` per contracts/anchor_validation_contract.md's postconditions, in `tests/contract/test_anchor_validation_contract.py`
- [X] T009 [P] Contract test: `validate_anchors()` determinism — two calls with identical `ranked_candidates`/`config` produce byte-identical output (spec FR-013), same file
- [X] T010 [P] Contract test: for every event classified `HIGH`/`MEDIUM`, its accepted timestamp is strictly ordered relative to every other accepted anchor earlier/later in that innings' over.ball order — the run-level ordering invariant (spec SC-002) holding by construction, same file
- [X] T011 [P] Unit test: OCR-quality signal evaluator — verdicts `HIGH`/`MEDIUM`/`LOW`/`INSUFFICIENT` against the configured thresholds (T003), using the real `ocr_confidence` values (0.27, 0.45, 0.41...) pulled from the `ww_vs_pf` investigation as fixture data, in `tests/unit/test_anchor_validation.py`
- [X] T012 [P] Unit test: score-state consistency evaluator — `CONSISTENT` for a plausible runs/wickets delta relative to the nearest accepted anchor (reusing the "plausible ceiling per ball advanced" concept from `src/cvip/events/state_transition.py`, research.md Decision 5), `UNKNOWN` when the candidate's `runs`/`wickets` are both null, `INCONSISTENT` for an implausible jump or a decrease, same file
- [X] T013 [P] Unit test: ordering evaluator — `PRESERVED` when the candidate's timestamp fits between its innings' neighboring already-accepted anchors in over.ball order, `VIOLATION` (naming the conflicting anchor, populating `OrderingConflict`) otherwise, including the first-event-in-innings case (nothing to compare against yet → judged on other signals alone, per spec Edge Cases), same file
- [X] T014 [P] Unit test: neighbor-pacing evaluator — `WITHIN_EXPECTED`/`SUSPICIOUS` against `neighbor_pacing_tolerance`, `UNKNOWN` when too few accepted anchors exist yet in the innings, same file
- [X] T015 [P] Unit test: confidence-tier classification rule table (research.md Decision 6) — one test per HIGH/MEDIUM/LOW/UNRESOLVED rule combination, same file
- [X] T016 [US-shared] Implement `alignment.py`'s `_rank_candidates()`, replacing `_search_reading()`'s single-result return with every reading found across the tiered search, ranked (search tier, then ball-offset, then `ocr_confidence` descending) per contracts/anchor_validation_contract.md Stage 2a (depends on T006, T007)
- [X] T017 Implement `anchor_validation.py`'s four signal-evaluator functions (`evaluate_signal_ocr_quality`, `evaluate_signal_score_state`, `evaluate_signal_ordering`, `evaluate_signal_neighbor_pacing`) per research.md Decisions 3-6 (depends on T005, T011, T012, T013, T014)
- [X] T018 Implement `anchor_validation.py`'s `validate_anchors()`: per-innings grouping, `(over_number, ball_in_over)` sort, forward walk maintaining running accepted-anchor state, try-ranked-candidates-until-one-clears-hard-rejects, confidence-tier classification, per contracts/anchor_validation_contract.md Stage 2b (depends on T017, T008, T009, T010, T015)
- [X] T019 Wire Stage 2a/2b into `alignment.py`'s `align()`: for each metadata event call `_rank_candidates()` then batch-call `validate_anchors()`, build the extended `MatchAlignmentEvidence` (including `recovery_eligible = matched_scoreboard_reading is not None and matched_detected_event is None and validation_tier in (HIGH, MEDIUM)`) per data-model.md's updated `recovery_eligible` definition (depends on T016, T018)
- [X] T020 [P] Unit test: `align()`'s existing detected-event matching (`_assign_detected_events`) is unaffected by the new validation stage — a `TRUE_POSITIVE` outcome does not depend on `validation_tier` (013's original behavior for already-detected events is preserved), in `tests/unit/test_metadata_alignment.py`

**Checkpoint**: Foundation ready — the validation engine exists, is wired into `align()`, and `recovery_eligible` reflects validation outcome. User story implementation can now begin.

---

## Phase 3: User Story 1 - Highlights Are Never Built From a Wrong Moment (Priority: P1) 🎯 MVP

**Goal**: A metadata event whose only supporting evidence is untrustworthy is excluded from automatic recovery — `recovery_eligible` (and therefore what `cvip validate --recover` writes to the Event Database) reflects a validated decision, not just "some reading existed."

**Independent Test**: Run recovery against a fixture (and, per quickstart.md Scenario 1, the real `ww_vs_pf` dataset) containing at least one event whose best candidate has low OCR quality/breaks ordering. Confirm that event is not recovered, while a well-supported event in the same fixture is recovered exactly as before.

### Tests for User Story 1 ⚠️

> Write these tests FIRST, ensure they FAIL before implementation

- [X] T021 [P] [US1] Unit test: an event whose only candidate has `ocr_confidence` below `ocr_confidence_low` is `UNRESOLVED` and `recovery_eligible=False`, in `tests/unit/test_metadata_alignment.py`
- [X] T022 [P] [US1] Unit test: an event whose top-ranked candidate would violate chronological order falls through to its next-ranked candidate (if any passes) or becomes `UNRESOLVED` (if none do) — never silently accepts the ordering-violating one, same file
- [X] T023 [P] [US1] Unit test: an event with strong OCR quality, consistent score-state, and preserved ordering is classified `HIGH` and remains `recovery_eligible=True` — the no-regression case (spec FR-016), same file
- [X] T024 [P] [US1] Unit test: `recovery.py`'s `find_recovery_candidates()` and `recover_events()` require **zero code changes** — existing `tests/unit/test_metadata_recovery.py` and `tests/contract/test_metadata_recovery_contract.py` pass unmodified against the new `MatchAlignmentEvidence` shape (regression check, run as-is, no new assertions needed beyond confirming green)
- [X] T025 [US1] Integration test: reproduce this feature's own originating bug fix against the real `ww_vs_pf.sqlite` fixture — the 6 previously out-of-order recovered events (documented in spec.md's Input) are no longer written as `source='METADATA'` events at their old, wrong timestamps when `cvip validate ww_vs_pf --recover` runs, in `tests/integration/test_metadata_validation_real_dataset.py`

### Implementation for User Story 1

- [X] T026 [US1] Update `tests/contract/test_metadata_alignment_contract.py`'s existing `recovery_eligible` assertions to reflect the validation-gated meaning (013's original contract text superseded per contracts/anchor_validation_contract.md's "Updated Stage 2 postcondition") (depends on T019)
- [X] T027 [US1] Confirm (no code expected) `orchestrator.py`'s `validate()` and `cli.py`'s `--recover` wiring require no changes — both already operate on `recovery_eligible` indirectly via `recovery.py`, which is untouched; add a one-line comment in `orchestrator_validate_contract.md` era code only if a gap is found

**Checkpoint**: User Story 1 is fully functional and independently testable — `cvip validate --recover` no longer inserts a wrongly-timestamped event, on both synthetic fixtures and the real match that surfaced the bug.

---

## Phase 4: User Story 2 - Rejected/Unresolved Events Come With a Clear Reason (Priority: P2)

**Goal**: For any event not recovered, a user can read a specific, human-readable reason — best candidate considered, its OCR quality, score-state result, ordering result — without inspecting raw database tables.

**Independent Test**: Run validation on a fixture with at least one `UNRESOLVED` event and one `LOW`-confidence event. Confirm the printed/written report names the best-tried candidate and states a specific rejection reason for each, distinguishing "no candidate existed" from "a candidate existed but was rejected."

### Tests for User Story 2 ⚠️

- [X] T028 [P] [US2] Unit test: `AnchorValidationSignals.reason` is populated for both an accepted candidate and a rejected/best-tried candidate, combining all four signal verdicts into one human-readable string, in `tests/unit/test_anchor_validation.py`
- [X] T029 [P] [US2] Unit test: `analyze_accuracy()`'s `missed_events` (013's existing field) still includes `UNRESOLVED` events, and each such entry is now traceable back to its `MatchAlignmentEvidence.validation_signals`/`rejected_candidates` for reason detail, in `tests/unit/test_metadata_validation.py`
- [X] T030 [P] [US2] Unit test: for an event with an empty candidate tuple (no reading found at all), `validation_signals is None` and the report distinguishes this from a populated-but-rejected case (spec User Story 2, Acceptance Scenario 3), same file

### Implementation for User Story 2

- [X] T031 [US2] Extend `cli.py`'s `AccuracyReport` output formatting to print, for every non-recovered event, its best-tried candidate's OCR confidence, score-state verdict, ordering verdict, and `reason` string (depends on T028, T029, T030; no orchestrator.py change expected — this is presentation over already-computed data)
- [X] T032 [US2] Unit test: `cvip validate`'s CLI output includes the per-event diagnostic detail for a fixture with a rejected candidate (orchestrator mocked to return a known `AccuracyReport`), in `tests/unit/test_cli_validate.py`

**Checkpoint**: User Stories 1 AND 2 both work independently — recovery is correct, and every non-recovered event is explainable.

---

## Phase 5: User Story 3 - Run-Level Trust Summary (Priority: P3)

**Goal**: A single validation run reports total metadata events, anchored counts by confidence tier, unresolved count, and ordering-violation counts (detected and prevented), without the user needing to query the database.

**Independent Test**: Run validation end-to-end on any fixture with a mix of outcomes; confirm the printed summary's counts match a hand-computed expectation, and that at least one ordering violation the engine caught is reflected in `ordering_violations_prevented`.

### Tests for User Story 3 ⚠️

- [X] T033 [P] [US3] Contract test: `summarize()`'s postcondition — `anchored_high_confidence + anchored_medium_confidence + anchored_low_confidence + unresolved_count == len(evidence)`, in `tests/contract/test_anchor_validation_contract.py`
- [X] T034 [P] [US3] Unit test: `summarize()` counts `ordering_violations_detected` (every rejected candidate with an ordering `VIOLATION` verdict, anywhere in the try sequence) versus `ordering_violations_prevented` (only the subset that were rank-0, i.e. would have been silently accepted under 013's original unconditional-commit behavior), in `tests/unit/test_anchor_validation.py`
- [X] T035 [P] [US3] Unit test: `AccuracyReport`'s new additive fields (`anchored_high_confidence`, `anchored_medium_confidence`, `anchored_low_confidence`, `unresolved_count`, `ordering_violations_detected`, `ordering_violations_prevented`) are populated correctly and existing fields (`ground_truth_total`, `true_positives`, etc.) are unchanged in value for a fixture carried over from 013's own test suite (no-regression check), in `tests/unit/test_metadata_validation.py`
- [X] T036 [P] [US3] Unit test: `unresolved_count` is distinct from `false_negatives_no_signal` — a fixture with "signal existed but was untrustworthy" produces a nonzero `unresolved_count` while `false_negatives_no_signal` counts only genuine no-signal cases, same file

### Implementation for User Story 3

- [X] T037 [US3] Implement `anchor_validation.py`'s `summarize(evidence)` per contracts/anchor_validation_contract.md (depends on T033, T034)
- [X] T038 [US3] Extend `AccuracyReport` in `src/cvip/metadata/validation_models.py` with the six new additive fields per data-model.md (depends on T037)
- [X] T039 [US3] Wire `summarize()` into `validation.py`'s `analyze_accuracy()`, folding its result into the returned `AccuracyReport` per research.md Decision 9 (depends on T035, T036, T038)
- [X] T040 [US3] Extend `diagnostics.py`'s existing `metadata.validate` diagnostics record with the same new operational metrics (spec FR-010), following the established per-module diagnostics-record convention (depends on T039)
- [X] T041 [US3] Extend `cli.py`'s `AccuracyReport` output formatting to print the run-level summary counts (depends on T038)

**Checkpoint**: All three user stories independently functional.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Improvements and gates that affect the whole feature, not any single story

- [X] T042 [P] Run all three [quickstart.md](./quickstart.md) scenarios manually against the real `ww_vs_pf`/`platinum_final_3rd` databases and record pass/fail results
- [X] T043 [P] Add docstrings to all public functions/classes in `src/cvip/metadata/anchor_validation.py` and `anchor_validation_models.py`
- [X] T044 Re-run `tests/integration/test_metadata_validation_real_dataset.py`'s existing 013-era assertions (the already-established recall figure against the real Wild Wanderers vs Phoenix Firehawks data) and confirm they still pass — this feature must not change recall/precision computation, only which events are auto-recoverable
- [X] T045 Run the full test suite (`pytest`) and confirm all tests pass, including every prior feature's existing tests (regression check across the whole repo)
- [X] T046 Run the constitution-mandated coverage gate: `pytest --cov=src/cvip/metadata --cov-fail-under=100`. This feature is not complete until this passes — add targeted tests for any branch it reports as uncovered (Constitution Principle VII)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories
- **User Story 1 (Phase 3)**: Depends on Foundational only
- **User Story 2 (Phase 4)**: Depends on Foundational only — reads fields Foundational already populates (`validation_signals`, `rejected_candidates`); does not depend on US1's own tasks, though both extend `cli.py`'s output formatting so should be sequenced to avoid touching the same lines simultaneously
- **User Story 3 (Phase 5)**: Depends on Foundational only — same file-overlap caveat as US2 for `cli.py`
- **Polish (Phase 6)**: Depends on all three user stories being complete

### Within Each User Story

- Tests are written first and must fail before implementation begins
- US1: test the gating behavior (T021-T025) → confirm/update the one contract assertion (T026) → confirm no unwanted ripple into `recovery.py`/`orchestrator.py` (T027)
- US2: test reason/signal surfacing (T028-T030) → CLI presentation (T031) → CLI test (T032)
- US3: test `summarize()`'s postconditions (T033-T036) → implement `summarize()` (T037) → extend `AccuracyReport` (T038) → wire into `analyze_accuracy()` (T039) → extend diagnostics (T040) → CLI presentation (T041)

### Parallel Opportunities

- T001, T002 (Setup) can run in parallel
- T003, T004, T005 (Foundational config/models) can run in parallel — different files
- T007-T015 (all engine-level contract/unit tests) can run in parallel once T004-T006 land
- T021-T025 (US1 tests) can run in parallel
- T028-T030 (US2 tests) can run in parallel
- T033-T036 (US3 tests) can run in parallel
- T042, T043 (Polish) can run in parallel
- US1, US2, and US3 each depend only on Foundational, so their *test-writing* can proceed fully in parallel across all three stories; their `cli.py`-touching implementation tasks (T031, T041) should be sequenced relative to each other to avoid a merge conflict on the same output-formatting function

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (blocks everything else — this is where the actual bug gets fixed)
3. Complete Phase 3: User Story 1
4. **STOP and VALIDATE**: run quickstart.md Scenario 1 against real `ww_vs_pf` data; confirm the 6 previously-wrong recovered events no longer appear at their old timestamps
5. This alone delivers the feature's core value — the correctness fix — even before the richer diagnostics/summary reporting (US2/US3) exist

### Incremental Delivery

1. Setup + Foundational → the validation engine exists and is wired into `recovery_eligible`
2. Add User Story 1 → validate independently (the correctness fix itself, provable against real data)
3. Add User Story 2 → validate independently (rejection reasons become visible)
4. Add User Story 3 → validate independently (run-level trust summary becomes visible)
5. Phase 6: Polish, including the full quickstart re-run and the mandatory 100% coverage gate on `src/cvip/metadata`

---

## Notes

- [P] tasks touch different files (or are independent test-writing tasks with no unmet dependencies) and have no unmet dependencies
- [Story] label maps each task to its user story for traceability back to spec.md
- Commit after each task or logical group
- Stop at any checkpoint to validate a story independently before moving on
- **The engine is Foundational, not US1-only**, because US2 and US3 both need its output (`validation_signals`, `rejected_candidates`, tier classification) already populated to do their own work — this mirrors 013's own precedent for its shared Stages 1-2.
- **Zero changes to `recovery.py`, `recovery_models.py`, `enrichment.py`, `enrichment_models.py`** is itself a design guarantee this task list preserves (research.md Decision 8) — T024 exists specifically to prove that guarantee holds, not to add new behavior to those files.
- **FR-011 (fully generic, no match-specific logic)**: enforced structurally — every task operates on `config/default.yaml` thresholds, `scoreboard_readings` columns, and already-accepted-anchor state, never a hardcoded team/match/over value. The real `ww_vs_pf`/`platinum_final_3rd` datasets are used only as **test fixtures** proving the generic logic behaves correctly on real data, exactly as 013's own T059 used real data as a fixture, not as a special case in the implementation itself.
