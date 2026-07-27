---

description: "Task list template for feature implementation"
---

# Tasks: Scene Detection

**Input**: Design documents from `/specs/003-scene-detection/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/scene_detection_contract.md](./contracts/scene_detection_contract.md), [quickstart.md](./quickstart.md)

**Tests**: Included — constitution Principle VII (Test-First Development) requires contract tests at module boundaries, tests written before implementation, and 100% coverage on critical paths (enforced by T037).

**Organization**: Tasks are grouped by user story (from spec.md) to enable independent implementation and testing of each story.

**Note on shared infrastructure**: This feature reuses Video Loader's (`specs/001-video-loader/`) existing `tests/fixtures/video_loader/` fixtures, the Frame Extraction Service's (`specs/002-frame-extraction-service/`) `extract_frames()` for all frame access, `src/cvip/common/diagnostics.py`'s emitter, and `pyproject.toml`'s existing pytest/coverage configuration — no new fixtures, diagnostics module, or test-runner config are created here.

**Note on scope correction during planning**: An early draft of `data-model.md`/the contract included an optional `resume_from_frame_index` field on `SceneDetectionRequest`, mirroring the Frame Extraction Service. This was corrected before task generation: spec.md's FR-019 only requires clean cancellation and leaving the *Pipeline Orchestrator* able to resume the overall `cvip analyze` workflow afterward — it does not require this feature to itself resume mid-detection from a checkpoint. No resume-related tasks appear below; `RESUME_POINT_OUT_OF_RANGE` was likewise removed from the failure taxonomy as dead code with no requirement behind it.

**Revision note**: This task list was revised after `/speckit-analyze` surfaced 7 findings (2 HIGH, 4 MEDIUM, 1 LOW). All were addressed: threshold-configurability coverage (T014), boundary_id uniqueness coverage (T015), single-forward-pass behavioral coverage (T016), ambiguous-classification coverage (T025), Result-metadata consistency (folded into T008), the stale Frame Extraction Service integration wording in spec.md/research.md/`technical_plan.md` (fixed directly in those docs), and FR-013's deferred-testability note (added below). These additions shifted all task IDs from T014 onward relative to the original version.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)

## Path Conventions

Single project, per plan.md Project Structure: new files in `src/cvip/video/` (alongside Video Loader and the Frame Extraction Service), tests in the existing `tests/{contract,integration,unit,benchmark}/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization for this feature's new files only — test directories, pytest config, and fixtures already exist from Video Loader and the Frame Extraction Service

- [X] T001 Create `src/cvip/video/{scene_detection_models.py,scene_detection_errors.py,scene_detection.py}` as empty modules per plan.md Source Code layout
- [X] T002 [P] Create empty test file placeholders: `tests/contract/test_scene_detection_contract.py`, `tests/integration/test_scene_detection_e2e.py`, `tests/unit/test_scene_detection_validation.py`, `tests/benchmark/test_scene_detection_performance.py`
- [X] T003 [P] Confirm `pyproject.toml`'s existing `pytest` `testpaths` and `--cov=src/cvip/video` coverage scope already cover this feature's new files (same subpackage as Video Loader and the Frame Extraction Service) — no config changes expected; document in a one-line comment if any gap is found

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core types every user story depends on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T004 [P] Implement `BoundaryType`, `SceneDetectionRequest` (including its validation rules: `load_result.status == SUCCESS`, `scene_threshold` finite and non-negative), `SceneBoundary`, and `SceneDetectionResult` per [data-model.md](./data-model.md) in `src/cvip/video/scene_detection_models.py`
- [X] T005 [P] Implement the `SceneDetectionFailureReason` enum (`SOURCE_NOT_VALIDATED`, `SOURCE_UNAVAILABLE_MID_RUN`, `DECODE_FAILURE_MID_RUN`) and a `SceneDetectionError` exception carrying it, per [contracts/scene_detection_contract.md](./contracts/scene_detection_contract.md), in `src/cvip/video/scene_detection_errors.py`
- [X] T006 Implement a diagnostics-building helper (module_name `"video.scene_detection"`) reusing `src/cvip/common/diagnostics.py`'s `ExecutionDiagnostics`/`DiagnosticsTracker` (no new diagnostics module) in `src/cvip/video/scene_detection.py` (depends on T004, T005)

**Checkpoint**: Foundation ready — user story implementation can now begin

---

