---

description: "Task list template for feature implementation"
---

# Tasks: Robust Innings Transition Detection

**Input**: Design documents from `/specs/015-innings-transition-detection/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/innings_transition_contract.md](./contracts/innings_transition_contract.md), [quickstart.md](./quickstart.md)

**Tests**: Included — Constitution Principle VII requires contract tests at module boundaries, tests written before implementation, and 100% coverage on critical paths (enforced by T044). This module is explicitly a critical path per plan.md's Constitution Check: it gates which team's footage every downstream consumer thinks it's looking at.

**Organization**: Tasks are grouped by user story (from spec.md) to enable independent implementation and testing of each story.

**Note on shared engine**: The `InningsTracker` state machine itself (candidate evaluation, all four signal checks, protected-baseline bookkeeping, max-segments bound) is built once, in Foundational — all three user stories exercise the SAME decision logic, just emphasizing different postconditions of it (US1: correct segment count; US2: no cascading false positives; US3: the hard bound never exceeded). This mirrors the precedent both `specs/013` and `specs/014` set for their own shared engines.

**Note on call-site migration**: The three existing call sites (`scoreboard_ocr.py`, `events/detection.py`, `orchestrator.py`) are migrated to consume the shared tracker as part of Foundational too, since none of the three user stories is meaningfully testable end-to-end without at least the buggy call site (`orchestrator.py`, the one populating `scoreboard_readings.innings`) actually using the new engine. Migrating all three together (rather than one now, two later) avoids leaving two of the three copies drifted out of sync with the fix, which is the exact bug class this feature exists to close.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)

## Path Conventions

Single project, per plan.md Project Structure: two new files in `src/cvip/video/`, additive/internal-only modifications to three existing files (`video/scoreboard_ocr.py`, `events/detection.py`, `orchestrator.py`), one additive config block, tests in the existing `tests/{contract,unit,integration}/`.

---

## Phase 1: Setup

- [X] T001 [P] Create empty `src/cvip/video/innings_transition.py` and `src/cvip/video/innings_transition_models.py` module files per plan.md Source Code layout
- [X] T002 [P] Create empty test file placeholders: `tests/contract/test_innings_transition_contract.py`, `tests/unit/test_innings_transition.py`, `tests/integration/test_innings_transition_real_dataset.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The shared `InningsTracker` engine, its config, and migrating all three existing call sites onto it

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T003 [P] Add the `innings_transition` config block (`max_segments`, `max_runs_for_new_segment`, `max_wickets_for_new_segment`, `min_consecutive_confirmations_raw`/`_collapsed`, `low_confidence_threshold`, `low_confidence_confirmation_multiplier`) to `config/default.yaml` per data-model.md's Configuration Additions and research.md Decision 11 — same "reasoned calibration, revisit if wrong" comment style as this file's existing calibrated blocks; explicitly note `max_runs_for_new_segment: 20` is carried over unchanged from the existing `_NEW_INNINGS_MAX_RUNS` constant, with its own prior real-incident rationale (PLATINUM CUP FINAL) preserved in the comment
- [X] T004 [P] Implement `InningsDecisionOutcome` enum and `InningsTransitionSignals`, `InningsTransitionDecision`, `InningsTransitionConfig` frozen dataclasses per data-model.md, in `src/cvip/video/innings_transition_models.py`
- [X] T005 [US-shared] Contract test: `InningsTracker.observe()` never raises for well-formed input (missing runs/wickets → `NOT_A_CANDIDATE`, per contracts/innings_transition_contract.md step 1), in `tests/contract/test_innings_transition_contract.py`
- [X] T006 [P] Contract test: determinism — two independently-constructed trackers fed the identical reading sequence produce byte-identical `InningsTransitionDecision` sequences (spec FR-013), same file
- [X] T007 [P] Contract test: `current_segment` never exceeds `config.max_segments` for an adversarially-constructed sequence of several well-separated, fully-corroborated low-score runs (spec SC-006) — every candidate past the bound is `REJECTED_MAX_SEGMENTS_REACHED`, not silently dropped, same file
- [X] T008 [P] Contract test: the trusted baseline is never set from a `REJECTED_*` decision, verified by constructing a sequence with an implausible candidate followed by a genuinely normal continuing reading, and asserting the normal reading is judged against the pre-candidate baseline, not the rejected one (research.md Decision 8), same file
- [X] T009 [P] Unit test: `reset_plausible` evaluator — true only when BOTH runs and wickets land at or under their configured ceilings simultaneously (research.md Decision 5); a low-but-nonzero-runs-with-high-wickets reading (or vice versa) must NOT qualify, in `tests/unit/test_innings_transition.py`
- [X] T010 [P] Unit test: `over_ball_reset` evaluator — true only when over/ball are also near the start; a runs/wickets-plausible-but-over/ball-mid-innings reading is rejected via `REJECTED_NO_OVER_BALL_RESET` (research.md Decision 6, directly reversing specs/007's prior rejected assumption — reference that supersession in the test docstring), same file
- [X] T011 [P] Unit test: consecutive-confirmation counting — an isolated single qualifying reading surrounded by normal readings never accepts (`REJECTED_INSUFFICIENT_PERSISTENCE`); a run of `min_consecutive_confirmations` qualifying readings in a row does accept; a qualifying run broken by one normal reading in the middle resets the count to zero, not preserved (research.md Decision 4), same file
- [X] T012 [P] Unit test: confidence scaling — a low-confidence candidate run needs more consecutive confirmations than a high-confidence one of the same length to accept (research.md Decision 7), same file
- [X] T013 [P] Unit test: reproduces the real incident directly — feed the exact real `ww_vs_pf` reading values at t=3208s (runs=5, wickets=2) and t=4048s (runs=7, wickets=3) as isolated single readings surrounded by normal Wild Wanderers continuation data; assert neither is ever accepted, and the real transition reading (runs≈6, wickets≈1, over≈1.3, sustained) IS accepted, same file
- [X] T014 Implement `InningsTracker` (`__init__`, `observe`, `current_segment`) and its internal signal-evaluation helpers per contracts/innings_transition_contract.md's 8-step algorithm, in `src/cvip/video/innings_transition.py` (depends on T004-T013)
- [X] T015 [US-shared] Migrate `src/cvip/video/scoreboard_ocr.py`'s `_validate_reading` (lines 562-569): replace the inline `innings_transition` boolean with a call into a shared `InningsTracker` instance the module now owns per extraction run, using `outcome == ACCEPTED` in place of the old boolean — external return shape and every other validation rule unchanged (depends on T014)
- [X] T016 [P] Unit test: `scoreboard_ocr.py`'s existing false-transition test (`test_recovery_jump_after_a_false_innings_transition_is_not_blocked`, currently at test_scoreboard_ocr_validation.py:498-527) still passes against the new tracker-backed logic — update the test only if its own construction needs adapting to the new call, never its asserted behavior, in `tests/unit/test_scoreboard_ocr_validation.py`
- [X] T017 [US-shared] Migrate `src/cvip/events/detection.py`'s `EventDetectionRunner._process_comparison` (lines 184-207): replace the inline `current.runs < previous.runs and current.wickets < previous.wickets` check with a call into a shared `InningsTracker` instance the runner now owns, fed the collapsed `ScoreState` stream with the `_collapsed` confirmation-count config; `self._innings`/`self._innings_transitions_detected` populated from the tracker (depends on T014)
- [X] T018 [P] Unit test: `events/detection.py`'s existing innings-transition test (`test_innings_transition_heuristic_suppresses_events_and_resets_tracking`, currently at test_event_detection_rules.py:210-221) still passes against the new tracker-backed logic, in `tests/unit/test_event_detection_rules.py`
- [X] T019 [US-shared] Migrate `src/cvip/orchestrator.py`'s `_tag_readings_with_innings` (lines 149-166): becomes a thin adapter constructing one `InningsTracker` (with the `_raw` confirmation-count config) and tagging each `_ScoreboardReadingWithInnings` with `decision.segment`; remove the module-level `_NEW_INNINGS_MAX_RUNS` constant (superseded by config) (depends on T014)
- [X] T020 [P] Unit test: `orchestrator.py`'s existing `_tag_readings_with_innings` tests (`test_tag_readings_with_innings_increments_on_genuine_transition`, `test_tag_readings_with_innings_ignores_mid_innings_ocr_noise`, `test_tag_readings_with_innings_boundary_at_threshold`, currently at test_orchestrator_analyze.py:460-493) still pass against the new tracker-backed adapter, in `tests/unit/test_orchestrator_analyze.py`

**Checkpoint**: Foundation ready — the shared engine exists, is proven against its own contract, and all three call sites consume it identically. User story work can now begin (largely already exercised by the above, but each story below adds its own explicit end-to-end proof).

---

## Phase 3: User Story 1 - A Match Is Never Split Into More Segments Than It Actually Has (Priority: P1) 🎯 MVP

**Goal**: On the real match that surfaced this defect, analysis produces exactly two segments, with the genuine second-innings start correctly labeled segment 2.

**Independent Test**: Run the new `_tag_readings_with_innings` against the real `ww_vs_pf` raw reading sequence; confirm exactly 2 distinct segment values, and the real transition (t≈6171s) is labeled 2, not 4.

### Tests for User Story 1 ⚠️

- [X] T021 [P] [US1] Integration test: reproduces this feature's own originating bug fix against the real `ww_vs_pf` raw OCR data (same CSV/JSON fixture source `specs/014-anchor-validation`'s own integration test already uses, per quickstart.md Scenario 1) — exactly 2 segments result, and the real transition at t≈6171s is labeled segment 2, in `tests/integration/test_innings_transition_real_dataset.py`
- [X] T022 [P] [US1] Integration test: the two previously-false transitions (t≈3208s, t≈4048s) are NOT accepted — their recorded decisions are `REJECTED_IMPLAUSIBLE_RESET` or `REJECTED_INSUFFICIENT_PERSISTENCE` with a specific reason string, same file
- [X] T023 [P] [US1] Integration test: no-regression check against `platinum_final_3rd`'s real data (quickstart.md Scenario 2) — still exactly 2 segments, transition lands at the same real point as before this feature, same file

