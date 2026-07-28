---

description: "Task list template for feature implementation"
---

# Tasks: Scoreboard OCR

**Input**: Design documents from `/specs/005-scoreboard-ocr/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/scoreboard_ocr_contract.md](./contracts/scoreboard_ocr_contract.md), [quickstart.md](./quickstart.md)

**Tests**: Included — constitution Principle VII (Test-First Development) requires contract tests at module boundaries, tests written before implementation, and 100% coverage on critical paths (enforced by T054).

**Organization**: Tasks are grouped by user story (from spec.md) to enable independent implementation and testing of each story.

**Note on shared infrastructure**: This feature reuses Video Loader's (`specs/001-video-loader/`) existing `tests/fixtures/video_loader/` fixtures, the Frame Extraction Service's (`specs/002-frame-extraction-service/`) `extract_frames()`/`FrameContext` for all frame access, `src/cvip/common/diagnostics.py`'s emitter, and `pyproject.toml`'s existing pytest/coverage configuration — no new fixtures, diagnostics module, or test-runner config are created here. Unlike Replay Detection, this feature does not depend on Scene Detection's or Replay Detection's output — only a `LoadResult`.

**Note on a pre-existing dependency gap**: `pytesseract` is pinned in `requirements.txt` but not currently installed in the active dev environment (the native Tesseract binary is). T001 includes installing it — this is a setup step, not a design decision (research.md).

**Revision note**: This task list was revised after `/speckit-analyze` surfaced 4 findings (0 CRITICAL/HIGH, 2 MEDIUM, 2 LOW). All were addressed: FR-021's diagnostics definition (and data-model.md's matching entity) now explicitly includes the ROI-unchanged-skip count, with T046 extended to verify it (F1); a dedicated happy-path full-field-parse test (T026) and a text-field-change-does-not-reduce-confidence test (T027) were added to US1 (E1, E2); and two "satisfied by construction" Notes entries were added for FR-008 and FR-027, matching FR-022/FR-023's existing treatment (D1). These additions shifted all task IDs from T026 onward relative to the original version.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)

## Path Conventions

Single project, per plan.md Project Structure: new files in `src/cvip/video/` (alongside Video Loader, the Frame Extraction Service, Scene Detection, and Replay Detection), tests in the existing `tests/{contract,integration,unit,benchmark}/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization for this feature's new files only — test directories, pytest config, and fixtures already exist from the four prior features

- [X] T001 Confirm `pytesseract` is installed in the active dev environment (`pip show pytesseract`; if missing, `pip install -r requirements.txt`) and confirm the native Tesseract binary is on `PATH` (`tesseract --version`) — a pre-existing dependency gap noted in research.md, not a new prerequisite
- [X] T002 Create `src/cvip/video/{scoreboard_ocr_models.py,scoreboard_ocr_errors.py,scoreboard_ocr.py}` as empty modules per plan.md Source Code layout
- [X] T003 [P] Create empty test file placeholders: `tests/contract/test_scoreboard_ocr_contract.py`, `tests/integration/test_scoreboard_ocr_e2e.py`, `tests/unit/test_scoreboard_ocr_validation.py`, `tests/benchmark/test_scoreboard_ocr_performance.py`
- [X] T004 [P] Confirm `pyproject.toml`'s existing `pytest` `testpaths` and `--cov=src/cvip/video` coverage scope already cover this feature's new files (same subpackage as the four prior features) — no config changes expected; document in a one-line comment if any gap is found

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core types every user story depends on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T005 [P] Implement the `ScoreboardOcrFailureReason` enum (`SOURCE_NOT_VALIDATED`, `INVALID_OCR_CONFIGURATION`, `SOURCE_UNAVAILABLE_MID_RUN`, `DECODE_FAILURE_MID_RUN`), a `ScoreboardOcrError` exception carrying it, and the `ValidationFailureReason` enum (`RUNS_DECREASED`, `WICKETS_DECREASED`, `INVALID_OVER_SEQUENCE`, `INVALID_BALL_NUMBER`, `PLAYER_PARSE_FAILED`), per [contracts/scoreboard_ocr_contract.md](./contracts/scoreboard_ocr_contract.md) and [data-model.md](./data-model.md), in `src/cvip/video/scoreboard_ocr_errors.py`
- [X] T006 [P] Implement `ScoreboardOcrRequest`, `OCREvidence`, `ScoreboardSample`, and `ScoreboardOcrResult` per [data-model.md](./data-model.md) as frozen (immutable) dataclasses with plain, self-contained field types (no references to run-internal state) in `src/cvip/video/scoreboard_ocr_models.py`
- [X] T007 Implement a diagnostics-building helper (module_name `"video.scoreboard_ocr"`) reusing `src/cvip/common/diagnostics.py`'s `ExecutionDiagnostics`/`DiagnosticsTracker` (no new diagnostics module) in `src/cvip/video/scoreboard_ocr.py` (depends on T005, T006)

