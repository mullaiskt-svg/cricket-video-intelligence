---

description: "Task list template for feature implementation"
---

# Tasks: OCR Timeline Smoother

**Input**: Design documents from `/specs/006-ocr-timeline-smoother/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/ocr_timeline_smoother_contract.md](./contracts/ocr_timeline_smoother_contract.md), [quickstart.md](./quickstart.md)

**Tests**: Included — constitution Principle VII (Test-First Development) requires contract tests at module boundaries, tests written before implementation, and 100% coverage on critical paths (enforced by T040).

**Organization**: Tasks are grouped by user story (from spec.md) to enable independent implementation and testing of each story.

**Note on shared infrastructure**: This feature reuses `src/cvip/common/diagnostics.py`'s emitter and `pyproject.toml`'s existing pytest/coverage configuration — no new fixture, diagnostics module, or test-runner config is created here. Unlike every prior module, this feature depends on **no video fixtures at all** — its sole input is Scoreboard OCR's (`specs/005-scoreboard-ocr/`) `ScoreboardOcrResult`, and every test builds synthetic `ScoreboardOcrResult`/`ScoreboardSample` instances directly in Python (plan.md Project Structure).

**Note on dependencies**: No new pip package is introduced by this feature (research.md) — the first module on this platform with zero new external dependencies.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)

## Path Conventions

Single project, per plan.md Project Structure: new files in `src/cvip/video/` (alongside Video Loader, the Frame Extraction Service, Scene Detection, Replay Detection, and Scoreboard OCR), tests in the existing `tests/{contract,integration,unit,benchmark}/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization for this feature's new files only — test directories, pytest config, and diagnostics infrastructure already exist from the five prior features

- [X] T001 [P] Create `src/cvip/video/{ocr_timeline_smoother_models.py,ocr_timeline_smoother_errors.py,ocr_timeline_smoother.py}` as empty modules per plan.md Source Code layout
- [X] T002 [P] Create empty test file placeholders: `tests/contract/test_ocr_timeline_smoother_contract.py`, `tests/integration/test_ocr_timeline_smoother_e2e.py`, `tests/unit/test_ocr_timeline_smoother_algorithm.py`, `tests/benchmark/test_ocr_timeline_smoother_performance.py`
- [X] T003 [P] Confirm `pyproject.toml`'s existing `pytest` `testpaths` and `--cov=src/cvip/video` coverage scope already cover this feature's new files (same subpackage as the five prior features) — no config changes expected; document in a one-line comment if any gap is found

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core types every user story depends on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T004 [P] Implement the `OCRTimelineSmootherFailureReason` enum (`INVALID_INPUT`, `INVALID_SMOOTHING_CONFIGURATION`) and an `OCRTimelineSmootherError` exception carrying it, per [contracts/ocr_timeline_smoother_contract.md](./contracts/ocr_timeline_smoother_contract.md) and [data-model.md](./data-model.md), in `src/cvip/video/ocr_timeline_smoother_errors.py`
- [X] T005 [P] Implement `OCRTimelineSmootherRequest`, the `SmoothingResolution` enum (`PASSED_THROUGH`, `HELD_FORWARD_UNUSABLE`, `HELD_FORWARD_OUTLIER`), `SmoothingEvidence`, `CleanedScoreboardSample`, and `OCRTimelineSmootherResult` per [data-model.md](./data-model.md) as frozen (immutable) dataclasses with plain, self-contained field types (no references to run-internal state) in `src/cvip/video/ocr_timeline_smoother_models.py`
- [X] T006 Implement a diagnostics-building helper (module_name `"video.ocr_timeline_smoother"`) reusing `src/cvip/common/diagnostics.py`'s `ExecutionDiagnostics`/`DiagnosticsTracker` (no new diagnostics module) in `src/cvip/video/ocr_timeline_smoother.py` (depends on T004, T005)

**Checkpoint**: Foundation ready — user story implementation can now begin

