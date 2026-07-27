---

description: "Task list template for feature implementation"
---

# Tasks: Frame Extraction Service

**Input**: Design documents from `/specs/002-frame-extraction-service/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/frame_extraction_contract.md](./contracts/frame_extraction_contract.md), [quickstart.md](./quickstart.md)

**Tests**: Included — constitution Principle VII (Test-First Development) requires contract tests at module boundaries, tests written before implementation, and 100% coverage on critical paths (enforced by T033).

**Organization**: Tasks are grouped by user story (from spec.md) to enable independent implementation and testing of each story.

**Note on shared infrastructure**: This feature reuses Video Loader's (`specs/001-video-loader/`) existing `tests/fixtures/video_loader/` fixtures, `src/cvip/common/diagnostics.py` emitter, and `pyproject.toml` pytest/coverage configuration — no new fixtures, diagnostics module, or test-runner config are created here.

**Revision note**: This task list was revised after `/speckit-analyze` surfaced 8 findings (1 CRITICAL, 2 HIGH, 4 MEDIUM, 1 LOW). All were addressed: the offline/CPU-only coverage gap (T012), the determinism coverage gap (T013), the throughput-consistency coverage gap (T021), the happy-path diagnostics-count assertion (folded into T008), the stale `specs/technical_plan.md` open question (fixed directly in that doc), the buffer-reuse contract's testability (documented in Notes, not force-tested), the FR-012/FR-013 deferral classification (documented in Notes), and SC-002's memory tolerance (pinned to a concrete 150MB ceiling in spec.md). These additions shifted all task IDs from T012 onward relative to the original version.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)

## Path Conventions

Single project, per plan.md Project Structure: new files in `src/cvip/video/` (alongside Video Loader's existing files), tests in the existing `tests/{contract,integration,unit,benchmark}/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization for this feature's new files only — test directories, pytest config, and fixtures already exist from Video Loader

- [X] T001 Create `src/cvip/video/{frame_extraction_models.py,frame_extraction_errors.py,frame_extraction.py}` as empty modules per plan.md Source Code layout
- [X] T002 [P] Create empty test file placeholders: `tests/contract/test_frame_extraction_contract.py`, `tests/integration/test_frame_extraction_e2e.py`, `tests/unit/test_frame_extraction_validation.py`, `tests/benchmark/test_frame_extraction_performance.py`
- [X] T003 [P] Confirm `pyproject.toml`'s existing `pytest` `testpaths` and `--cov=src/cvip/video` coverage scope already cover this feature's new files (they live in the same subpackage as Video Loader) — no config changes expected; document in a one-line comment if any gap is found — **confirmed, no gap**: `testpaths` already lists all four dirs and `--cov=src/cvip/video` is directory-scoped

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core types every user story depends on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T004 [P] Implement `SamplingMode`, `ExtractionRequest` (including its validation rules: exactly one of `rate_fps`/`frame_indices`/`timestamps_seconds` populated per `mode`, and frame-index-over-timestamp resume precedence), `FrameContext`, and `ExtractionProgress` per [data-model.md](./data-model.md) in `src/cvip/video/frame_extraction_models.py`
- [X] T005 [P] Implement the `ExtractionFailureReason` enum (`SOURCE_NOT_VALIDATED`, `RESUME_POINT_OUT_OF_RANGE`, `SOURCE_UNAVAILABLE_MID_RUN`, `DECODE_FAILURE_MID_RUN`) per [contracts/frame_extraction_contract.md](./contracts/frame_extraction_contract.md) in `src/cvip/video/frame_extraction_errors.py`
- [X] T006 Implement a diagnostics-building helper (module_name `"video.frame_extraction"`) reusing `src/cvip/common/diagnostics.py`'s `ExecutionDiagnostics`/`DiagnosticsTracker` (no new diagnostics module) in `src/cvip/video/frame_extraction.py` (depends on T004, T005)