## Phase 3: User Story 1 - Segment a match video into scene boundaries (Priority: P1) 🎯 MVP

**Goal**: Given a successful `LoadResult`, `detect_scenes()` produces a correctly-ordered `SceneDetectionResult` by driving PySceneDetect's per-frame API over frames sourced from the Frame Extraction Service — never opening the video file itself — in a single forward pass, deterministically, offline and CPU-only, and fails fast on a non-validated source or a mid-run problem.

**Independent Test**: Run detection against the Video Loader fixtures and confirm the returned boundaries are correctly ordered and timestamped; confirm an empty boundary list for a single continuous shot; confirm a failed `LoadResult` is rejected immediately; confirm repeated runs are identical; confirm no network dependency, no direct `cv2.VideoCapture` use, no backward seeking, unique boundary IDs, and that `scene_threshold` is actually applied.

### Tests for User Story 1 ⚠️

> Write these tests FIRST, ensure they FAIL before implementation

- [X] T007 [P] [US1] Contract test asserting `detect_scenes()` returns a `SceneDetector` matching [contracts/scene_detection_contract.md](./contracts/scene_detection_contract.md)'s shape, and that a `FAILURE` `LoadResult` yields `SOURCE_NOT_VALIDATED` without any file access, in `tests/contract/test_scene_detection_contract.py`
- [X] T008 [P] [US1] Integration test: detection against the Video Loader `valid_short.mp4`/`.mkv` fixtures yields a strictly ascending, no-duplicate-timestamp boundary list; assert exactly one `SceneDetectionDiagnostics` record is emitted for this successful run (FR-015/SC-005 happy-path case); **also assert `SceneDetectionResult`'s metadata is internally consistent with the boundary list**: `total_boundaries == len(boundaries)`, `replay_transition_count == count(b for b in boundaries if b.boundary_type == REPLAY_TRANSITION)`, `processing_duration` is populated and positive, and `configuration_version` is populated (FR-014), in `tests/integration/test_scene_detection_e2e.py`
- [X] T009 [P] [US1] Integration test: a video that is a single continuous shot with no cuts yields an empty boundary list rather than failing or fabricating a boundary (US1 Acceptance Scenario 3), in `tests/integration/test_scene_detection_e2e.py`
- [X] T010 [P] [US1] Unit test asserting frames are sourced exclusively via `extract_frames()` (mock/spy on `cvip.video.frame_extraction.extract_frames`) and that `cv2.VideoCapture` is never constructed directly by this feature's code, per FR-003/research.md Decision 1, in `tests/unit/test_scene_detection_validation.py`
- [X] T011 [P] [US1] Integration test: the source becoming inaccessible partway through a run yields `SOURCE_UNAVAILABLE_MID_RUN`, and a corrupted/undecodable frame partway through yields `DECODE_FAILURE_MID_RUN` (both via mocking the underlying `FrameExtractor`), in `tests/integration/test_scene_detection_e2e.py`
- [X] T012 [P] [US1] Unit test confirming no network calls are possible during detection (mock/patch `socket.socket` and `socket.create_connection` to raise if called, assert a normal run still succeeds) per FR-016, and a static/behavioral check that no GPU-specific API (e.g., no `cv2.cuda.*` calls) is used per FR-017, in `tests/unit/test_scene_detection_validation.py`
- [X] T013 [P] [US1] Integration test asserting determinism (FR-020/SC-008): run the identical `SceneDetectionRequest` against the same fixture 3 times and assert the boundary sequence — including classifications and confidence scores — is identical across all 3 runs, in `tests/integration/test_scene_detection_e2e.py`
- [X] T014 [P] [US1] Integration test asserting `scene_threshold` is actually applied, not hardcoded or ignored (FR-012): run detection against the same fixture with a deliberately low `scene_threshold` and a deliberately high one, and assert the resulting boundary counts differ (the low threshold detects at least as many cuts as the high one, with at least one case where they differ), in `tests/integration/test_scene_detection_e2e.py`
- [X] T015 [P] [US1] Unit test asserting every `boundary_id` within a single `SceneDetectionResult` is unique — no duplicates — across a fixture producing multiple boundaries, per FR-009, in `tests/unit/test_scene_detection_validation.py`
- [X] T016 [P] [US1] Integration test asserting single-forward-pass behavior observably (FR-004/SC-007): spy on the underlying `cv2.VideoCapture.set(cv2.CAP_PROP_POS_FRAMES, ...)` calls made during a full detection run via the Frame Extraction Service, and assert the sequence of seeked positions is strictly increasing with no repeats — i.e., no backward seek and no frame revisited. This validates observable seek behavior, not this feature's own internal call structure, in `tests/integration/test_scene_detection_e2e.py`