### Implementation for User Story 1

- [X] T024 [US1] Run quickstart.md Scenarios 1-2 manually against the real databases/fixtures and record pass/fail results (no new code expected if Foundational is correct — this is the end-to-end proof, not new implementation)

**Checkpoint**: User Story 1 is fully functional and independently provable — the real bug (5 segments instead of 2) is fixed, on real data, without regressing an already-correct match.

---

## Phase 4: User Story 2 - One Misread Frame Never Compounds Into Multiple Errors (Priority: P2)

**Goal**: A rejected candidate never becomes the reference point for judging subsequent readings, so one bad frame cannot directly cause a second bad decision.

**Independent Test**: Feed a sequence with one implausible reading immediately followed by readings consistent with the innings genuinely continuing unchanged; confirm the implausible reading was never used as a baseline for anything after it.

### Tests for User Story 2 ⚠️

- [X] T025 [P] [US2] Unit test: directly reproduces the real cascade mechanism — a reading shaped like t=3208s's false transition, immediately followed by a reading shaped like t=4048s's, with NORMAL Wild Wanderers continuation readings in between (not present in the original bug, added here specifically to prove containment) — assert the second candidate's rejection reasoning references the correct (pre-first-candidate) baseline, not the first (rejected) candidate's values, in `tests/unit/test_innings_transition.py`
- [X] T026 [P] [US2] Unit test: a rejected candidate's own runs/wickets/over/ball values never appear in any LATER decision's `InningsTransitionSignals` as the comparison baseline (inspect the `reason` string / any exposed baseline reference), same file