**Checkpoint**: Foundation ready — user story implementation can now begin

---

## Phase 3: User Story 1 - Request frames from a validated video at a chosen rate (Priority: P1) 🎯 MVP

**Goal**: Given a successful `LoadResult`, `extract_frames()` yields correctly-indexed, correctly-timestamped `FrameContext` objects in any of the four sampling modes, deterministically, offline and CPU-only, and fails fast on a non-validated source or a mid-run problem.

**Independent Test**: Request `FULL` and `FIXED_INTERVAL` frames from the valid Video Loader fixtures and confirm correct indices/timestamps; request `FRAME_LIST`/`TIMESTAMP_LIST` and confirm dedup/sort/nearest-frame behavior; confirm a failed `LoadResult` is rejected immediately; confirm repeated runs are identical; confirm no network dependency.

### Tests for User Story 1 ⚠️

> Write these tests FIRST, ensure they FAIL before implementation

- [X] T007 [P] [US1] Contract test asserting `extract_frames()` returns a `FrameExtractor` matching [contracts/frame_extraction_contract.md](./contracts/frame_extraction_contract.md)'s shape, and that a `FAILURE` `LoadResult` yields `SOURCE_NOT_VALIDATED` without any file access, in `tests/contract/test_frame_extraction_contract.py`
- [X] T008 [P] [US1] Integration test: `FULL` mode and `FIXED_INTERVAL` mode (1 FPS) against the Video Loader `valid_short.mp4`/`.mkv` fixtures yield the correct `frame_index`/`timestamp_seconds` sequences; **also assert exactly one `ExtractionDiagnostics` record is emitted for this successful run** (FR-010/SC-006 happy-path case), in `tests/integration/test_frame_extraction_e2e.py`
- [X] T009 [P] [US1] Integration test: `FRAME_LIST` mode with an unordered list containing a duplicate yields the correct deduplicated, ascending sequence; `TIMESTAMP_LIST` mode yields the nearest real decoded frame with no interpolation, in `tests/integration/test_frame_extraction_e2e.py`
- [X] T010 [P] [US1] Unit test asserting the reported timestamp for a sampled frame comes from the actually-decoded frame (mock `cv2.VideoCapture` so the seeked frame's real timestamp disagrees with a naive `frame_index / native_fps` calculation; assert the real one wins) per FR-004/research.md, in `tests/unit/test_frame_extraction_validation.py`
- [X] T011 [P] [US1] Integration test: the source becoming inaccessible partway through a run yields `SOURCE_UNAVAILABLE_MID_RUN`, and a corrupted frame partway through yields `DECODE_FAILURE_MID_RUN` (both via mocking), in `tests/integration/test_frame_extraction_e2e.py`
- [X] T012 [P] [US1] Unit test confirming no network calls are possible during extraction (mock/patch `socket.socket` — and `socket.create_connection` — to raise if called, assert a normal extraction still succeeds) per FR-011, and a static/behavioral check that no GPU-specific API (e.g., no `cv2.cuda.*` calls) is used per FR-012, in `tests/unit/test_frame_extraction_validation.py`
- [X] T013 [P] [US1] Integration test asserting determinism (FR-006/SC-003): run the identical `ExtractionRequest` against the same fixture 3 times and assert the `frame_index`/`timestamp_seconds` sequence — including ordering — is byte-for-byte identical across all 3 runs, in `tests/integration/test_frame_extraction_e2e.py`

### Implementation for User Story 1

- [X] T014 [US1] Implement `FrameExtractor`'s core seek-based retrieval (seek to a computed target frame index via `CAP_PROP_POS_FRAMES`, decode, read the actual timestamp via `CAP_PROP_POS_MSEC`) and `FULL`/`FIXED_INTERVAL` mode logic in `src/cvip/video/frame_extraction.py` (depends on T004)
- [X] T015 [US1] Implement `FRAME_LIST` and `TIMESTAMP_LIST` mode logic — sort/de-duplicate the caller's list, skip out-of-range entries with a warning, select the nearest decoded frame for timestamp requests — in `src/cvip/video/frame_extraction.py` (depends on T014)
- [X] T016 [US1] Implement the `extract_frames()` factory function and the `SOURCE_NOT_VALIDATED` rejection path for a non-`SUCCESS` `LoadResult` in `src/cvip/video/frame_extraction.py` (depends on T005, T015)
- [X] T017 [US1] Implement `FrameExtractor` as a context manager (`__enter__`/`__exit__`: release `VideoCapture`, build and emit the diagnostics record via T006's helper) in `src/cvip/video/frame_extraction.py` (depends on T006, T016)
- [X] T018 [US1] Implement mid-run failure detection, mapping an `OSError`/inaccessible-source condition to `SOURCE_UNAVAILABLE_MID_RUN` and a decode failure to `DECODE_FAILURE_MID_RUN` in `src/cvip/video/frame_extraction.py` (depends on T017)

**Checkpoint**: User Story 1 is fully functional and independently testable — all four sampling modes work correctly against a validated video, deterministically, offline/CPU-only, and fail fast on an invalid source or mid-run problem.

---

## Phase 4: User Story 2 - Extraction stays within the memory budget regardless of match length (Priority: P2)

**Goal**: Peak memory during extraction stays at or under 150MB (SC-002) regardless of video duration, and throughput is consistent run-to-run (SC-008).

**Independent Test**: Compare peak memory extracting at the same rate from a short fixture vs. the multi-hour fixture, confirming both are ≤150MB; run the same extraction multiple times and confirm consistent timing.

### Tests for User Story 2 ⚠️

- [X] T019 [P] [US2] Benchmark test asserting peak memory for `FIXED_INTERVAL` extraction against both `valid_short.mp4` and `multi_hour.mp4` stays at or under 150MB (SC-002), in `tests/benchmark/test_frame_extraction_performance.py`
- [X] T020 [P] [US2] Unit test asserting only one frame is decoded/held at a time — no pre-buffering of frames ahead of what the caller has consumed, in `tests/unit/test_frame_extraction_validation.py`
- [X] T021 [P] [US2] Benchmark test asserting throughput consistency (SC-008): run the identical extraction request against the same fixture 3 times, record each run's duration, and assert all durations fall within an acceptable tolerance of their mean (e.g., within ±25%) — protects against future performance regressions, in `tests/benchmark/test_frame_extraction_performance.py`

### Implementation for User Story 2

- [X] T022 [US2] Review `src/cvip/video/frame_extraction.py` to confirm no unbounded buffering (single current-frame retention only, no materializing the full requested sequence into a list) and fix any finding (depends on T018) — **reviewed, no fix needed**: `_resolve_targets` materializes a list of target *frame indices* (small integers, ~3.5MB even for 126,000 frames), not frame *data*; `_retrieve_frame` decodes exactly one frame per call, returned immediately, with no additional buffering

**Checkpoint**: User Stories 1 AND 2 both work independently — correct sampling, memory stays within the 150MB budget, and throughput is consistent across repeated runs.

---

## Phase 5: User Story 3 - Observe progress, cancel, and resume an interrupted extraction (Priority: P3)

**Goal**: `FrameExtractor.progress` is readable at any point; `.cancel()` stops cleanly and still emits diagnostics; a new request with `resume_from_frame_index` picks up where a previous one left off.

**Independent Test**: Read progress partway through a run, cancel it, note the last frame index received, and confirm a new request resuming from `last_index + 1` never re-yields an earlier frame.

### Tests for User Story 3 ⚠️

- [X] T023 [P] [US3] Unit test asserting `ExtractionProgress` fields (`processed_frames`, `total_frames`, `processed_seconds`, `total_duration_seconds`, `percent_complete`) update correctly as iteration proceeds, in `tests/unit/test_frame_extraction_validation.py`
- [X] T024 [P] [US3] Integration test: calling `.cancel()` mid-extraction stops further iteration, releases resources, and emits exactly one diagnostics record summarizing the partial run, in `tests/integration/test_frame_extraction_e2e.py`
- [X] T025 [P] [US3] Integration test: `resume_from_frame_index` resumes correctly (inclusive, never re-yields a prior frame); a resume point beyond the video's range yields `RESUME_POINT_OUT_OF_RANGE`; supplying both a frame index and a timestamp resolves via frame-index precedence, in `tests/integration/test_frame_extraction_e2e.py`

### Implementation for User Story 3

- [X] T026 [US3] Implement the `FrameExtractor.progress` property, computing an `ExtractionProgress` snapshot on demand, in `src/cvip/video/frame_extraction.py` (depends on T018)
- [X] T027 [US3] Implement `FrameExtractor.cancel()`, wired into the iteration loop and `__exit__` so cancellation and normal exhaustion share the same cleanup/diagnostics path, in `src/cvip/video/frame_extraction.py` (depends on T026)
- [X] T028 [US3] Implement `resume_from_frame_index`/`resume_from_timestamp_seconds` handling — precedence rule and `RESUME_POINT_OUT_OF_RANGE` validation — in `src/cvip/video/frame_extraction.py` (depends on T027)

**Checkpoint**: All three user stories are independently functional — correct sampling, bounded memory, consistent throughput, and observable/cancellable/resumable extraction.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Improvements and gates that affect the whole feature, not any single story

- [X] T029 [P] Run all four [quickstart.md](./quickstart.md) scenarios manually on target-class hardware (or the closest available) and record pass/fail results in `specs/002-frame-extraction-service/quickstart.md`
- [X] T030 [P] Add docstrings to all public functions/classes in `src/cvip/video/{frame_extraction_models,frame_extraction_errors,frame_extraction}.py`
- [X] T031 Re-run `tests/contract/test_frame_extraction_contract.py` after US2 and US3 changes to confirm no regression against the contract
- [X] T032 Run the full test suite (`pytest`) and confirm all tests pass, including Video Loader's existing tests (regression check across both features now sharing `src/cvip/video/`)
- [X] T033 Run the constitution-mandated coverage gate: `pytest --cov=src/cvip/video --cov-fail-under=100`. This feature is not complete until this passes — add targeted tests for any branch it reports as uncovered (Constitution Principle VII)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories
- **User Story 1 (Phase 3)**: Depends on Foundational only
- **User Story 2 (Phase 4)**: Depends on Foundational; benchmarks/reviews the `FrameExtractor` built in US1 (T018) but adds no new branching logic of its own
- **User Story 3 (Phase 5)**: Depends on Foundational; extends the same `FrameExtractor` from US1 (T018) with progress/cancel/resume, which are additive, not modifications to US1's sampling logic
- **Polish (Phase 6)**: Depends on all three user stories being complete

### Within Each User Story

- Tests are written first and must fail before implementation begins
- Data model/errors (Foundational) before any `frame_extraction.py` logic
- Core seek-based retrieval (T014) before the mode-specific logic built on it (T015), before the public factory function (T016), before context-manager wiring (T017), before mid-run failure handling (T018)
- US2 and US3 both build on US1's T018 as their starting point, but do not depend on each other

### Parallel Opportunities

- T002, T003 (Setup) can run in parallel
- T004, T005 (Foundational) can run in parallel — different files
- T007, T008, T009, T010, T011, T012, T013 (US1 tests) can run in parallel
- T019, T020, T021 (US2 tests) can run in parallel
- T023, T024, T025 (US3 tests) can run in parallel
- T029, T030 (Polish) can run in parallel

---

## Parallel Example: User Story 1

```bash
# Launch all seven US1 tests together (write first, confirm they fail):
Task: "Contract test in tests/contract/test_frame_extraction_contract.py"
Task: "FULL/FIXED_INTERVAL + diagnostics-count integration test in tests/integration/test_frame_extraction_e2e.py"
Task: "FRAME_LIST/TIMESTAMP_LIST integration test in tests/integration/test_frame_extraction_e2e.py"
Task: "Actual-timestamp-wins unit test in tests/unit/test_frame_extraction_validation.py"
Task: "Mid-run failure integration test in tests/integration/test_frame_extraction_e2e.py"
Task: "Offline/CPU-only unit test in tests/unit/test_frame_extraction_validation.py"
Task: "Determinism integration test in tests/integration/test_frame_extraction_e2e.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (blocks everything else)
3. Complete Phase 3: User Story 1
4. **STOP and VALIDATE**: confirm all four sampling modes work correctly, deterministically, offline/CPU-only, against the Video Loader fixtures, and that an invalid source / mid-run failure is rejected with the right reason
5. This alone is a usable MVP — Scene Detection, Replay Detection, and Scoreboard OCR could all be built against it, accepting that progress/cancel/resume and the explicit memory/throughput benchmarks aren't validated yet

### Incremental Delivery

1. Setup + Foundational → foundation ready
2. Add User Story 1 → validate independently (MVP: correct, deterministic sampling + fail-fast + offline/CPU-only)
3. Add User Story 2 → validate independently (150MB memory budget + consistent throughput on the real multi-hour fixture)
4. Add User Story 3 → validate independently (progress, cancellation, resume)
5. Phase 6: Polish, including the mandatory coverage gate (T033)

---

## Notes

- [P] tasks touch different files and have no unmet dependencies
- [Story] label maps each task to its user story for traceability back to spec.md
- Commit after each task or logical group
- Stop at any checkpoint to validate a story independently before moving on
- **Deferred by design, not forgotten**: shared/broadcast decoding across simultaneous callers (e.g., Scene Detection and Scoreboard OCR extracting from the same video at the same time) is explicitly out of scope for this feature per spec.md's Assumptions and research.md's decision — each request performs its own independent pass. This has now also been reflected back into `specs/technical_plan.md` (previously stale on this point). Revisit only if the aggregate `cvip analyze` time budget proves too tight once Modules 2-4 are benchmarked; no task in this list is expected to close that gap.
- **PySceneDetect integration** (how Module 2/Scene Detection adapts to consume `FrameContext`, or reimplements scene-cut detection on top of it) is explicitly that future feature's own concern, per research.md's "Open item intentionally not resolved here" — not a gap in this task list.
- **FR-012 (CPU-only)**: partially covered directly (T012's static/behavioral check that no GPU-specific OpenCV API is used) and additionally satisfied by construction — no GPU library or code path exists anywhere in this feature, matching Video Loader's own precedent for this same requirement.
- **FR-013 (usable by multiple independent pipeline modules without their own video-reading logic)**: intentionally not independently verifiable within this feature's own test suite — its truth is proven out when Scene Detection, Replay Detection, and Scoreboard OCR are actually built against this service's contract (`contracts/frame_extraction_contract.md`) in their own future features, the same way Video Loader's FR-006 (downstream modules only accepting a successful `LoadResult`) was deferred to its first consumer rather than tested in isolation.
- **FR-005's buffer-reuse/invalidation clause** ("the service MAY reuse or invalidate a previous frame's underlying buffer once the caller advances"): this is a permission granted to the implementation, not an externally-observable behavior a consumer can meaningfully assert on — a test could only confirm the service is *allowed* to reuse a buffer, not force it to, and asserting the opposite (that data past a certain point becomes invalid) would pin the test to a specific internal implementation choice rather than the contract itself. Documented here as an implementation contract, consistent with G5's resolution, rather than backed by a dedicated test. T020 (no pre-buffering ahead) already covers the related, externally-observable memory-boundedness property this clause exists to support.
