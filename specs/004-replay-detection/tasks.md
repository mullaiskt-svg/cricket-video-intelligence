---

description: "Task list template for feature implementation"
---

# Tasks: Replay Detection

**Input**: Design documents from `/specs/004-replay-detection/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/replay_detection_contract.md](./contracts/replay_detection_contract.md), [quickstart.md](./quickstart.md)

**Tests**: Included — constitution Principle VII (Test-First Development) requires contract tests at module boundaries, tests written before implementation, and 100% coverage on critical paths (enforced by T049).

**Organization**: Tasks are grouped by user story (from spec.md) to enable independent implementation and testing of each story.

**Note on shared infrastructure**: This feature reuses Video Loader's (`specs/001-video-loader/`) existing `tests/fixtures/video_loader/` fixtures, the Frame Extraction Service's (`specs/002-frame-extraction-service/`) `extract_frames()` for all frame access, Scene Detection's (`specs/003-scene-detection/`) `detect_scenes()` for candidate-segment boundaries and the transition signal, `src/cvip/common/diagnostics.py`'s emitter, and `pyproject.toml`'s existing pytest/coverage configuration — no new fixtures, diagnostics module, or test-runner config are created here.

**Note on cross-cutting doc updates made during `/speckit-plan`**: `specs/technical_plan.md`'s `replays` table schema was updated (`detection_method`'s incompatible 3-value enum replaced with `confidence REAL`) and `config/default.yaml` gained a new `replay.logo_template_path` key — both already applied, not tasks in this list.

**Revision note**: This task list was revised after `/speckit-analyze` surfaced 4 findings (0 CRITICAL/HIGH, 3 MEDIUM, 1 LOW). All were addressed: a dedicated transition-signal exact-reuse test (T010), explicit diagnostics-count assertions added to the `INVALID_SCENE_DETECTION_RESULT` and `INVALID_REPLAY_CONFIGURATION` failure-path tests (T034-T037), the bundled configuration-validation task split into three independent tests — weight-sum, threshold-range, minimum-duration-range (T035-T037), and two additional "satisfied by construction" Notes entries (FR-027, FR-028's downstream half). These additions shifted all task IDs from T010 onward relative to the original version.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)

## Path Conventions

Single project, per plan.md Project Structure: new files in `src/cvip/video/` (alongside Video Loader, the Frame Extraction Service, and Scene Detection), tests in the existing `tests/{contract,integration,unit,benchmark}/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization for this feature's new files only — test directories, pytest config, and fixtures already exist from the three prior features

- [X] T001 Create `src/cvip/video/{replay_detection_models.py,replay_detection_errors.py,replay_detection.py}` as empty modules per plan.md Source Code layout
- [X] T002 [P] Create empty test file placeholders: `tests/contract/test_replay_detection_contract.py`, `tests/integration/test_replay_detection_e2e.py`, `tests/unit/test_replay_detection_validation.py`, `tests/benchmark/test_replay_detection_performance.py`
- [X] T003 [P] Confirm `pyproject.toml`'s existing `pytest` `testpaths` and `--cov=src/cvip/video` coverage scope already cover this feature's new files (same subpackage as the three prior features) — no config changes expected; document in a one-line comment if any gap is found

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core types every user story depends on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T004 [P] Implement the `ReplayDetectionFailureReason` enum (`SOURCE_NOT_VALIDATED`, `INVALID_SCENE_DETECTION_RESULT`, `INVALID_REPLAY_CONFIGURATION`, `SOURCE_UNAVAILABLE_MID_RUN`, `DECODE_FAILURE_MID_RUN`) and a `ReplayDetectionError` exception carrying it, per [contracts/replay_detection_contract.md](./contracts/replay_detection_contract.md), in `src/cvip/video/replay_detection_errors.py`
- [X] T005 [P] Implement `ReplaySegment`, `ReplayEvidence`, `ReplayDetectionRequest`, and `ReplayDetectionResult` per [data-model.md](./data-model.md) as frozen (immutable) dataclasses with plain, self-contained field types (no references to run-internal state) in `src/cvip/video/replay_detection_models.py`
- [X] T006 Implement a diagnostics-building helper (module_name `"video.replay_detection"`) reusing `src/cvip/common/diagnostics.py`'s `ExecutionDiagnostics`/`DiagnosticsTracker` (no new diagnostics module) in `src/cvip/video/replay_detection.py` (depends on T004, T005)