### Implementation for User Story 1

- [X] T017 [US1] Implement the core detection loop: consume `extract_frames()` in `SamplingMode.FULL`, feed each frame to PySceneDetect's `ContentDetector.process_frame()` (configured with the request's `scene_threshold`), and collect raw cut points into preliminary `SceneBoundary` entries (timestamp only, from the `FrameContext`'s own actual timestamp) in `src/cvip/video/scene_detection.py` (depends on T004)
- [X] T018 [US1] Implement the `detect_scenes()` factory function and the `SOURCE_NOT_VALIDATED` rejection path for a non-`SUCCESS` `LoadResult` in `src/cvip/video/scene_detection.py` (depends on T005, T017)
- [X] T019 [US1] Implement `SceneDetector` as a context manager (`__enter__`/`__exit__`: release the underlying `FrameExtractor`, build and emit the diagnostics record via T006's helper) in `src/cvip/video/scene_detection.py` (depends on T006, T018)
- [X] T020 [US1] Implement mid-run failure translation, mapping the underlying `FrameExtractor`'s `ExtractionError` (`SOURCE_UNAVAILABLE_MID_RUN`/`DECODE_FAILURE_MID_RUN`) to this feature's own `SceneDetectionFailureReason` values in `src/cvip/video/scene_detection.py` (depends on T019)
- [X] T021 [US1] Implement `boundary_id` assignment (sequential, ascending-timestamp order, unique within the run) and the ordering/no-duplicate-timestamp guarantee (FR-006, FR-009), plus `SceneDetectionResult`'s metadata fields (`total_boundaries`, `replay_transition_count`, `processing_duration`, `configuration_version`) when finalizing the result, in `src/cvip/video/scene_detection.py` (depends on T020)

**Checkpoint**: User Story 1 is fully functional and independently testable — boundaries are correctly detected and ordered against a validated video, deterministically, offline/CPU-only, sourced only through the Frame Extraction Service in a single verified forward pass, with unique boundary IDs, a correctly-applied configurable threshold, and failing fast on an invalid source or mid-run problem.

---

## Phase 4: User Story 2 - Flag replay-style transitions distinctly from ordinary cuts (Priority: P2)

**Goal**: Every boundary is classified as `ORDINARY_CUT` or `REPLAY_TRANSITION` with a mandatory confidence score, using the gradual-ramp-vs-instantaneous-jump heuristic from research.md Decision 2, without introducing a second pass over the video — including boundaries whose classification is genuinely ambiguous.

**Independent Test**: Run detection against a video containing both a known ordinary hard cut and a known replay-style transition, and confirm the two boundaries receive different classifications, each with a confidence score present; separately, confirm a genuinely ambiguous boundary still completes without error.

### Tests for User Story 2 ⚠️

- [X] T022 [P] [US2] Integration test: a boundary corresponding to a known ordinary hard cut is classified `ORDINARY_CUT`; a boundary corresponding to a known replay-style transition (a synthetic gradual multi-frame content ramp) is classified `REPLAY_TRANSITION`, in `tests/integration/test_scene_detection_e2e.py`
- [X] T023 [P] [US2] Unit test asserting `confidence` is always present (never `None`/absent) on every returned boundary, including ambiguous/low-confidence cases, and always falls within `[0.0, 1.0]`, per FR-008/SC-009, in `tests/unit/test_scene_detection_validation.py`
- [X] T024 [P] [US2] Unit test for the classification heuristic itself: a mocked instantaneous single-frame content jump classifies `ORDINARY_CUT` with a high confidence; a mocked gradual multi-frame ramp classifies `REPLAY_TRANSITION` with a high confidence, in `tests/unit/test_scene_detection_validation.py`
- [X] T025 [P] [US2] Unit test for a genuinely ambiguous boundary (a mocked frame window that matches neither the instantaneous-jump nor the gradual-ramp pattern cleanly): detection completes without raising, the boundary is still included in the result, it carries a valid `boundary_type`, and its `confidence` is low but present — never absent and never causing the run to fail (FR-011, US2 Acceptance Scenario 4), in `tests/unit/test_scene_detection_validation.py`

### Implementation for User Story 2

- [X] T026 [US2] Implement the transition-classification heuristic — examine the small trailing window of already-yielded frames around each detected cut for a gradual-ramp vs. instantaneous-jump content-change pattern (research.md Decision 2) — in `src/cvip/video/scene_detection.py` (depends on T021)
- [X] T027 [US2] Wire the heuristic's output into each `SceneBoundary`'s `boundary_type`/`confidence` assignment, ensuring an ambiguous case still gets a best-effort classification with a correspondingly lower (but always present) confidence rather than failing the run (FR-011), in `src/cvip/video/scene_detection.py` (depends on T026)
- [X] T028 [US2] Review `src/cvip/video/scene_detection.py` to confirm the trailing-window heuristic uses only a small, fixed-size buffer of already-yielded frames — no backward seek, no re-invocation of `extract_frames()`, no second pass (FR-004) — and fix any finding (depends on T027)

**Checkpoint**: User Stories 1 AND 2 both work independently — correct boundary detection, plus correct best-effort classification (including ambiguous cases) with a mandatory confidence score, all within a single forward pass.

---

## Phase 5: User Story 3 - Complete within budget, and support clean cancellation (Priority: P3)

**Goal**: Detection against a full 3-4 hour match completes within its ~10-20 minute budget share and does not consume memory that scales with video duration; `.cancel()` stops a run cleanly and still emits diagnostics.

**Independent Test**: Run detection against the multi-hour fixture and confirm both elapsed time and peak memory stay within the documented budget; separately, start a run and call `.cancel()` partway through and confirm it stops cleanly with exactly one diagnostics record.

### Tests for User Story 3 ⚠️

- [X] T029 [P] [US3] Benchmark test asserting detection against `multi_hour.mp4` completes within its allotted ~10-20 minute share of the overall analysis budget (SC-003), in `tests/benchmark/test_scene_detection_performance.py`
- [X] T030 [P] [US3] Benchmark test asserting peak memory for detection against `valid_short.mp4` does not exceed peak memory against `multi_hour.mp4` by more than the SC-004 tolerance (i.e., memory does not scale with duration), in `tests/benchmark/test_scene_detection_performance.py`
- [X] T031 [P] [US3] Integration test: calling `.cancel()` mid-detection stops further frame processing, releases resources, and emits exactly one diagnostics record summarizing the partial run, in `tests/integration/test_scene_detection_e2e.py`

### Implementation for User Story 3

- [X] T032 [US3] Implement `SceneDetector.cancel()`, wired into the detection loop and `__exit__` so cancellation and normal completion share the same cleanup/diagnostics path, in `src/cvip/video/scene_detection.py` (depends on T021)

**Checkpoint**: All three user stories are independently functional — correct detection, correct classification with confidence (including ambiguous cases), and within-budget/cancellable execution.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Improvements and gates that affect the whole feature, not any single story

- [X] T033 [P] Run all four [quickstart.md](./quickstart.md) scenarios manually on target-class hardware (or the closest available) and record pass/fail results in `specs/003-scene-detection/quickstart.md`
- [X] T034 [P] Add docstrings to all public functions/classes in `src/cvip/video/{scene_detection_models,scene_detection_errors,scene_detection}.py`
- [X] T035 Re-run `tests/contract/test_scene_detection_contract.py` after US2 and US3 changes to confirm no regression against the contract
- [X] T036 Run the full test suite (`pytest`) and confirm all tests pass, including Video Loader's and the Frame Extraction Service's existing tests (regression check across all three features now sharing `src/cvip/video/`)
- [X] T037 Run the constitution-mandated coverage gate: `pytest --cov=src/cvip/video --cov-fail-under=100`. This feature is not complete until this passes — add targeted tests for any branch it reports as uncovered (Constitution Principle VII)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories
- **User Story 1 (Phase 3)**: Depends on Foundational only
- **User Story 2 (Phase 4)**: Depends on Foundational; layers classification onto the detection loop built in US1 (T021) but adds no new frame-sourcing logic of its own
- **User Story 3 (Phase 5)**: Depends on Foundational; adds cancellation to the same `SceneDetector` from US1 (T021), additive rather than a modification to US1's detection logic
- **Polish (Phase 6)**: Depends on all three user stories being complete

### Within Each User Story

- Tests are written first and must fail before implementation begins
- Data model/errors (Foundational) before any `scene_detection.py` logic
- Core detection loop (T017) before the public factory function (T018), before context-manager wiring (T019), before mid-run failure handling (T020), before boundary/result finalization (T021)
- US2 and US3 both build on US1's T021 as their starting point, but do not depend on each other

### Parallel Opportunities

- T002, T003 (Setup) can run in parallel
- T004, T005 (Foundational) can run in parallel — different files
- T007, T008, T009, T010, T011, T012, T013, T014, T015, T016 (US1 tests) can run in parallel
- T022, T023, T024, T025 (US2 tests) can run in parallel
- T029, T030, T031 (US3 tests) can run in parallel
- T033, T034 (Polish) can run in parallel

---

## Parallel Example: User Story 1

```bash
# Launch all ten US1 tests together (write first, confirm they fail):
Task: "Contract test in tests/contract/test_scene_detection_contract.py"
Task: "Ordered boundary list + diagnostics-count + result-metadata integration test in tests/integration/test_scene_detection_e2e.py"
Task: "Empty boundary list (no-cuts video) integration test in tests/integration/test_scene_detection_e2e.py"
Task: "Frame Extraction Service sourcing unit test in tests/unit/test_scene_detection_validation.py"
Task: "Mid-run failure integration test in tests/integration/test_scene_detection_e2e.py"
Task: "Offline/CPU-only unit test in tests/unit/test_scene_detection_validation.py"
Task: "Determinism integration test in tests/integration/test_scene_detection_e2e.py"
Task: "scene_threshold-is-applied integration test in tests/integration/test_scene_detection_e2e.py"
Task: "boundary_id uniqueness unit test in tests/unit/test_scene_detection_validation.py"
Task: "Single-forward-pass (no backward seek) integration test in tests/integration/test_scene_detection_e2e.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (blocks everything else)
3. Complete Phase 3: User Story 1
4. **STOP and VALIDATE**: confirm boundary detection works correctly, deterministically, offline/CPU-only, against the Video Loader fixtures, sourced only through the Frame Extraction Service in a verified single forward pass, with unique boundary IDs and a correctly-applied configurable threshold, and that an invalid source / mid-run failure is rejected with the right reason
5. This alone is a usable MVP — Replay Detection could be built against a plain (unclassified) boundary list, accepting that replay-transition classification and the explicit time/memory benchmarks aren't validated yet

### Incremental Delivery

1. Setup + Foundational → foundation ready
2. Add User Story 1 → validate independently (MVP: correct, deterministic boundary detection + fail-fast + offline/CPU-only + verified single pass)
3. Add User Story 2 → validate independently (classification + mandatory confidence including ambiguous cases, no second pass)
4. Add User Story 3 → validate independently (time/memory budget + cancellation)
5. Phase 6: Polish, including the mandatory coverage gate (T037)

---

## Notes

- [P] tasks touch different files and have no unmet dependencies
- [Story] label maps each task to its user story for traceability back to spec.md
- Commit after each task or logical group
- Stop at any checkpoint to validate a story independently before moving on
- **PySceneDetect's per-frame API** (research.md Decision 1: driving `ContentDetector.process_frame()` directly rather than `SceneManager.detect_scenes()`) was reasoned from the library's documented architecture rather than empirically verified against a running installation during planning (offline environment). T007/T010 (contract + frame-sourcing tests) are what actually prove this out during implementation; if `process_frame()`'s exact signature or return shape differs from expectations, adjust T017 accordingly — this would not change any other task's scope.
- **FR-017 (CPU-only)**: partially covered directly (T012's static/behavioral check that no GPU-specific OpenCV API is used) and additionally satisfied by construction — no GPU library or code path exists anywhere in this feature, matching Video Loader's and the Frame Extraction Service's own precedent for this same requirement.
- **FR-013 (result usable by other modules within the same run without re-running detection)**: intentionally not independently verifiable within this feature's own test suite — its truth is proven out when Replay Detection is actually built against this feature's contract (`contracts/scene_detection_contract.md`) in its own future feature, the same way the Frame Extraction Service's own FR-013 was deferred to its first consumer rather than tested in isolation. Deferred by design, not forgotten.
- **FR-021 (must not determine whether a segment is an actual replay)**: not independently testable as a behavior (there is no "wrong" output to assert against for something the feature never attempts) — satisfied by construction and enforced by code review (T035's contract re-check) rather than a dedicated test, the same way FR-013 above is handled.