### Implementation for User Story 2

- [X] T027 [US2] No new implementation expected — User Story 2's guarantee is Foundational's own protected-baseline postcondition (T014, contracts/innings_transition_contract.md's step-3/8-only baseline update rule). If T025/T026 fail, fix `InningsTracker`'s baseline-update logic before proceeding (depends on T014)

**Checkpoint**: User Stories 1 AND 2 both proven — segments are correct, and the specific cascading-failure mechanism from the real incident is closed.

---

## Phase 5: User Story 3 - A Match Can Never Be Segmented Into More Parts Than Are Structurally Possible (Priority: P3)

**Goal**: However noisy the input, the reported segment count never exceeds the configured maximum, and additional transition-like evidence beyond the bound is visibly disregarded, not silently dropped.

**Independent Test**: Feed a sequence engineered to trigger more transition-like patterns than the match format allows; confirm the segment count never exceeds the configured maximum and the excess candidates are recorded as `REJECTED_MAX_SEGMENTS_REACHED`.

### Tests for User Story 3 ⚠️

- [X] T028 [P] [US3] Unit test: a sequence with three well-separated, fully-corroborated, sustained low-score runs (each individually strong enough to be `ACCEPTED` in isolation) against `max_segments=2` results in exactly 2 accepted transitions and the third recorded as `REJECTED_MAX_SEGMENTS_REACHED`, in `tests/unit/test_innings_transition.py`
- [X] T029 [P] [US3] Unit test: `max_segments` is read from `InningsTransitionConfig`, not hardcoded — a config with `max_segments=1` rejects even a single, otherwise-fully-qualifying transition, same file

### Implementation for User Story 3

- [X] T030 [US3] No new implementation expected — User Story 3's guarantee is Foundational's own step-7 bound check (T014). If T028/T029 fail, fix `InningsTracker`'s bound enforcement before proceeding (depends on T014)

**Checkpoint**: All three user stories independently proven.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T031 [P] Run all four [quickstart.md](./quickstart.md) scenarios manually and record pass/fail results
- [X] T032 [P] Add docstrings to all public functions/classes in `src/cvip/video/innings_transition.py` and `innings_transition_models.py`, including explicit references to which prior spec decisions (specs/005 FR-014, specs/007 research.md Decision 5, specs/012 research.md Decision 9) this feature supersedes
- [X] T033 Update `specs/005-scoreboard-ocr/spec.md`, `specs/007-event-detection/research.md`, and `specs/012-pipeline-orchestrator-cli/research.md` with a short superseded-by note pointing at this feature, per this project's own convention of not leaving stale, contradicted design rationale undocumented (mirrors how `alignment_models.py`'s docstring in specs/014 documents its own extension of specs/013)
- [X] T034 Run the full test suite (`pytest`) and confirm all tests pass, including every prior feature's existing tests — this specifically must show the ALREADY-EXISTING innings-transition tests in `test_orchestrator_analyze.py`, `test_scoreboard_ocr_validation.py`, and `test_event_detection_rules.py` still pass (T016/T018/T020's own point), proving this is a genuine behind-the-scenes replacement, not a breaking change to documented behavior
- [X] T035 Run the constitution-mandated coverage gate: `pytest --cov=src/cvip/video/innings_transition.py --cov=src/cvip/video/innings_transition_models.py --cov-fail-under=100`. Add targeted tests for any branch reported as uncovered (Constitution Principle VII)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories (the shared engine and all three call-site migrations happen here, since none of the three stories is meaningfully testable without at least the buggy call site already migrated)
- **User Story 1 (Phase 3)**: Depends on Foundational only — its own tests are largely a real-data restatement of what Foundational's unit tests already proved synthetically
- **User Story 2 (Phase 4)**: Depends on Foundational only
- **User Story 3 (Phase 5)**: Depends on Foundational only
- **Polish (Phase 6)**: Depends on all three user stories being complete