---

## Phase 3: User Story 1 - Produce a fully diffable, gap-free scoreboard timeline (Priority: P1) 🎯 MVP

**Goal**: Given a `ScoreboardOcrResult`, `smooth_timeline()` produces exactly one `CleanedScoreboardSample` (plus an internal `SmoothingEvidence` record) per input sample — filling every unusable-flagged gap and discounting every isolated single-sample outlier by holding forward the most recently established known-good reading, never fabricating a value via interpolation, and leaving an honest "no reliable value yet" for a leading gap.

**Independent Test**: Run the smoother against a constructed raw timeline containing an unusable stretch, an isolated single-sample outlier, a leading gap, a trailing gap, and a genuine multi-sample change, and confirm each case is handled exactly as spec.md describes.

### Tests for User Story 1 ⚠️

> Write these tests FIRST, ensure they FAIL before implementation

- [X] T007 [P] [US1] Contract test asserting `smooth_timeline()` returns an `OCRTimelineSmootherRunner` matching [contracts/ocr_timeline_smoother_contract.md](./contracts/ocr_timeline_smoother_contract.md)'s shape, and that a missing/malformed `scoreboard_ocr_result` yields `INVALID_INPUT` and an invalid `outlier_window` yields `INVALID_SMOOTHING_CONFIGURATION`, both before any sample is processed, in `tests/contract/test_ocr_timeline_smoother_contract.py`
- [X] T008 [P] [US1] Unit test: a stretch of samples flagged unusable by Scoreboard OCR (`ocr_confidence = 0` or `parse_confidence = 0`) is replaced in the cleaned output with the most recently established known-good reading's field values (FR-003, US1 AS1), in `tests/unit/test_ocr_timeline_smoother_algorithm.py`
- [X] T009 [P] [US1] Unit test: a single usable sample whose core scoring tuple disagrees with `outlier_window` nearest usable neighbors on both sides (which agree with each other) is treated as an outlier and replaced with the consensus value (FR-004, US1 AS2, research.md Decisions 1-2), in `tests/unit/test_ocr_timeline_smoother_algorithm.py`
- [X] T010 [P] [US1] Unit test: two or more consecutive usable samples agreeing on a new divergent core scoring tuple are NOT flagged as outliers — each is passed through with its own field values (spec.md Edge Cases, research.md Decision 1), in `tests/unit/test_ocr_timeline_smoother_algorithm.py`
- [X] T011 [P] [US1] Unit test: a leading stretch of unusable samples with no known-good reading established yet is left with all-`null` cleaned fields, never a fabricated value (FR-006, US1 AS3), in `tests/unit/test_ocr_timeline_smoother_algorithm.py`
- [X] T012 [P] [US1] Unit test: a trailing stretch of unusable samples at the very end of the timeline receives the same hold-forward treatment as a mid-timeline gap, with no special-casing (spec.md Edge Cases), in `tests/unit/test_ocr_timeline_smoother_algorithm.py`
- [X] T013 [P] [US1] Unit test: a raw timeline with no unusable samples and no outliers produces a cleaned output identical to the input's field values, sample for sample (US1 AS4), in `tests/unit/test_ocr_timeline_smoother_algorithm.py`
- [X] T014 [P] [US1] Unit test: the cleaned output has exactly one entry per input sample, in the same order, at the same timestamps, for a timeline mixing gaps/outliers/genuine changes (US1 AS5, FR-007), in `tests/unit/test_ocr_timeline_smoother_algorithm.py`
- [X] T015 [P] [US1] Unit test asserting the outlier-detection window boundary guard: a usable sample near the start or end of the sequence with fewer than `outlier_window` usable neighbors available on one side is never flagged as an outlier (research.md Decision 1), in `tests/unit/test_ocr_timeline_smoother_algorithm.py`
- [X] T016 [P] [US1] Unit test asserting no numeric interpolation ever occurs: a gap between two known-good readings with different `runs` values is filled with the earlier reading's exact value throughout the gap, never an averaged or interpolated number (FR-005), in `tests/unit/test_ocr_timeline_smoother_algorithm.py`
- [X] T017 [P] [US1] Unit test asserting `SmoothingEvidence.resolution` is correctly `PASSED_THROUGH`, `HELD_FORWARD_UNUSABLE`, or `HELD_FORWARD_OUTLIER` for each of the three sample kinds, and `SmoothingEvidence.original_sample` preserves the sample's own pre-smoothing field values and confidence fields for comparison (FR-008), in `tests/unit/test_ocr_timeline_smoother_algorithm.py`
- [X] T018 [P] [US1] Integration test: smoothing a synthetic timeline combining an unusable stretch, an isolated outlier, a leading gap, and a genuine multi-sample change all in one sequence produces the expected cleaned output end-to-end, in `tests/integration/test_ocr_timeline_smoother_e2e.py`