**Checkpoint**: Foundation ready — user story implementation can now begin

---

## Phase 3: User Story 1 - Detect and score candidate replay segments (Priority: P1) 🎯 MVP

**Goal**: Given a validated `LoadResult` and a `SceneDetectionResult`, `detect_replays()` produces correctly-scored `ReplaySegment`s by combining five weighted signals per candidate segment (four self-computed via a shared live-action-baseline mechanism, one reused directly from Scene Detection), applying the configured threshold and minimum-duration filters, deterministically, offline and CPU-only, and rejects an unvalidated source without touching a frame.

**Independent Test**: Run detection against the Video Loader fixtures (via Scene Detection's own output) and confirm segments are correctly ordered, uniquely identified, confidence-scored via the weighted combination, filtered by threshold and minimum duration, and that a failed `LoadResult` is rejected immediately.

### Tests for User Story 1 ⚠️

> Write these tests FIRST, ensure they FAIL before implementation

- [X] T007 [P] [US1] Contract test asserting `detect_replays()` returns a `ReplayDetector` matching [contracts/replay_detection_contract.md](./contracts/replay_detection_contract.md)'s shape, and that a `FAILURE` `LoadResult` yields `SOURCE_NOT_VALIDATED` without any file access, in `tests/contract/test_replay_detection_contract.py`
- [X] T008 [P] [US1] Integration test: detection against the Video Loader `valid_short.mp4` fixture (via a real Scene Detection result) yields a structurally valid `ReplayDetectionResult` — ordered segments, each with a unique `replay_id` and a confidence in `[0.0, 1.0]` — and exactly one `ReplayDetectionDiagnostics` record for the successful run, in `tests/integration/test_replay_detection_e2e.py`
- [X] T009 [P] [US1] Unit test asserting the weighted-combination arithmetic: given a `ReplayEvidence` with known per-signal scores and known configured weights, `combined_confidence` equals the expected weighted sum (FR-009), in `tests/unit/test_replay_detection_validation.py`
- [X] T010 [P] [US1] Unit test asserting the transition signal is an exact, unmodified reuse of Scene Detection's own value (FR-007): given a boundary classified `REPLAY_TRANSITION` with a known confidence, `ReplayEvidence.transition_score` equals that exact confidence value (not recomputed, not rounded, not scaled); given a boundary classified `ORDINARY_CUT`, `transition_score` is exactly `0.0`, in `tests/unit/test_replay_detection_validation.py`
- [X] T011 [P] [US1] Integration test: a candidate segment whose combined confidence meets/exceeds the configured threshold is reported; one whose confidence falls below is not — including a segment Scene Detection flagged `REPLAY_TRANSITION` when the other signals pull the combined confidence below threshold (US1 Acceptance Scenarios 2-3), in `tests/integration/test_replay_detection_e2e.py`
- [X] T012 [P] [US1] Integration test: a candidate segment shorter than the configured minimum duration is never reported, regardless of its combined confidence (US1 Acceptance Scenario 4, FR-012, SC-003), in `tests/integration/test_replay_detection_e2e.py`
- [X] T013 [P] [US1] Integration test: a video with no replay footage at all yields an empty segment list rather than failing or fabricating a segment (US1 Acceptance Scenario 5), in `tests/integration/test_replay_detection_e2e.py`
- [X] T014 [P] [US1] Unit test: the logo-presence signal always scores 0.0 when no `logo_template_path` is configured, and detection still completes normally using the remaining four signals (FR-015), in `tests/unit/test_replay_detection_validation.py`
- [X] T015 [P] [US1] Unit test confirming frames are sourced exclusively via `extract_frames()` (mock/spy) and that `cv2.VideoCapture` is never constructed directly by this feature's code, per FR-004, and confirming no network calls are possible during detection (mock `socket.socket`/`socket.create_connection`) per FR-020, and a static check that no GPU-specific API (`cv2.cuda.*`) is used per FR-021, in `tests/unit/test_replay_detection_validation.py`
- [X] T016 [P] [US1] Integration test asserting determinism (FR-024/SC-006): run the identical `ReplayDetectionRequest` against the same fixture and Scene Detection result 3 times and assert the segment sequence — including confidence scores — is identical across all 3 runs, in `tests/integration/test_replay_detection_e2e.py`
- [X] T017 [P] [US1] Unit test asserting deterministic secondary ordering (FR-018): two segments with identical `start_seconds` are ordered by ascending `end_seconds`, then by stable input order, in `tests/unit/test_replay_detection_validation.py`
- [X] T018 [P] [US1] Unit test asserting every `replay_id` within a single `ReplayDetectionResult` is unique across a fixture producing multiple segments, per FR-014/SC-011, in `tests/unit/test_replay_detection_validation.py`
- [X] T019 [P] [US1] Unit test asserting per-segment signal aggregation is the mean across all sampled frames within the segment, not a peak or majority-vote alternative (FR-029), by directly exercising the aggregation helper with a controlled set of per-frame scores, in `tests/unit/test_replay_detection_validation.py`
- [X] T020 [P] [US1] Unit test asserting the Live-Action Baseline's cold-start handling: a candidate segment evaluated before the baseline has accumulated any non-candidate samples yields the neutral 0.5 score for each of the three baseline-relative signals, not a fabricated 0.0 or 1.0 (data-model.md "Cold-start handling"), in `tests/unit/test_replay_detection_validation.py`

### Implementation for User Story 1

- [X] T021 [US1] Implement the Live-Action Baseline Tracker — rolling means for the scoreboard-ROI content signature, whole-frame difference magnitude, and coarse whole-frame fingerprint, updated only from frames outside any currently-open candidate segment, with cold-start (insufficient-sample) handling — in `src/cvip/video/replay_detection.py` (depends on T005)
- [X] T022 [US1] Implement the four self-computed per-frame signal functions: logo-presence (OpenCV template matching against the optional configured template), scoreboard-region absence, motion profile, and camera-angle difference (the latter three scored via deviation from the Live-Action Baseline Tracker) in `src/cvip/video/replay_detection.py` (depends on T021)
- [X] T023 [US1] Implement per-segment signal aggregation (mean across sampled frames per FR-029) and combination into a `ReplayEvidence` with `combined_confidence` derived from the request's configured weights (FR-009), including the transition signal's exact, unmodified pass-through from the bracketing Scene Detection boundary (FR-007) in `src/cvip/video/replay_detection.py` (depends on T022)
- [X] T024 [US1] Implement the core detection loop: consume `extract_frames()` at the platform's configured 1 FPS rate, derive candidate segment boundaries from the Scene Detection result (FR-005), feed each sampled frame to the baseline tracker and signal functions, and finalize each candidate segment by applying the confidence threshold and minimum-duration filters (FR-011, FR-012) in `src/cvip/video/replay_detection.py` (depends on T023)
- [X] T025 [US1] Implement the `detect_replays()` factory function and the `SOURCE_NOT_VALIDATED` rejection path for a non-`SUCCESS` `LoadResult` in `src/cvip/video/replay_detection.py` (depends on T004, T024)
- [X] T026 [US1] Implement `ReplayDetector` as a context manager (`__enter__`/`__exit__`: release the underlying `FrameExtractor`, build and emit the diagnostics record via T006's helper) in `src/cvip/video/replay_detection.py` (depends on T006, T025)
- [X] T027 [US1] Implement `replay_id` assignment (sequential, unique within the run) and the ordering/tie-break guarantee (ascending start, then end, then stable input order — FR-014, FR-018) when finalizing `ReplayDetectionResult.segments` in `src/cvip/video/replay_detection.py` (depends on T026)

**Checkpoint**: User Story 1 is fully functional and independently testable — candidate segments are correctly detected, scored via the weighted five-signal combination (with the transition signal an exact, verified pass-through), filtered by threshold/minimum-duration, deterministically, offline/CPU-only, and an invalid source is rejected without touching a frame.

---

## Phase 4: User Story 2 - Produce a segment list usable across the analyze/generate workflow (Priority: P2)

**Goal**: The detection result's shape is fully self-contained (plain values, no references to run-internal state) and carries a source-video identifier, so a later, separate process (`cvip generate`) can consume it without any of this run's in-memory state still existing.

**Independent Test**: Confirm the result's fields are plain, immutable values with no back-reference to the `ReplayDetector` instance, and that `source_video_id` correctly identifies the analyzed video.

### Tests for User Story 2 ⚠️

- [X] T028 [P] [US2] Integration test: a completed `ReplayDetectionResult`'s `source_video_id` matches the video's own `file_hash` (US2 Acceptance Scenario 2, FR-017), in `tests/integration/test_replay_detection_e2e.py`
- [X] T029 [P] [US2] Unit test: `ReplaySegment` and `ReplayDetectionResult` are frozen dataclasses — attempting to mutate a field after construction raises, reinforcing that downstream consumers receive final, non-reinterpretable values (US2 Acceptance Scenario 1 and 3, FR-028), in `tests/unit/test_replay_detection_validation.py`

### Implementation for User Story 2

- [X] T030 [US2] Review `src/cvip/video/replay_detection_models.py` and `src/cvip/video/replay_detection.py` to confirm `ReplaySegment`/`ReplayDetectionResult` are self-contained (frozen, plain field types, no back-references to `ReplayDetector` state) and fix any finding (depends on T005, T027)

**Checkpoint**: User Stories 1 AND 2 both work independently — correct, scored segment detection, plus a result shape safe to hand to a separate later process.

---

## Phase 5: User Story 3 - Complete within budget, and follow platform-standard operational behavior (Priority: P3)

**Goal**: Detection against a full 3-4 hour match completes within its ~2-5 minute budget share, decodes the video no more than once, supports cooperative cancellation, and fails fast with one of the taxonomy's five specific reasons on every failure path — always emitting exactly one diagnostics record, including for a rejected configuration.

**Independent Test**: Run detection against the multi-hour fixture and confirm elapsed time and single-pass behavior; separately, force each of the five failure conditions and confirm the matching specific reason plus exactly one diagnostics record; separately, confirm `.cancel()` stops a run cleanly.

### Tests for User Story 3 ⚠️

- [X] T031 [P] [US3] Benchmark test asserting detection against `multi_hour.mp4` completes within its allotted ~2-5 minute share of the overall analysis budget (SC-004), in `tests/benchmark/test_replay_detection_performance.py`
- [X] T032 [P] [US3] Integration test asserting single-forward-pass behavior observably (FR-019/SC-005): spy on the underlying `cv2.VideoCapture.set(cv2.CAP_PROP_POS_FRAMES, ...)` calls made during a full detection run via the Frame Extraction Service, and assert the sequence of seeked positions is strictly increasing with no repeats, in `tests/integration/test_replay_detection_e2e.py`
- [X] T033 [P] [US3] Integration test: the source becoming inaccessible partway through a run yields `SOURCE_UNAVAILABLE_MID_RUN`, and a corrupted/undecodable frame partway through yields `DECODE_FAILURE_MID_RUN` (both via mocking the underlying `FrameExtractor`), **each asserting exactly one diagnostics record is emitted** (FR-022/SC-007), in `tests/integration/test_replay_detection_e2e.py`
- [X] T034 [P] [US3] Integration test: a `SceneDetectionResult` that is missing, malformed, or whose `source_video_id` doesn't match the video being analyzed yields `INVALID_SCENE_DETECTION_RESULT` before any frame is processed (US3 Acceptance Scenario 5), **asserting exactly one diagnostics record is emitted** for this rejection (FR-022/SC-007), in `tests/integration/test_replay_detection_e2e.py`
- [X] T035 [P] [US3] Integration test: a configuration whose five weights do not sum to 1.0 yields `INVALID_REPLAY_CONFIGURATION` before any frame is processed, **asserting exactly one diagnostics record is emitted** for this rejection (US3 Acceptance Scenario 4, FR-010, SC-010, FR-022/SC-007), in `tests/integration/test_replay_detection_e2e.py`
- [X] T036 [P] [US3] Integration test: a configuration whose `confidence_threshold` is outside `[0.0, 1.0]` yields `INVALID_REPLAY_CONFIGURATION` before any frame is processed, with exactly one diagnostics record emitted (FR-010, FR-022/SC-007) — independent of T035's weight-sum case, in `tests/integration/test_replay_detection_e2e.py`
- [X] T037 [P] [US3] Integration test: a configuration whose `min_segment_seconds` is negative or non-finite yields `INVALID_REPLAY_CONFIGURATION` before any frame is processed, with exactly one diagnostics record emitted (FR-010, FR-022/SC-007) — independent of T035/T036's cases, in `tests/integration/test_replay_detection_e2e.py`
- [X] T038 [P] [US3] Integration test: calling `.cancel()` mid-detection stops further frame processing, releases resources, and emits exactly one diagnostics record summarizing the partial run, in `tests/integration/test_replay_detection_e2e.py`
- [X] T039 [P] [US3] Unit test asserting the diagnostics record contains every field FR-025 requires (candidate segments evaluated, replay segments accepted, replay segments rejected, average confidence, highest confidence, longest replay duration, total replay duration, sampling rate used, processing duration) for a successful run, **and** that a mid-run or configuration failure's diagnostics still reflect whatever was evaluated/accepted before the failure rather than reporting all-zero counts, in `tests/unit/test_replay_detection_validation.py`

### Implementation for User Story 3

- [X] T040 [US3] Implement lazy configuration validation (five weights sum to 1.0 within tolerance; threshold within `[0.0, 1.0]`; minimum duration finite and non-negative — each validated and reported independently) at the start of `run()`, raising `INVALID_REPLAY_CONFIGURATION` through the same diagnostics-emitting `_fail()` path used by every other failure reason (research.md's lazy-validation decision, not a constructor-time `ValueError`) in `src/cvip/video/replay_detection.py` (depends on T025)
- [X] T041 [US3] Implement `INVALID_SCENE_DETECTION_RESULT` validation (missing result, or `source_video_id` mismatch against the video being analyzed) in `src/cvip/video/replay_detection.py` (depends on T040)
- [X] T042 [US3] Implement mid-run failure translation, mapping the underlying `FrameExtractor`'s `ExtractionError` to `SOURCE_UNAVAILABLE_MID_RUN`/`DECODE_FAILURE_MID_RUN`, plus a broad exception handler mapping any other unexpected mid-run processing error to `DECODE_FAILURE_MID_RUN` (matching Scene Detection's own precedent for this exact gap) in `src/cvip/video/replay_detection.py` (depends on T041)
- [X] T043 [US3] Implement `ReplayDetector.cancel()`, wired into the detection loop and `__exit__` so cancellation and normal completion share the same cleanup/diagnostics path in `src/cvip/video/replay_detection.py` (depends on T027)
- [X] T044 [US3] Implement the full fixed diagnostics field list (FR-025) in the diagnostics-building helper, ensuring partial-progress state (segments evaluated/accepted/rejected so far, confidence/duration statistics) is finalized and available *before* `_fail()` emits a record on any failure path — not only on normal completion (matching Scene Detection's own `_finalize_boundaries`-before-`_fail()` fix for the same class of bug) in `src/cvip/video/replay_detection.py` (depends on T042, T043)

**Checkpoint**: All three user stories are independently functional — correct, scored detection; a self-contained, persistence-ready result; and within-budget, single-pass, fully-taxonomized, cancellable operation with diagnostics guaranteed on every path.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Improvements and gates that affect the whole feature, not any single story

- [X] T045 [P] Run all four [quickstart.md](./quickstart.md) scenarios manually on target-class hardware (or the closest available) and record pass/fail results in `specs/004-replay-detection/quickstart.md`
- [X] T046 [P] Add docstrings to all public functions/classes in `src/cvip/video/{replay_detection_models,replay_detection_errors,replay_detection}.py`
- [X] T047 Re-run `tests/contract/test_replay_detection_contract.py` after US2 and US3 changes to confirm no regression against the contract
- [X] T048 Run the full test suite (`pytest`) and confirm all tests pass, including Video Loader's, the Frame Extraction Service's, and Scene Detection's existing tests (regression check across all four features now sharing `src/cvip/video/`)
- [X] T049 Run the constitution-mandated coverage gate: `pytest --cov=src/cvip/video --cov-fail-under=100`. This feature is not complete until this passes — add targeted tests for any branch it reports as uncovered (Constitution Principle VII)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories
- **User Story 1 (Phase 3)**: Depends on Foundational only
- **User Story 2 (Phase 4)**: Depends on Foundational; reviews the result shape built in US1 (T005, T027) but adds no new detection logic of its own
- **User Story 3 (Phase 5)**: Depends on Foundational; adds validation/cancellation/failure-handling to the same `ReplayDetector` from US1 (T025, T027), additive rather than a modification to US1's scoring logic
- **Polish (Phase 6)**: Depends on all three user stories being complete

### Within Each User Story

- Tests are written first and must fail before implementation begins
- Data model/errors (Foundational) before any `replay_detection.py` logic
- Baseline tracker (T021) before the signal functions that use it (T022), before per-segment aggregation (T023), before the core detection loop (T024), before the public factory function (T025), before context-manager wiring (T026), before `replay_id`/ordering finalization (T027)
- US2 and US3 both build on US1's T025/T027 as their starting point, but do not depend on each other

### Parallel Opportunities

- T002, T003 (Setup) can run in parallel
- T004, T005 (Foundational) can run in parallel — different files
- T007-T020 (all 14 US1 tests) can run in parallel
- T028, T029 (US2 tests) can run in parallel
- T031-T039 (all 9 US3 tests) can run in parallel
- T045, T046 (Polish) can run in parallel

---

## Parallel Example: User Story 1

```bash
# Launch all fourteen US1 tests together (write first, confirm they fail):
Task: "Contract test in tests/contract/test_replay_detection_contract.py"
Task: "Structural-correctness + diagnostics-count integration test in tests/integration/test_replay_detection_e2e.py"
Task: "Weighted-combination arithmetic unit test in tests/unit/test_replay_detection_validation.py"
Task: "Transition-signal exact-reuse unit test in tests/unit/test_replay_detection_validation.py"
Task: "Threshold application integration test in tests/integration/test_replay_detection_e2e.py"
Task: "Minimum-duration filtering integration test in tests/integration/test_replay_detection_e2e.py"
Task: "Empty-result (no replays) integration test in tests/integration/test_replay_detection_e2e.py"
Task: "Missing-logo-template graceful-degradation unit test in tests/unit/test_replay_detection_validation.py"
Task: "Frame-sourcing/offline/CPU-only unit test in tests/unit/test_replay_detection_validation.py"
Task: "Determinism integration test in tests/integration/test_replay_detection_e2e.py"
Task: "Deterministic tie-break ordering unit test in tests/unit/test_replay_detection_validation.py"
Task: "replay_id uniqueness unit test in tests/unit/test_replay_detection_validation.py"
Task: "Mean-aggregation unit test in tests/unit/test_replay_detection_validation.py"
Task: "Baseline cold-start unit test in tests/unit/test_replay_detection_validation.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (blocks everything else)
3. Complete Phase 3: User Story 1
4. **STOP and VALIDATE**: confirm candidate segments are correctly detected, scored via the weighted five-signal combination (including a verified exact-reuse transition signal), filtered by threshold/minimum-duration, deterministically, offline/CPU-only, against the Video Loader fixtures (via a real Scene Detection result), and that an invalid source is rejected without touching a frame
5. This alone is a usable MVP — Event Detection and Clip Generator could be built against a scored segment list, accepting that the persistence-readiness guarantees and the explicit budget/failure-taxonomy/cancellation behaviors aren't validated yet

### Incremental Delivery

1. Setup + Foundational → foundation ready
2. Add User Story 1 → validate independently (MVP: correct, deterministic, weighted-signal segment detection + fail-fast on an invalid source + offline/CPU-only)
3. Add User Story 2 → validate independently (self-contained, persistence-ready result shape)
4. Add User Story 3 → validate independently (time budget, single pass, full failure taxonomy with diagnostics on every path, cancellation)
5. Phase 6: Polish, including the mandatory coverage gate (T049)

---

## Notes

- [P] tasks touch different files and have no unmet dependencies
- [Story] label maps each task to its user story for traceability back to spec.md
- Commit after each task or logical group
- Stop at any checkpoint to validate a story independently before moving on
- **The four self-computed signals' exact per-frame measurements** (research.md: template-match score for logo presence; edge/variance measure for scoreboard-region content; whole-frame difference magnitude for motion profile; a coarse downscaled/blurred descriptor for camera-angle) are reasoned choices, not empirically tuned against real broadcast footage during planning (offline environment, no golden dataset yet). T008-T013/T016 (structural, threshold, determinism tests) are what prove the *mechanics* work correctly; the *real-world accuracy* of these specific measurements against actual replay footage is what SC-009's golden-dataset criterion — explicitly out of this feature's own test-suite scope — will eventually validate. If accuracy proves insufficient once that dataset exists, the specific per-signal measurement can be swapped without changing this contract.
- **FR-021 (CPU-only)**: partially covered directly (T015's static/behavioral check that no GPU-specific OpenCV API is used) and additionally satisfied by construction — no GPU library or code path exists anywhere in this feature, matching every prior module's own precedent for this same requirement.
- **FR-026 (no DB writes)**: not independently testable as a positive behavior (there's no "wrong" output to assert against for something the feature never attempts) — satisfied by construction (no database/SQL code exists anywhere in this feature) and enforced by code review (T047's contract re-check), the same way Scene Detection's analogous FR-021 was handled.
- **FR-027 (must not determine highlight-worthiness or presentation)**: likewise not independently testable as a positive behavior — this feature's code has no concept of "importance," "ranking," or "presentation" anywhere in it, so there is no code path that could produce a wrong answer to assert against. Satisfied by construction and enforced by code review (T047), the same treatment as FR-026.
- **FR-028's downstream-facing half** ("no other module may recompute replay classification from raw signal evidence or apply a different threshold to this feature's output"): the half of this requirement that constrains *this* feature (never expose evidence as if it were re-decidable, treat its own decision as final) is covered by T029/T030. The half that constrains *other, not-yet-built* modules (Event Detection, Clip Generator) cannot be verified by this feature's own test suite — there is nothing to test against yet. It will be proven out when those modules are actually built against this feature's contract (`contracts/replay_detection_contract.md`), the same way the Frame Extraction Service's own FR-013 and Scene Detection's FR-013 were both deferred to their first real consumer rather than tested in isolation.
- **SC-009 (≥90% replay-removal accuracy against the golden dataset)**: intentionally has no task in this list. It depends on `specs/technical_plan.md`'s golden dataset, a cross-cutting platform deliverable that doesn't exist yet — consistent with how spec.md's own Success Criteria section scoped this from the start.