### Within Each Phase

- Tests are written first and must fail before implementation begins (T005-T013 before T014; T016/T018/T020 are existing-test-preservation checks run immediately after each migration task T015/T017/T019)
- T014 (the engine) blocks T015, T017, T019 (all three call-site migrations) — they cannot be adapted to consume something that doesn't exist yet
- T015/T017/T019 (the three migrations) have no dependency on each other and can proceed in parallel once T014 lands

### Parallel Opportunities

- T001, T002 (Setup) can run in parallel
- T003, T004 (Foundational config/models) can run in parallel — different files
- T005-T013 (all engine-level contract/unit tests) can run in parallel once T004 lands
- T015, T017, T019 (the three call-site migrations) can run in parallel once T014 lands — different files, no shared dependency between them
- T021-T023 (US1 integration tests), T025-T026 (US2 tests), T028-T029 (US3 tests) can each run in parallel within their own story
- T031, T032 (Polish) can run in parallel

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (this is where the actual fix happens — the engine plus all three migrations)
3. Complete Phase 3: User Story 1
4. **STOP and VALIDATE**: run quickstart.md Scenarios 1-2 against real `ww_vs_pf`/`platinum_final_3rd` data; confirm exactly 2 segments on the buggy match and no change on the already-correct one
5. This alone delivers the feature's core value — the real defect is fixed and proven on the exact data that surfaced it

### Incremental Delivery

1. Setup + Foundational → the engine exists, all three call sites consume it, existing tests still pass
2. Add User Story 1 → validate independently against real data (the correctness fix itself)
3. Add User Story 2 → validate independently (cascading-failure containment made explicit)
4. Add User Story 3 → validate independently (the hard structural bound made explicit)
5. Phase 6: Polish, including the full quickstart re-run, the prior-spec supersession notes, and the mandatory 100% coverage gate

---

## Notes

- [P] tasks touch different files (or are independent test-writing tasks with no unmet dependencies) and have no unmet dependencies
- [Story] label maps each task to its user story for traceability back to spec.md
- Commit after each task or logical group
- Stop at any checkpoint to validate a story independently before moving on
- **All three call-site migrations happen in Foundational, not spread across the user stories** — because the bug this feature fixes is specifically that three copies drifted apart; leaving any one of them un-migrated would recreate exactly that risk.
- **Zero external behavior change** for `cvip analyze`'s CLI surface (spec FR-014) is a design guarantee this task list preserves structurally — T016/T018/T020 exist specifically to prove existing, already-documented behavior at each of the three call sites is unchanged, not to add new behavior.
- **FR-009 (no new OCR-extraction scope)**: enforced structurally — every task operates only on `runs`/`wickets`/`over_number`/`ball_in_over`/confidence fields already present on `ScoreboardSample`/`ScoreState` today; no task adds a new OCR-parsing capability (team name, target text remain explicitly out of scope per spec.md's own Assumptions).