### Implementation for User Story 1

- [X] T019 [US1] Implement the "usable sample" classification helper (`ocr_confidence > 0.0 and parse_confidence > 0.0`, research.md Decision 4) in `src/cvip/video/ocr_timeline_smoother.py` (depends on T005)
- [X] T020 [US1] Implement the outlier-flagging pass: for each usable sample, locate its nearest `outlier_window` usable neighbors on each side (skipping unusable-flagged samples) and flag it as an outlier when both windows mutually agree on the core scoring tuple (`runs`, `wickets`, `over_number`, `ball_in_over`) while the sample itself disagrees (research.md Decisions 1-2) in `src/cvip/video/ocr_timeline_smoother.py` (depends on T019)
- [X] T021 [US1] Implement the Known-Good Tracker and the hold-forward fill pass: walk samples in order, emitting the tracker's fields (or all-`null`) for unusable/outlier-flagged samples and the sample's own fields (updating the tracker) otherwise, producing one `CleanedScoreboardSample` + `SmoothingEvidence` per sample (FR-003 through FR-006, FR-008) in `src/cvip/video/ocr_timeline_smoother.py` (depends on T020)
- [X] T022 [US1] Implement the `smooth_timeline()` factory function and the `OCRTimelineSmootherRunner` class, orchestrating the flag pass then the fill pass inside `run()` in `src/cvip/video/ocr_timeline_smoother.py` (depends on T006, T021)

**Checkpoint**: User Story 1 is fully functional and independently testable — every input sample yields exactly one cleaned sample via the two-pass flag-then-fill algorithm, with gaps and isolated outliers correctly discounted and genuine changes correctly preserved.

---

## Phase 4: User Story 2 - Produce a timeline usable by a later, separate module (Priority: P2)

**Goal**: The smoothing result's shape is fully self-contained (plain values, no references to run-internal state) and carries a source-video identifier, so Event Detection can consume it without any of this run's in-memory state (including the Known-Good Tracker and outlier-flag state) still existing.

**Independent Test**: Confirm the result's fields are plain, immutable values with no back-reference to the `OCRTimelineSmootherRunner` instance, and that `source_video_id` correctly identifies the analyzed video.

### Tests for User Story 2 ⚠️

- [X] T023 [P] [US2] Integration test: a completed `OCRTimelineSmootherResult`'s `source_video_id` matches `scoreboard_ocr_result.source_video_id` (FR-019, US2 AS2), in `tests/integration/test_ocr_timeline_smoother_e2e.py`
- [X] T024 [P] [US2] Unit test: `CleanedScoreboardSample` and `OCRTimelineSmootherResult` are frozen dataclasses — attempting to mutate a field after construction raises, and `OCRTimelineSmootherResult.samples` is a tuple, not a list (US2 AS1), in `tests/unit/test_ocr_timeline_smoother_algorithm.py`

### Implementation for User Story 2