**Checkpoint**: Foundation ready — user story implementation can now begin

---

## Phase 3: User Story 1 - Extract a complete, never-failing raw scoreboard timeline (Priority: P1) 🎯 MVP

**Goal**: Given a validated `LoadResult`, `extract_scoreboard()` produces exactly one `ScoreboardSample` (plus an internal `OCREvidence` record) per sampled frame — preprocessing the configured ROI, running Tesseract OCR, structurally parsing the fields, and validating them against cricket-scoring rules (with the innings-transition heuristic and last-accepted-reading comparison) — never hard-failing on a single bad reading, while a ROI-unchanged skip keeps the whole run within budget, deterministically, offline and CPU-only, and rejects an unvalidated source without touching a frame.

**Independent Test**: Run extraction against the Video Loader fixtures and confirm every sampled frame produces a sample with both confidence fields correctly reflecting an undetectable region, a low-confidence reading, a rule-violating reading, or a clean reading, and that a failed `LoadResult` is rejected immediately.

### Tests for User Story 1 ⚠️

> Write these tests FIRST, ensure they FAIL before implementation

- [X] T008 [P] [US1] Contract test asserting `extract_scoreboard()` returns a `ScoreboardOcrExtractor` matching [contracts/scoreboard_ocr_contract.md](./contracts/scoreboard_ocr_contract.md)'s shape, and that a `FAILURE` `LoadResult` yields `SOURCE_NOT_VALIDATED` without any file access, in `tests/contract/test_scoreboard_ocr_contract.py`
- [X] T009 [P] [US1] Integration test: extraction against the Video Loader `valid_short.mp4` fixture yields a structurally valid `ScoreboardOcrResult` — one sample per sampled frame, ordered, each with both confidence fields in `[0.0, 1.0]` — and exactly one `ScoreboardOcrDiagnostics` record for the successful run, in `tests/integration/test_scoreboard_ocr_e2e.py`
- [X] T010 [P] [US1] Unit test asserting the preprocessing pipeline applies grayscale → upscale → threshold in that order (research.md), with each stage independently toggleable per the request's `preprocess_grayscale`/`preprocess_upscale`/`preprocess_threshold` settings, in `tests/unit/test_scoreboard_ocr_validation.py`
- [X] T011 [P] [US1] Unit test: a sampled frame whose scoreboard region is not visually detectable yields `ocr_confidence = 0.0` and empty `raw_text`, without failing the run (FR-010), in `tests/unit/test_scoreboard_ocr_validation.py`
- [X] T012 [P] [US1] Unit test: a reading whose `ocr_confidence` falls below the configured `min_confidence` is recorded exactly as observed, not discarded or corrected (FR-011), in `tests/unit/test_scoreboard_ocr_validation.py`
- [X] T013 [P] [US1] Unit test asserting per-field OCR confidence is correctly attributed from `pytesseract.image_to_data()`'s per-token confidences (research.md): given known synthetic token/confidence data, `OCREvidence.field_confidences` reflects the attributed tokens' confidences, and a field with no attributable token is absent from the mapping rather than fabricated (FR-029), in `tests/unit/test_scoreboard_ocr_validation.py`
- [X] T014 [P] [US1] Unit test: an "over.ball" raw-text reading (e.g., "12.3") splits into `over_number = 12` and `ball_in_over = 3` (FR-007), in `tests/unit/test_scoreboard_ocr_validation.py`
- [X] T015 [P] [US1] Unit test: a `ball_in_over` value outside its valid range yields `parse_confidence = 0.0` with `ValidationFailureReason.INVALID_BALL_NUMBER` (FR-013, FR-031), in `tests/unit/test_scoreboard_ocr_validation.py`
- [X] T016 [P] [US1] Unit test asserting each of the three numeric monotonic-rule violations independently — `runs` decreasing (`RUNS_DECREASED`), `wickets` decreasing (`WICKETS_DECREASED`), `over_number` decreasing (`INVALID_OVER_SEQUENCE`) — each yields `parse_confidence = 0.0` with the matching `ValidationFailureReason` (FR-013, FR-031), in `tests/unit/test_scoreboard_ocr_validation.py`
- [X] T017 [P] [US1] Unit test asserting the innings-transition heuristic: a reading whose `wickets` AND `runs` both drop relative to the last accepted reading has the monotonic checks suppressed for that comparison and is accepted if otherwise valid (FR-014), in `tests/unit/test_scoreboard_ocr_validation.py`
- [X] T018 [P] [US1] Unit test: a reading whose `batter` field cannot be structurally parsed from the raw OCR text at all yields `parse_confidence = 0.0` with `ValidationFailureReason.PLAYER_PARSE_FAILED` (FR-030, FR-031), in `tests/unit/test_scoreboard_ocr_validation.py`
- [X] T019 [P] [US1] Unit test: the first reading of a run (no prior accepted reading to compare against) is never rejected by the rule-consistency checks (FR-016), in `tests/unit/test_scoreboard_ocr_validation.py`
- [X] T020 [P] [US1] Unit test asserting rule validation compares against the last *accepted* reading, not merely the immediately preceding one: a rejected reading does not become the new comparison baseline, preventing a single bad reading from cascading into repeated false rejections (FR-012), in `tests/unit/test_scoreboard_ocr_validation.py`
- [X] T021 [P] [US1] Unit test asserting the ROI-unchanged skip (research.md Decision 1): given two consecutive sampled frames with pixel-identical ROIs, the second sample's fields, confidences, and `OCREvidence` are reused verbatim from the first (aside from `timestamp_seconds`), and the OCR stage is not invoked for the skipped frame (mock/spy), in `tests/unit/test_scoreboard_ocr_validation.py`
- [X] T022 [P] [US1] Unit test confirming frames are sourced exclusively via `extract_frames()`'s `FrameContext` (mock/spy) and that `cv2.VideoCapture` is never constructed directly by this feature's code (FR-003), that no network calls are possible during extraction (mock `socket.socket`/`socket.create_connection`, FR-025), and a static check that no GPU-specific API (`cv2.cuda.*`) is used (FR-026), in `tests/unit/test_scoreboard_ocr_validation.py`
- [X] T023 [P] [US1] Integration test asserting determinism (FR-020/SC-006): run the identical `ScoreboardOcrRequest` against the same fixture 3 times and assert the sample sequence — including both confidence fields, and including any ROI-unchanged-skip samples — is identical across all 3 runs, in `tests/integration/test_scoreboard_ocr_e2e.py`
- [X] T024 [P] [US1] Integration test: a video whose scoreboard region is undetectable throughout still completes normally with a full-length sample sequence (every sample `ocr_confidence = 0.0`) rather than failing or producing a shortened timeline (FR-006, FR-010), in `tests/integration/test_scoreboard_ocr_e2e.py`
- [X] T025 [P] [US1] Unit test asserting `OCREvidence` is preserved internally for every sample with `raw_text`, per-field confidences, `parsed_fields`, `validation_passed`, and `validation_failure_reason` all populated appropriately (FR-029), in `tests/unit/test_scoreboard_ocr_validation.py`
- [X] T026 [P] [US1] **Happy-path unit test**: given a deterministic, well-formed synthetic OCR result covering all 7 extractable fields (`runs`, `wickets`, `over_number`/`ball_in_over`, `batter`, `non_striker`, `bowler`, `run_rate`), assert every field parses to its expected value, `parse_confidence` is high (no validation failure of any kind, `validation_failure_reason` is `null`), and `ocr_confidence` reflects the (mocked) high per-token confidences — this is this feature's primary positive-path verification, distinct from T009's purely structural check (analysis finding E1), in `tests/unit/test_scoreboard_ocr_validation.py`
- [X] T027 [P] [US1] Unit test asserting text fields carry no *historical* rule-consistency check (spec.md Assumptions, analysis finding E2): given two otherwise-valid consecutive readings where `batter` (or `non_striker`/`bowler`) genuinely changes between them, assert the second reading's `parse_confidence` is unaffected and it is still accepted — distinct from T018's *unparseable*-name case, in `tests/unit/test_scoreboard_ocr_validation.py`