- [X] T025 [US2] Review `src/cvip/video/ocr_timeline_smoother_models.py` and `src/cvip/video/ocr_timeline_smoother.py` to confirm `CleanedScoreboardSample`/`OCRTimelineSmootherResult` are self-contained (frozen, plain field types, no back-references to `OCRTimelineSmootherRunner` state, including the Known-Good Tracker and outlier-flag state) and fix any finding (depends on T005, T022)

**Checkpoint**: User Stories 1 AND 2 both work independently — correct gap-filling/outlier-discounting, plus a result shape safe to hand to a separate later process.

---

## Phase 5: User Story 3 - Complete quickly, and follow platform-standard operational behavior (Priority: P3)

**Goal**: Smoothing a full match's ~12,600 samples completes in under 1 minute, supports cooperative cancellation, and fails fast with one of the taxonomy's two specific reasons on every structural failure path — always emitting exactly one diagnostics record, including for a rejected input or configuration.

**Independent Test**: Run the smoother against a full match's worth of synthetic samples and confirm elapsed time stays under 1 minute; separately, force each of the taxonomy's failure conditions and confirm the matching specific reason plus exactly one diagnostics record; separately, confirm `.cancel()` stops a run cleanly.

### Tests for User Story 3 ⚠️

- [X] T026 [P] [US3] Benchmark test asserting smoothing a synthetic ~12,600-sample sequence (a full match's worth) completes in under 1 minute (SC-008), in `tests/benchmark/test_ocr_timeline_smoother_performance.py`
- [X] T027 [P] [US3] Integration test: a missing or structurally malformed `scoreboard_ocr_result` (`None`, or samples out of ascending-timestamp order) yields `INVALID_INPUT` before any sample is processed, with exactly one diagnostics record emitted (FR-012, FR-014), in `tests/integration/test_ocr_timeline_smoother_e2e.py`
- [X] T028 [P] [US3] Integration test: an `outlier_window` that is not a positive integer (`0`, negative, or non-int/bool) yields `INVALID_SMOOTHING_CONFIGURATION` before any sample is processed, with exactly one diagnostics record emitted (FR-013, FR-014) — independent of T027's case, in `tests/integration/test_ocr_timeline_smoother_e2e.py`
- [X] T029 [P] [US3] Integration test: calling `.cancel()` mid-run stops further sample processing and emits exactly one diagnostics record summarizing the partial run (FR-015), in `tests/integration/test_ocr_timeline_smoother_e2e.py`
- [X] T030 [P] [US3] Integration test asserting determinism (FR-016, SC-005): running the identical `OCRTimelineSmootherRequest` against the same input twice yields an identical ordered `samples` sequence, in `tests/integration/test_ocr_timeline_smoother_e2e.py`
- [X] T031 [P] [US3] Unit test asserting the diagnostics record contains every field FR-017 requires (total samples processed, held-forward-unusable count, held-forward-outlier count, no-reliable-value-yet count, processing duration) for a successful run, and that a rejected-input/rejected-configuration failure's diagnostics still reflect zero samples processed rather than omitting the record, in `tests/unit/test_ocr_timeline_smoother_algorithm.py`

### Implementation for User Story 3

- [X] T032 [US3] Implement lazy input validation (`scoreboard_ocr_result` present, `samples` strictly ascending by `timestamp_seconds`) at the start of `run()`, raising `INVALID_INPUT` through a diagnostics-emitting `_fail()` path in `src/cvip/video/ocr_timeline_smoother.py` (depends on T022)
- [X] T033 [US3] Implement lazy configuration validation (`outlier_window` a real `int`, not `bool`, `>= 1`) at the start of `run()`, raising `INVALID_SMOOTHING_CONFIGURATION` through the same `_fail()` path in `src/cvip/video/ocr_timeline_smoother.py` (depends on T032)
- [X] T034 [US3] Implement `OCRTimelineSmootherRunner.cancel()`, wired into the fill pass loop and `__exit__` so cancellation and normal completion share the same cleanup/diagnostics path in `src/cvip/video/ocr_timeline_smoother.py` (depends on T022)
- [X] T035 [US3] Implement the full fixed diagnostics field list (FR-017) in the diagnostics-building helper, ensuring partial-progress counts are finalized and available *before* `_fail()` emits a record on any failure path — not only on normal completion (matching every prior module's own precedent for this class of bug) in `src/cvip/video/ocr_timeline_smoother.py` (depends on T033, T034)

**Checkpoint**: All three user stories are independently functional — correct gap-filling/outlier-discounting; a self-contained, persistence-ready result; and within-budget, fully-taxonomized, cancellable operation with diagnostics guaranteed on every path.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Improvements and gates that affect the whole feature, not any single story

- [X] T036 [P] Run all four [quickstart.md](./quickstart.md) scenarios manually and record pass/fail results in `specs/006-ocr-timeline-smoother/quickstart.md`
- [X] T037 [P] Add docstrings to all public functions/classes in `src/cvip/video/{ocr_timeline_smoother_models,ocr_timeline_smoother_errors,ocr_timeline_smoother}.py`
- [X] T038 Re-run `tests/contract/test_ocr_timeline_smoother_contract.py` after US2 and US3 changes to confirm no regression against the contract
- [X] T039 Run the full test suite (`pytest`) and confirm all tests pass, including the five prior features' existing tests (regression check across all six features now sharing `src/cvip/video/`)
- [X] T040 Run the constitution-mandated coverage gate: `pytest --cov=src/cvip/video --cov-fail-under=100`. This feature is not complete until this passes — add targeted tests for any branch it reports as uncovered (Constitution Principle VII)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories
- **User Story 1 (Phase 3)**: Depends on Foundational only
- **User Story 2 (Phase 4)**: Depends on Foundational; reviews the result shape built in US1 (T005, T022) but adds no new smoothing logic of its own
- **User Story 3 (Phase 5)**: Depends on Foundational; adds validation/cancellation/failure-handling to the same `OCRTimelineSmootherRunner` from US1 (T022), additive rather than a modification to US1's smoothing logic
- **Polish (Phase 6)**: Depends on all three user stories being complete

### Within Each User Story

- Tests are written first and must fail before implementation begins
- Data model/errors (Foundational) before any `ocr_timeline_smoother.py` logic
- The usable-sample classifier (T019) before the outlier-flagging pass (T020), before the Known-Good-Tracker fill pass (T021), before the public factory function and runner class (T022)
- US2 and US3 both build on US1's T022 as their starting point, but do not depend on each other

### Parallel Opportunities

- T001, T002, T003 (Setup) can run in parallel
- T004, T005 (Foundational) can run in parallel — different files
- T007-T018 (all 12 US1 tests) can run in parallel
- T023, T024 (US2 tests) can run in parallel
- T026-T031 (all 6 US3 tests) can run in parallel
- T036, T037 (Polish) can run in parallel

---

## Parallel Example: User Story 1

```bash
# Launch all twelve US1 tests together (write first, confirm they fail):
Task: "Contract test in tests/contract/test_ocr_timeline_smoother_contract.py"
Task: "Unusable-stretch gap-fill unit test in tests/unit/test_ocr_timeline_smoother_algorithm.py"
Task: "Isolated single-sample outlier unit test in tests/unit/test_ocr_timeline_smoother_algorithm.py"
Task: "Genuine multi-sample change (not flagged as outlier) unit test in tests/unit/test_ocr_timeline_smoother_algorithm.py"
Task: "Leading-gap unit test in tests/unit/test_ocr_timeline_smoother_algorithm.py"
Task: "Trailing-gap unit test in tests/unit/test_ocr_timeline_smoother_algorithm.py"
Task: "No-op passthrough unit test in tests/unit/test_ocr_timeline_smoother_algorithm.py"
Task: "1:1 sample correspondence unit test in tests/unit/test_ocr_timeline_smoother_algorithm.py"
Task: "Outlier-window boundary-guard unit test in tests/unit/test_ocr_timeline_smoother_algorithm.py"
Task: "No-numeric-interpolation unit test in tests/unit/test_ocr_timeline_smoother_algorithm.py"
Task: "SmoothingEvidence resolution/original_sample unit test in tests/unit/test_ocr_timeline_smoother_algorithm.py"
Task: "Combined-scenario integration test in tests/integration/test_ocr_timeline_smoother_e2e.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (blocks everything else)
3. Complete Phase 3: User Story 1
4. **STOP and VALIDATE**: confirm every input sample produces exactly one cleaned sample via the two-pass flag-then-fill algorithm, with gaps and isolated outliers correctly discounted and genuine changes correctly preserved
5. This alone is a usable MVP — Event Detection could be built against a cleaned scoreboard timeline, accepting that the persistence-readiness guarantees and the explicit performance/failure-taxonomy/cancellation behaviors aren't validated yet

### Incremental Delivery

1. Setup + Foundational → foundation ready
2. Add User Story 1 → validate independently (MVP: correct gap-filling/outlier-discounting)
3. Add User Story 2 → validate independently (self-contained, persistence-ready result shape)
4. Add User Story 3 → validate independently (time budget, full failure taxonomy with diagnostics on every path, cancellation)
5. Phase 6: Polish, including the mandatory coverage gate (T040)

---

## Notes

- [P] tasks touch different files and have no unmet dependencies
- [Story] label maps each task to its user story for traceability back to spec.md
- Commit after each task or logical group
- Stop at any checkpoint to validate a story independently before moving on
- **The outlier window size (default 2), the core-scoring-tuple comparison scope, and the two-pass algorithm structure** (research.md) are reasoned choices, not empirically tuned against real broadcast footage (no golden dataset yet). T007-T018 (the flag-then-fill mechanics) are what prove the algorithm works correctly; the *real-world effectiveness* of these specific choices against actual OCR noise is what SC-009's golden-dataset criterion — explicitly out of this feature's own test-suite scope — will eventually validate.
- **FR-001/FR-002 (no video/`LoadResult`/Frame-Extraction-Service dependency)**: satisfied by construction — `OCRTimelineSmootherRequest` (data-model.md) has no field capable of carrying video-related input, and no code in this feature imports `cvip.video.frame_extraction` or `cvip.video.models`. Not independently testable as a positive runtime behavior any more than FR-010/FR-011 below are; enforced by code review (T025, T038), the same treatment as FR-010/FR-011 (`/speckit-analyze` finding F1).
- **FR-010 (no scoring events, highlight-worthiness, or replay classification derived)**: not independently testable as a positive behavior — this feature's code has no concept of "event," "importance," or "replay" anywhere in it, so there is no code path that could produce a wrong answer to assert against. Satisfied by construction and enforced by code review (T038), the same treatment Scoreboard OCR's analogous FR-023 received.
- **FR-011 (no DB writes)**: likewise not independently testable as a positive behavior — satisfied by construction (no database/SQL code exists anywhere in this feature) and enforced by code review (T038), matching every prior module's own precedent for this same requirement.
- **FR-018 (offline, CPU-only, no GPU)**: satisfied by construction, not by any runtime check — this feature makes no external calls and uses no GPU-specific API anywhere in its code, a direct consequence of never touching a video frame (unlike every prior module, which needed an explicit test for this).
- **SC-009 (measurable reduction in spurious events relative to raw OCR diffing)**: intentionally has no task in this list. It depends on `specs/technical_plan.md`'s golden dataset and Event Detection (Module 5), neither of which exists yet — consistent with how spec.md's own Success Criteria section scoped this from the start, and how Scoreboard OCR's analogous SC-011 was handled.