### Implementation for User Story 1

- [X] T028 [US1] Implement the preprocessing pipeline (grayscale → upscale → threshold, each independently toggleable per request settings) in `src/cvip/video/scoreboard_ocr.py` (depends on T006)
- [X] T029 [US1] Implement the OCR stage: `pytesseract.image_to_data()` against the preprocessed ROI, producing `raw_text`, overall `ocr_confidence`, and per-token confidences available for field attribution (research.md) in `src/cvip/video/scoreboard_ocr.py` (depends on T028)
- [X] T030 [US1] Implement the structured-parsing stage: locate and parse `runs`, `wickets`, `over_number`/`ball_in_over` (from the "over.ball" reading), `batter`, `non_striker`, `bowler`, and `run_rate` from the OCR tokens, producing `parsed_fields` and attributing per-field confidence where possible (FR-007, FR-030) in `src/cvip/video/scoreboard_ocr.py` (depends on T029)
- [X] T031 [US1] Implement the Last-Accepted-Reading Tracker and the cricket-rule validation stage — the `runs`/`wickets`/`over_number`/`ball_in_over` monotonic checks, the innings-transition suppression heuristic (FR-014), and `PLAYER_PARSE_FAILED` for an unparseable essential field — producing `validation_passed`/`validation_failure_reason` and the final `parse_confidence` (FR-012, FR-013, FR-015, FR-016, FR-030, FR-031) in `src/cvip/video/scoreboard_ocr.py` (depends on T030)
- [X] T032 [US1] Implement the ROI-Unchanged Skip mechanism (`cv2.absdiff`-based comparison against the previous sampled frame's raw ROI; reuse the previous sample verbatim aside from timestamp when unchanged) in `src/cvip/video/scoreboard_ocr.py` (depends on T031)
- [X] T033 [US1] Implement the core extraction loop: consume `extract_frames()` at the platform's configured 1 FPS rate, crop to the configured ROI each sampled frame, apply the ROI-unchanged skip check, run the preprocessing/OCR/parsing/validation pipeline when not skipped, and assemble one `ScoreboardSample` + `OCREvidence` per sampled frame in `src/cvip/video/scoreboard_ocr.py` (depends on T032)
- [X] T034 [US1] Implement the `extract_scoreboard()` factory function and the `SOURCE_NOT_VALIDATED` rejection path for a non-`SUCCESS` `LoadResult` in `src/cvip/video/scoreboard_ocr.py` (depends on T005, T033)
- [X] T035 [US1] Implement `ScoreboardOcrExtractor` as a context manager (`__enter__`/`__exit__`: release the underlying `FrameExtractor`, build and emit the diagnostics record via T007's helper) in `src/cvip/video/scoreboard_ocr.py` (depends on T007, T034)

**Checkpoint**: User Story 1 is fully functional and independently testable — every sampled frame yields exactly one sample via the full preprocessing/OCR/parsing/validation pipeline (with the ROI-unchanged skip keeping it efficient), never hard-failing on a bad reading, deterministically, offline/CPU-only, and an invalid source is rejected without touching a frame.

---

## Phase 4: User Story 2 - Produce a timeline usable by a later, separate module (Priority: P2)

**Goal**: The extraction result's shape is fully self-contained (plain values, no references to run-internal state) and carries a source-video identifier, so Event Detection can consume it without any of this run's in-memory state (including the ROI-unchanged-skip and last-accepted-reading tracker state) still existing.

**Independent Test**: Confirm the result's fields are plain, immutable values with no back-reference to the `ScoreboardOcrExtractor` instance, and that `source_video_id` correctly identifies the analyzed video.

### Tests for User Story 2 ⚠️

- [X] T036 [P] [US2] Integration test: a completed `ScoreboardOcrResult`'s `source_video_id` matches the video's own `file_hash` (FR-028), in `tests/integration/test_scoreboard_ocr_e2e.py`
- [X] T037 [P] [US2] Unit test: `ScoreboardSample` and `ScoreboardOcrResult` are frozen dataclasses — attempting to mutate a field after construction raises, and `ScoreboardOcrResult.samples` is a tuple, not a list (US2 Acceptance Scenario 1, FR-028), in `tests/unit/test_scoreboard_ocr_validation.py`

### Implementation for User Story 2

- [X] T038 [US2] Review `src/cvip/video/scoreboard_ocr_models.py` and `src/cvip/video/scoreboard_ocr.py` to confirm `ScoreboardSample`/`ScoreboardOcrResult` are self-contained (frozen, plain field types, no back-references to `ScoreboardOcrExtractor` state, including the ROI-unchanged-skip and last-accepted-reading tracker) and fix any finding (depends on T006, T035)

**Checkpoint**: User Stories 1 AND 2 both work independently — correct, never-failing extraction, plus a result shape safe to hand to a separate later process.

---

## Phase 5: User Story 3 - Complete within budget, and follow platform-standard operational behavior (Priority: P3)

**Goal**: Extraction against a full 3-4 hour match completes within its ~15-25 minute budget share (the platform's single largest cost), decodes the video no more than once, supports cooperative cancellation, and fails fast with one of the taxonomy's four specific reasons on every structural failure path — always emitting exactly one diagnostics record, including for a rejected configuration.

**Independent Test**: Run extraction against the multi-hour fixture and confirm elapsed time and single-pass behavior; separately, force each of the four failure conditions and confirm the matching specific reason plus exactly one diagnostics record; separately, confirm `.cancel()` stops a run cleanly.

### Tests for User Story 3 ⚠️

- [X] T039 [P] [US3] Benchmark test asserting extraction against `multi_hour.mp4` completes within its allotted ~15-25 minute share of the overall analysis budget (SC-004), in `tests/benchmark/test_scoreboard_ocr_performance.py`
- [X] T040 [P] [US3] Integration test asserting single-forward-pass behavior observably (FR-024/SC-005): spy on the underlying `cv2.VideoCapture.set(cv2.CAP_PROP_POS_FRAMES, ...)` calls made during a full extraction run via the Frame Extraction Service, and assert the sequence of seeked positions is strictly increasing with no repeats (accounting for the Frame Extraction Service's own one-time calibration probe, per Replay Detection's own precedent test), in `tests/integration/test_scoreboard_ocr_e2e.py`
- [X] T041 [P] [US3] Integration test: the source becoming inaccessible partway through a run yields `SOURCE_UNAVAILABLE_MID_RUN`, and a corrupted/undecodable frame partway through yields `DECODE_FAILURE_MID_RUN` (both via mocking the underlying `FrameExtractor`), **each asserting exactly one diagnostics record is emitted** (FR-018), in `tests/integration/test_scoreboard_ocr_e2e.py`
- [X] T042 [P] [US3] Integration test: a configuration whose scoreboard ROI is malformed (e.g., a coordinate outside `[0.0, 1.0]`, or a width/height pushing the ROI out of bounds) yields `INVALID_OCR_CONFIGURATION` before any frame is processed, **asserting exactly one diagnostics record is emitted** (FR-017, FR-018), in `tests/integration/test_scoreboard_ocr_e2e.py`
- [X] T043 [P] [US3] Integration test: a configuration whose `preprocess_upscale` is not a positive integer yields `INVALID_OCR_CONFIGURATION` before any frame is processed, with exactly one diagnostics record emitted (FR-017, FR-018) — independent of T042's ROI case, in `tests/integration/test_scoreboard_ocr_e2e.py`
- [X] T044 [P] [US3] Integration test: a configuration whose `min_confidence` is outside `[0.0, 1.0]` yields `INVALID_OCR_CONFIGURATION` before any frame is processed, with exactly one diagnostics record emitted (FR-017, FR-018) — independent of T042/T043's cases, in `tests/integration/test_scoreboard_ocr_e2e.py`
- [X] T045 [P] [US3] Integration test: calling `.cancel()` mid-extraction stops further frame processing, releases resources, and emits exactly one diagnostics record summarizing the partial run, in `tests/integration/test_scoreboard_ocr_e2e.py`
- [X] T046 [P] [US3] Unit test asserting the diagnostics record contains every field FR-021 requires (frames processed, undetectable-region count, average `ocr_confidence`, low-`ocr_confidence` count, average `parse_confidence`, `parse_confidence = 0` count with a `ValidationFailureReason` breakdown, **count of samples served via the ROI-unchanged skip** (analysis finding F1), configuration version, processing duration) for a successful run, **and** that a mid-run or configuration failure's diagnostics still reflect whatever was processed before the failure rather than reporting all-zero counts, in `tests/unit/test_scoreboard_ocr_validation.py`

### Implementation for User Story 3

- [X] T047 [US3] Implement lazy configuration validation (scoreboard ROI bounds; `preprocess_upscale` a positive integer; `min_confidence` within `[0.0, 1.0]` — each validated and reported independently) at the start of `run()`, raising `INVALID_OCR_CONFIGURATION` through the same diagnostics-emitting `_fail()` path used by every other failure reason (matching Replay Detection's own lazy-validation precedent, research.md) in `src/cvip/video/scoreboard_ocr.py` (depends on T034)
- [X] T048 [US3] Implement mid-run failure translation, mapping the underlying `FrameExtractor`'s `ExtractionError` to `SOURCE_UNAVAILABLE_MID_RUN`/`DECODE_FAILURE_MID_RUN`, plus a broad exception handler mapping any other unexpected mid-run processing error to `DECODE_FAILURE_MID_RUN` in `src/cvip/video/scoreboard_ocr.py` (depends on T047)
- [X] T049 [US3] Implement `ScoreboardOcrExtractor.cancel()`, wired into the extraction loop and `__exit__` so cancellation and normal completion share the same cleanup/diagnostics path in `src/cvip/video/scoreboard_ocr.py` (depends on T035)
- [X] T050 [US3] Implement the full fixed diagnostics field list (FR-021) in the diagnostics-building helper, ensuring partial-progress state (frames processed, confidence/validation statistics so far) is finalized and available *before* `_fail()` emits a record on any failure path — not only on normal completion (matching Replay Detection's own precedent fix for this exact class of bug) in `src/cvip/video/scoreboard_ocr.py` (depends on T048, T049)

**Checkpoint**: All three user stories are independently functional — correct, never-failing extraction; a self-contained, persistence-ready result; and within-budget, single-pass, fully-taxonomized, cancellable operation with diagnostics guaranteed on every path.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Improvements and gates that affect the whole feature, not any single story

- [X] T051 [P] Run all four [quickstart.md](./quickstart.md) scenarios manually on target-class hardware (or the closest available) and record pass/fail results in `specs/005-scoreboard-ocr/quickstart.md`
- [X] T052 [P] Add docstrings to all public functions/classes in `src/cvip/video/{scoreboard_ocr_models,scoreboard_ocr_errors,scoreboard_ocr}.py`
- [X] T053 Re-run `tests/contract/test_scoreboard_ocr_contract.py` after US2 and US3 changes to confirm no regression against the contract
- [X] T054 Run the full test suite (`pytest`) and confirm all tests pass, including the four prior features' existing tests (regression check across all five features now sharing `src/cvip/video/`)
- [X] T055 Run the constitution-mandated coverage gate: `pytest --cov=src/cvip/video --cov-fail-under=100`. This feature is not complete until this passes — add targeted tests for any branch it reports as uncovered (Constitution Principle VII)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories
- **User Story 1 (Phase 3)**: Depends on Foundational only
- **User Story 2 (Phase 4)**: Depends on Foundational; reviews the result shape built in US1 (T006, T035) but adds no new extraction logic of its own
- **User Story 3 (Phase 5)**: Depends on Foundational; adds validation/cancellation/failure-handling to the same `ScoreboardOcrExtractor` from US1 (T034, T035), additive rather than a modification to US1's extraction logic
- **Polish (Phase 6)**: Depends on all three user stories being complete

### Within Each User Story

- Tests are written first and must fail before implementation begins
- Data model/errors (Foundational) before any `scoreboard_ocr.py` logic
- Preprocessing (T028) before the OCR stage (T029), before structured parsing (T030), before rule validation (T031), before the ROI-unchanged skip (T032), before the core extraction loop (T033), before the public factory function (T034), before context-manager wiring (T035)
- US2 and US3 both build on US1's T034/T035 as their starting point, but do not depend on each other

### Parallel Opportunities

- T003, T004 (Setup) can run in parallel
- T005, T006 (Foundational) can run in parallel — different files
- T008-T027 (all 20 US1 tests) can run in parallel
- T036, T037 (US2 tests) can run in parallel
- T039-T046 (all 8 US3 tests) can run in parallel
- T051, T052 (Polish) can run in parallel

---

## Parallel Example: User Story 1

```bash
# Launch all twenty US1 tests together (write first, confirm they fail):
Task: "Contract test in tests/contract/test_scoreboard_ocr_contract.py"
Task: "Structural-correctness + diagnostics-count integration test in tests/integration/test_scoreboard_ocr_e2e.py"
Task: "Preprocessing pipeline order unit test in tests/unit/test_scoreboard_ocr_validation.py"
Task: "Undetectable-region unit test in tests/unit/test_scoreboard_ocr_validation.py"
Task: "Low-OCR-confidence-recorded-as-is unit test in tests/unit/test_scoreboard_ocr_validation.py"
Task: "Per-field OCR confidence attribution unit test in tests/unit/test_scoreboard_ocr_validation.py"
Task: "Over-and-ball parsing unit test in tests/unit/test_scoreboard_ocr_validation.py"
Task: "ball_in_over range unit test in tests/unit/test_scoreboard_ocr_validation.py"
Task: "Monotonic-rule-violation unit test (three reasons) in tests/unit/test_scoreboard_ocr_validation.py"
Task: "Innings-transition heuristic unit test in tests/unit/test_scoreboard_ocr_validation.py"
Task: "PLAYER_PARSE_FAILED unit test in tests/unit/test_scoreboard_ocr_validation.py"
Task: "First-reading-exemption unit test in tests/unit/test_scoreboard_ocr_validation.py"
Task: "Last-accepted-reading (not merely prior) unit test in tests/unit/test_scoreboard_ocr_validation.py"
Task: "ROI-unchanged skip unit test in tests/unit/test_scoreboard_ocr_validation.py"
Task: "Frame-sourcing/offline/CPU-only unit test in tests/unit/test_scoreboard_ocr_validation.py"
Task: "Determinism integration test in tests/integration/test_scoreboard_ocr_e2e.py"
Task: "Undetectable-throughout integration test in tests/integration/test_scoreboard_ocr_e2e.py"
Task: "OCREvidence-preserved unit test in tests/unit/test_scoreboard_ocr_validation.py"
Task: "Happy-path full-field-parse unit test in tests/unit/test_scoreboard_ocr_validation.py"
Task: "Text-field-change-does-not-reduce-confidence unit test in tests/unit/test_scoreboard_ocr_validation.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (blocks everything else)
3. Complete Phase 3: User Story 1
4. **STOP and VALIDATE**: confirm every sampled frame produces exactly one sample via the full preprocessing/OCR/parsing/validation pipeline, never hard-failing on a bad reading, deterministically, offline/CPU-only, against the Video Loader fixtures, and that an invalid source is rejected without touching a frame
5. This alone is a usable MVP — Event Detection could be built against a raw scoreboard timeline, accepting that the persistence-readiness guarantees and the explicit budget/failure-taxonomy/cancellation behaviors aren't validated yet

### Incremental Delivery

1. Setup + Foundational → foundation ready
2. Add User Story 1 → validate independently (MVP: correct, deterministic, never-failing raw scoreboard extraction + fail-fast on an invalid source + offline/CPU-only)
3. Add User Story 2 → validate independently (self-contained, persistence-ready result shape)
4. Add User Story 3 → validate independently (time budget, single pass, full failure taxonomy with diagnostics on every path, cancellation)
5. Phase 6: Polish, including the mandatory coverage gate (T055)

---

## Notes

- [P] tasks touch different files and have no unmet dependencies
- [Story] label maps each task to its user story for traceability back to spec.md
- Commit after each task or logical group
- Stop at any checkpoint to validate a story independently before moving on
- **The preprocessing order (grayscale → upscale → threshold), the per-field confidence attribution approach, and the ROI-unchanged skip's exact pixel-difference tolerance** (research.md) are reasoned choices, not empirically tuned against real broadcast footage during planning (offline environment, no golden dataset yet). T009-T027 (structural, parsing, validation, determinism tests) are what prove the *mechanics* work correctly; the *real-world accuracy* of these specific choices against actual broadcast footage is what SC-011's golden-dataset criterion — explicitly out of this feature's own test-suite scope — will eventually validate. If accuracy proves insufficient once that dataset exists, any of these specific choices can be swapped without changing this contract.
- **FR-008 (innings intentionally left unpopulated)**: not independently testable as a positive behavior — `ScoreboardSample` has no `innings` field at all (data-model.md), so there is no code path that could produce a wrong value to assert against. Satisfied by construction, the same treatment as FR-022/FR-023 (analysis finding D1).
- **FR-027 (timestamps reported in seconds)**: satisfied by construction, not by any conversion logic this feature owns — `FrameContext.timestamp_seconds` (Frame Extraction Service's own contract) is already guaranteed to be in seconds regardless of the video's native timestamp units, so this feature only ever passes that value through unchanged (analysis finding D1).
- **FR-026 (CPU-only)**: partially covered directly (T022's static/behavioral check that no GPU-specific OpenCV API is used) and additionally satisfied by construction — no GPU library or code path exists anywhere in this feature, matching every prior module's own precedent for this same requirement.
- **FR-022 (no DB writes)**: not independently testable as a positive behavior (there's no "wrong" output to assert against for something the feature never attempts) — satisfied by construction (no database/SQL code exists anywhere in this feature) and enforced by code review (T053's contract re-check), the same way Replay Detection's analogous FR-026 was handled.
- **FR-023 (must not derive events, highlight-worthiness, or replay classification)**: likewise not independently testable as a positive behavior — this feature's code has no concept of "event," "importance," or "replay" anywhere in it, so there is no code path that could produce a wrong answer to assert against. Satisfied by construction and enforced by code review (T053), the same treatment as FR-022.
- **SC-011 (readings accurate/complete enough for Event Detection to meet the ≥95% detection accuracy target)**: intentionally has no task in this list. It depends on `specs/technical_plan.md`'s golden dataset, a cross-cutting platform deliverable that doesn't exist yet — consistent with how spec.md's own Success Criteria section scoped this from the start, and how Replay Detection's analogous SC-009 was handled.
