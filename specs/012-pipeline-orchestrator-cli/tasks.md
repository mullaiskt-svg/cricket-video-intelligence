---

description: "Task list template for feature implementation"
---

# Tasks: Pipeline Orchestrator and CLI

**Input**: Design documents from `/specs/012-pipeline-orchestrator-cli/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/orchestrator_contract.md](./contracts/orchestrator_contract.md), [contracts/cli_contract.md](./contracts/cli_contract.md), [quickstart.md](./quickstart.md)

**Tests**: Included — constitution Principle VII (Test-First Development) requires contract tests at module boundaries, tests written before implementation, and 100% coverage on critical paths (enforced by T068).

**Organization**: Tasks are grouped by user story (from spec.md) to enable independent implementation and testing of each story.

**Note on test strategy**: Unlike every prior feature, this one's own logic (sequencing, translation, gating) is tested almost entirely with every pipeline module mocked (`mocker.patch`) — Modules 1-10 are already independently correct and independently tested; this feature's tests prove *wiring*, not detection accuracy (research.md Decision 5). Exactly one real, unmocked, slow smoke test exists (T065, `tests/benchmark/`, deselected by default).

**Note on package layout**: `orchestrator.py`/`orchestrator_models.py`/`orchestrator_errors.py`/`cli.py` are new top-level files directly under `src/cvip/`, not a new subpackage — per `specs/technical_plan.md`'s own file-location note (plan.md Structure Decision).

**Note on dependencies**: No new pip package — `argparse` is stdlib, `PyYAML` is already a project dependency (research.md Technical Context).

**Note on Foundational scope**: The native-dependency preflight helper (T006) is built in Foundational because both `analyze()` (US1) and `run_doctor_checks()` (US5) need it (research.md Decision 6) — building it once, early, avoids US5 having to modify US1's own code later.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3, US4, US5)

## Path Conventions

Single project, per plan.md Project Structure: new files directly in `src/cvip/` (not a subpackage), tests in the existing `tests/{contract,unit,benchmark}/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization for this feature's new top-level files

- [X] T001 [P] Create `src/cvip/{orchestrator.py,orchestrator_models.py,orchestrator_errors.py,cli.py}` as empty modules per plan.md Source Code layout
- [X] T002 [P] Create empty test file placeholders: `tests/contract/test_orchestrator_contract.py`, `tests/contract/test_cli_contract.py`, `tests/unit/test_orchestrator_analyze.py`, `tests/unit/test_orchestrator_generate.py`, `tests/unit/test_orchestrator_readonly.py`, `tests/unit/test_cli_analyze.py`, `tests/unit/test_cli_generate.py`, `tests/unit/test_cli_inspect_export.py`, `tests/unit/test_cli_doctor.py`, `tests/benchmark/test_orchestrator_e2e_smoke.py`
- [X] T003 [P] Confirm `pyproject.toml`'s existing `[tool.coverage.run] source = ["src/cvip"]` and pytest `testpaths` already cover these new top-level files (not a subpackage) — no config changes expected; document in a one-line comment if any gap is found

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Failure taxonomy, data model, native-dependency helper, and the CLI's parser/dispatch skeleton every user story depends on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T004 [P] Implement the `OrchestratorFailureReason` enum (9 values: `GENERAL_FAILURE`, `INVALID_ARGUMENTS`, `MISSING_INPUT_FILE`, `UNSUPPORTED_VIDEO_FORMAT`, `MISSING_NATIVE_DEPENDENCY`, `OCR_FAILURE`, `DATABASE_FAILURE`, `EXPORT_FAILURE`, `ALREADY_ANALYZED`) and an `OrchestratorError(reason, exit_code, detail)` exception, per [contracts/orchestrator_contract.md](./contracts/orchestrator_contract.md), [data-model.md](./data-model.md), and research.md Decision 7's mapping table, in `src/cvip/orchestrator_errors.py`
- [X] T005 [P] Implement frozen dataclasses `AnalyzeRequest`, `AnalysisRun`, `GenerateRequest`, `GenerateResult`, `DependencyCheckResult` per [data-model.md](./data-model.md), in `src/cvip/orchestrator_models.py`
- [X] T006 Implement `_check_native_dependencies()` (FFmpeg/Tesseract via `shutil.which`, research.md Decision 6) in `src/cvip/orchestrator.py` (depends on T004, T005)
- [X] T007 [P] Implement `cli.py`'s `argparse` parser scaffolding for all five commands and every flag [contracts/cli_contract.md](./contracts/cli_contract.md) documents (including the not-yet-functional `player`/`team`/`custom`-template-only flags: `--batting`, `--bowling`, `--fielding`, `--complete`) — no command logic wired yet, in `src/cvip/cli.py`
- [X] T008 Implement `cli.py`'s `main()` dispatch skeleton: parse args, load+minimally validate `config/default.yaml`/`--config` (malformed/missing → exit code 2 before any `cvip.orchestrator` call), a single top-level `try`/`except OrchestratorError: sys.exit(error.exit_code)` per command, with each command's actual body raising `NotImplementedError` for now, in `src/cvip/cli.py` (depends on T007)

**Checkpoint**: Foundation ready — user story implementation can now begin

---

## Phase 3: User Story 1 - Analyze a Match Once, End to End (Priority: P1) 🎯 MVP

**Goal**: `cvip analyze` sequences all six analysis stages in order, enforces single-pass analysis via the Event Database, persists each stage's output as it completes, and fails fast with a specific, correctly-mapped exit code on any stage's failure.

**Independent Test**: Run `cvip analyze` against a short real match video with no prior analysis on record. Confirm a database file exists afterward, `cvip inspect-db` against it reports `COMPLETE` with non-zero counts, and re-running without `--force` stops immediately.

### Tests for User Story 1 ⚠️

> Write these tests FIRST, ensure they FAIL before implementation

- [X] T009 [P] [US1] Contract test asserting `orchestrator.analyze()` accepts an `AnalyzeRequest` and returns an `AnalysisRun` matching [contracts/orchestrator_contract.md](./contracts/orchestrator_contract.md)'s shape, in `tests/contract/test_orchestrator_contract.py`
- [X] T010 [P] [US1] Unit test: the full six-stage sequence runs in order with every mocked module called exactly once, correct config-derived field translation into each stage's request, and each stage's output persisted to a real `tmp_path`-backed `EventDatabase` immediately on that stage's completion (FR-001, FR-004, Acceptance Scenario US1-1), in `tests/unit/test_orchestrator_analyze.py`
- [X] T011 [P] [US1] Unit test: a `COMPLETE` match record for the target `file_hash` (seeded beforehand) makes `analyze()` raise `OrchestratorError(ALREADY_ANALYZED)` before any stage after Video Loader is called (FR-002, Acceptance Scenario US1-2), same file
- [X] T012 [P] [US1] Unit test: `force=True` against that same seeded `COMPLETE` record clears prior data (`reset_for_forced_reanalysis` called) and runs a fresh six-stage sequence (FR-003, Acceptance Scenario US1-3), same file
- [X] T013 [P] [US1] Unit test: a mocked mid-sequence stage failure (e.g. Replay Detection) means no later stage is ever called, the match record ends `FAILED`, and `OrchestratorError` carries the correctly-translated reason (FR-005, Acceptance Scenario US1-4), same file
- [X] T014 [P] [US1] Unit test: an `IN_PROGRESS` (not `COMPLETE`) match record for the target `file_hash` also raises `OrchestratorError(ALREADY_ANALYZED)` without `--force` — identical treatment to `COMPLETE` (FR-002, Acceptance Scenario US1-5, spec.md Assumptions), same file
- [X] T015 [P] [US1] Unit test: a missing native dependency (mocked `shutil.which` returning `None`) raises `OrchestratorError(MISSING_NATIVE_DEPENDENCY)` before Scene Detection is ever called (research.md Decision 6), same file
- [X] T016 [P] [US1] Unit test: Video Loader's `FailureReason.FILE_NOT_FOUND`/`UNSUPPORTED_FORMAT` map to `OrchestratorError(MISSING_INPUT_FILE)`/`OrchestratorError(UNSUPPORTED_VIDEO_FORMAT)` respectively, same file
- [X] T017 [P] [US1] Unit test: `cvip analyze`'s `argparse` parser accepts the documented required/optional arguments and rejects a missing `video_path` with `argparse`'s own `SystemExit(2)`, in `tests/unit/test_cli_analyze.py`
- [X] T018 [P] [US1] Unit test: `cvip analyze` builds an `AnalyzeRequest` correctly from parsed args plus loaded config and calls `orchestrator.analyze()` with it (orchestrator mocked), same file
- [X] T019 [P] [US1] Unit test: an `OrchestratorError` raised from `analyze()` results in `sys.exit(error.exit_code)` and `error.detail` printed to stderr, same file
- [X] T020 [P] [US1] Unit test: a missing/malformed `--config` file yields exit code 2 before `orchestrator.analyze()` is ever called, same file

### Implementation for User Story 1

- [X] T021 [US1] Implement `analyze()`'s Video Loader step and single-pass gate (`check_analysis_status`, `reset_for_forced_reanalysis` when `force=True`) in `src/cvip/orchestrator.py` (depends on T008)
- [X] T022 [US1] Wire the T006 native-dependency preflight and `begin_analysis()` into `analyze()`, immediately after the single-pass gate passes, in `src/cvip/orchestrator.py` (depends on T021)
- [X] T023 [US1] Implement the Scene Detection step (config translation, call, error mapping) in `src/cvip/orchestrator.py` (depends on T022)
- [X] T024 [US1] Implement the Replay Detection step, persisting its segments via `persist_replays()` on success, in `src/cvip/orchestrator.py` (depends on T023)
- [X] T025 [US1] Implement the Scoreboard OCR step, persisting its raw samples via `persist_scoreboard_readings()` on success, in `src/cvip/orchestrator.py` (depends on T024)
- [X] T026 [US1] Implement the OCR Timeline Smoother step in `src/cvip/orchestrator.py` (depends on T025)
- [X] T027 [US1] Implement the Event Detection step, persisting its events via `persist_events()` on success, calling `complete_analysis()`, and writing `request.timeline_path` if supplied, in `src/cvip/orchestrator.py` (depends on T026)
- [X] T028 [US1] Implement per-stage `fail_analysis()`-on-error plus `OrchestratorError` translation (research.md Decision 7's table) wrapping every one of the six stage calls, in `src/cvip/orchestrator.py` (depends on T027)
- [X] T029 [US1] Implement the FR-016 per-stage start/outcome log marker around each of the six stage calls, in `src/cvip/orchestrator.py` (depends on T028)
- [X] T030 [US1] Wire `cvip analyze` in `src/cvip/cli.py`: config loading, `AnalyzeRequest` construction, the `orchestrator.analyze()` call, success output, and exit-code handling (depends on T008, T029)

**Checkpoint**: User Story 1 is fully functional and independently testable — single-pass, fail-fast, fully-wired analysis works end-to-end (modulo real modules, which the mocks stand in for until T065).

---

## Phase 4: User Story 2 - Generate Highlights From an Already-Analyzed Match (Priority: P2)

**Goal**: `cvip generate --template match` queries the Event Database, sequences Clip Generator → Video Stitcher, and never touches Modules 1-7.

**Independent Test**: Against an already-`COMPLETE` seeded match database, run `cvip generate <match_id> --template match --output <path>`. Confirm a playable output video is produced and no OCR/scene/replay-detection code path is ever invoked.

### Tests for User Story 2 ⚠️

- [X] T031 [P] [US2] Contract test asserting `orchestrator.generate()` accepts a `GenerateRequest` and returns a `GenerateResult` matching [contracts/orchestrator_contract.md](./contracts/orchestrator_contract.md)'s shape, in `tests/contract/test_orchestrator_contract.py`
- [X] T032 [P] [US2] Unit test: `template="match"` with no filters calls `query_events()` with an all-`None` filter, passes its result unmodified into `generate_clips`, and never imports or calls Video Loader/Frame Extraction/Scene Detection/Replay Detection/Scoreboard OCR/OCR Timeline Smoother/Event Detection anywhere in the call graph (FR-006, Acceptance Scenario US2-1), in `tests/unit/test_orchestrator_generate.py`
- [X] T033 [P] [US2] Unit test: `min_importance`/`start_over`/`end_over`/`event_types`/`player`/`team` arguments translate into an `EventQueryFilter` with exactly those values (FR-006, Acceptance Scenario US2-2), same file
- [X] T034 [P] [US2] Unit test: `template` of `player`/`team`/`custom` raises `OrchestratorError(INVALID_ARGUMENTS)` with a "not yet implemented — planned for V1.5" detail, and no database is opened (FR-007, Acceptance Scenario US2-3), same file
- [X] T035 [P] [US2] Unit test: a `match_id` with no corresponding database file raises `OrchestratorError(MISSING_INPUT_FILE)` (FR-008, Acceptance Scenario US2-4), same file
- [X] T036 [P] [US2] Unit test: `stitch_video`'s `MISSING_FFMPEG` maps to `OrchestratorError(MISSING_NATIVE_DEPENDENCY)`; every other `VideoStitchingFailureReason` maps to `OrchestratorError(EXPORT_FAILURE)`, same file
- [X] T037 [P] [US2] Unit test: `cvip generate`'s `argparse` parser requires `--template`/`--output`, accepts repeatable `--event-type`, and rejects a missing required argument, in `tests/unit/test_cli_generate.py`
- [X] T038 [P] [US2] Unit test: `cvip generate` builds a `GenerateRequest` correctly and calls `orchestrator.generate()` with it (orchestrator mocked); exit-code handling on `OrchestratorError`, same file

### Implementation for User Story 2

- [X] T039 [US2] Implement `generate()`'s template validation and db-path resolution/existence check in `src/cvip/orchestrator.py` (depends on T008)
- [X] T040 [US2] Implement the `EventQueryFilter` construction from `GenerateRequest` and the `query_events()` call in `src/cvip/orchestrator.py` (depends on T039)
- [X] T041 [US2] Implement the Clip Generator step in `src/cvip/orchestrator.py` (depends on T040)
- [X] T042 [US2] Implement the Video Stitcher step, including the `MISSING_FFMPEG` vs. other-reason exit-code distinction, in `src/cvip/orchestrator.py` (depends on T041)
- [X] T043 [US2] Wire `cvip generate` in `src/cvip/cli.py` (depends on T008, T042)

**Checkpoint**: User Stories 1 AND 2 both work independently — the platform's full two-phase promise (analyze once, generate many) is wired end-to-end.

---

## Phase 5: User Story 3 - Inspect an Analyzed Match's Contents (Priority: P3)

**Goal**: `cvip inspect-db` reports an accurate summary of a match's persisted content.

**Independent Test**: Against a seeded match database, run `cvip inspect-db <db_path>`. Confirm the printed summary's every field matches the database's actual persisted content exactly.

### Tests for User Story 3 ⚠️

- [X] T044 [P] [US3] Contract test asserting `orchestrator.inspect_db()` accepts a `db_path` and returns a `MatchSummary` matching [contracts/orchestrator_contract.md](./contracts/orchestrator_contract.md)'s shape, in `tests/contract/test_orchestrator_contract.py`
- [X] T045 [P] [US3] Unit test: `inspect_db()` against a seeded database returns a `MatchSummary` whose every field matches exactly what was seeded (FR-010, Acceptance Scenario US3-1), in `tests/unit/test_orchestrator_readonly.py`
- [X] T046 [P] [US3] Unit test: `inspect_db()` against a nonexistent path raises `OrchestratorError(MISSING_INPUT_FILE)` (Acceptance Scenario US3-2), same file
- [X] T047 [P] [US3] Unit test: `cvip inspect-db` prints every field [contracts/cli_contract.md](./contracts/cli_contract.md)'s documented output format lists (orchestrator mocked), in `tests/unit/test_cli_inspect_export.py`

### Implementation for User Story 3

- [X] T048 [US3] Implement `inspect_db(db_path)` in `src/cvip/orchestrator.py` (depends on T008)
- [X] T049 [US3] Wire `cvip inspect-db` in `src/cvip/cli.py` (depends on T008, T048)

**Checkpoint**: User Stories 1-3 all work independently.

---

## Phase 6: User Story 4 - Export a Match's Full Timeline (Priority: P3)

**Goal**: `cvip export-timeline` produces a complete, accurate JSON or CSV export of a match's persisted scoreboard/event data.

**Independent Test**: Against a seeded match database, run `cvip export-timeline <match_id> --format json --output <path>`. Confirm the output file contains every persisted scoreboard reading and event, field-for-field, with `snake_case` keys.

### Tests for User Story 4 ⚠️

- [X] T050 [P] [US4] Contract test asserting `orchestrator.export_timeline()` accepts `match_id`/`db_path` and returns a `MatchTimelineExport` matching [contracts/orchestrator_contract.md](./contracts/orchestrator_contract.md)'s shape, in `tests/contract/test_orchestrator_contract.py`
- [X] T051 [P] [US4] Unit test: `export_timeline()` against a seeded database returns every persisted reading and event, `snake_case`-keyed (FR-009, Acceptance Scenario US4-1), in `tests/unit/test_orchestrator_readonly.py`
- [X] T052 [P] [US4] Unit test: `cvip export-timeline --format json` produces valid JSON matching the seeded data exactly (orchestrator mocked to return known `MatchTimelineExport`), in `tests/unit/test_cli_inspect_export.py`
- [X] T053 [P] [US4] Unit test: `cvip export-timeline --format csv` produces valid CSV covering the same event data (Acceptance Scenario US4-2), same file

### Implementation for User Story 4

- [X] T054 [US4] Implement `export_timeline(match_id, db_path)` in `src/cvip/orchestrator.py` (depends on T008)
- [X] T055 [US4] Wire `cvip export-timeline` in `src/cvip/cli.py`, including JSON (`json.dumps`) and CSV (stdlib `csv`) serialization (depends on T008, T054)

**Checkpoint**: User Stories 1-4 all work independently.

---

## Phase 7: User Story 5 - Confirm the Local Machine Is Ready Before Analyzing (Priority: P4)

**Goal**: `cvip doctor` independently checks every required dependency/directory and reports each check's own status plus an overall status.

**Independent Test**: Run `cvip doctor` on a machine with every dependency present; confirm overall `OK`. Remove FFmpeg from `PATH` and re-run; confirm `doctor` specifically flags it while every other check still reports its own status.

### Tests for User Story 5 ⚠️

- [X] T056 [P] [US5] Unit test: `run_doctor_checks()` reports every check `ok=True` when every dependency/directory is genuinely present (Acceptance Scenario US5-1), in `tests/unit/test_cli_doctor.py`
- [X] T057 [P] [US5] Unit test: a mocked missing FFmpeg (or Tesseract) makes only that check report `ok=False` with a specific `detail`, while every other check still runs and reports its own independent result (Acceptance Scenario US5-2), same file
- [X] T058 [P] [US5] Unit test: the Python-version check, package-importability check, and directory-writability check (via a real temp-file write-then-delete, not just `os.access()`) each independently report correctly, same file
- [X] T059 [P] [US5] Unit test: `cvip doctor` prints one line per check plus a final overall `Status:` line, `sys.exit(0)` when every check passed and `sys.exit(1)` otherwise, same file

### Implementation for User Story 5

- [X] T060 [US5] Implement `run_doctor_checks()` in `src/cvip/orchestrator.py`, reusing the T006 native-dependency helper (depends on T006, T008)
- [X] T061 [US5] Wire `cvip doctor` in `src/cvip/cli.py` (depends on T008, T060)

**Checkpoint**: All five user stories are independently functional.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Improvements and gates that affect the whole feature, not any single story

- [X] T062 [P] Run all six [quickstart.md](./quickstart.md) scenarios manually and record pass/fail results in `specs/012-pipeline-orchestrator-cli/quickstart.md`
- [X] T063 [P] Add docstrings to all public functions/classes in `src/cvip/{orchestrator,orchestrator_models,orchestrator_errors,cli}.py`
- [X] T064 Implement Scenario 5's exit-code coverage: one dedicated test per non-zero `OrchestratorFailureReason`/exit-code pair (9 tests, research.md Decision 7's full table, SC-004), in `tests/unit/test_orchestrator_analyze.py`/`test_orchestrator_generate.py`/`test_cli_doctor.py` as appropriate to each condition
- [X] T065 Implement Scenario 6: the one real, unmocked, full-`analyze` smoke test against `tests/fixtures/video_loader/valid_short.mp4` and a real `tmp_path`-backed `EventDatabase` (research.md Decision 5), in `tests/benchmark/test_orchestrator_e2e_smoke.py`
- [X] T066 Contract test confirming `src/cvip/cli.py` contains no direct `cvip.video.*`/`cvip.events.*`/`cvip.clips.*`/`cvip.stitcher.*`/`cvip.db.*` imports (FR-015, static source inspection via `inspect.getsource()` or AST parsing, matching the precedent `tests/contract/test_scoreboard_parsers_contract.py` already established for a similar independence check), in `tests/contract/test_cli_contract.py`
- [X] T067 Run the full test suite (`pytest`) and confirm all tests pass, including every prior feature's existing tests (regression check across the whole repo, now including `src/cvip/{orchestrator,orchestrator_models,orchestrator_errors,cli}.py`)
- [X] T068 Run the constitution-mandated coverage gate: `pytest --cov=src/cvip/orchestrator.py --cov=src/cvip/orchestrator_models.py --cov=src/cvip/orchestrator_errors.py --cov=src/cvip/cli.py --cov-fail-under=100`. This feature is not complete until this passes — add targeted tests for any branch it reports as uncovered (Constitution Principle VII)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories
- **User Story 1 (Phase 3)**: Depends on Foundational only
- **User Story 2 (Phase 4)**: Depends on Foundational only — does not depend on US1's own implementation, only on the shared `cli.py`/`orchestrator_errors.py` scaffolding
- **User Story 3 (Phase 5)**: Depends on Foundational only
- **User Story 4 (Phase 6)**: Depends on Foundational only
- **User Story 5 (Phase 7)**: Depends on Foundational (specifically T006, the shared native-dependency helper)
- **Polish (Phase 8)**: Depends on all five user stories being complete

### Within Each User Story

- Tests are written first and must fail before implementation begins
- US1: Video Loader + single-pass gate (T021) → preflight + `begin_analysis` (T022) → Scene Detection (T023) → Replay Detection (T024) → Scoreboard OCR (T025) → OCR Timeline Smoother (T026) → Event Detection (T027) → error-mapping wrap (T028) → logging (T029) → `cli.py` wiring (T030) — strictly sequential, since each stage's own implementation needs the previous stage's real call site to wrap
- US2: template validation (T039) → filter/query (T040) → Clip Generator (T041) → Video Stitcher (T042) → `cli.py` wiring (T043) — sequential for the same reason
- US3, US4, US5 are each fully independent of one another and of US1/US2's own implementation (they share only the Foundational scaffolding) — genuinely parallelizable across stories, not just within

### Parallel Opportunities

- T001, T002, T003 (Setup) can run in parallel
- T004, T005 (Foundational) can run in parallel — different files; T007 can also start in parallel with T004/T005 (different file, no shared dependency until T008)
- T009-T020 (all 12 US1 tests) can run in parallel
- T031-T038 (all 8 US2 tests) can run in parallel
- T044-T047 (all 4 US3 tests) can run in parallel
- T050-T053 (all 4 US4 tests) can run in parallel
- T056-T059 (all 4 US5 tests) can run in parallel
- Once Foundational is complete, User Stories 1, 2, 3, 4, and 5's *implementation* work (not just tests) can proceed in parallel across different engineers/sessions, since none of their implementation tasks depend on another story's implementation being done first (only on Foundational) — genuinely independent, unlike most prior features where later stories built on an earlier story's pipeline stage
- T062, T063 (Polish) can run in parallel

---

## Parallel Example: User Story 1

```bash
# Launch all twelve US1 tests together (write first, confirm they fail):
Task: "Contract test in tests/contract/test_orchestrator_contract.py"
Task: "Full six-stage sequence unit test in tests/unit/test_orchestrator_analyze.py"
Task: "COMPLETE-match single-pass gate unit test in tests/unit/test_orchestrator_analyze.py"
Task: "--force reset unit test in tests/unit/test_orchestrator_analyze.py"
Task: "Mid-sequence failure unit test in tests/unit/test_orchestrator_analyze.py"
Task: "IN_PROGRESS-match single-pass gate unit test in tests/unit/test_orchestrator_analyze.py"
Task: "Missing native dependency unit test in tests/unit/test_orchestrator_analyze.py"
Task: "Video Loader failure-reason mapping unit test in tests/unit/test_orchestrator_analyze.py"
Task: "cvip analyze argparse unit test in tests/unit/test_cli_analyze.py"
Task: "AnalyzeRequest construction unit test in tests/unit/test_cli_analyze.py"
Task: "Exit-code translation unit test in tests/unit/test_cli_analyze.py"
Task: "Malformed config unit test in tests/unit/test_cli_analyze.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (blocks everything else)
3. Complete Phase 3: User Story 1
4. **STOP and VALIDATE**: confirm `cvip analyze` sequences all six stages correctly, enforces single-pass analysis, and fails fast with the correct exit code on any stage's failure
5. This alone is the platform's core MVP unlock — a user can run one command against a real video and get a queryable database, even before `generate`/`inspect-db`/`export-timeline`/`doctor` exist

### Incremental Delivery

1. Setup + Foundational → foundation ready (parser scaffolding, error taxonomy, data model, native-dependency helper)
2. Add User Story 1 → validate independently (the core `analyze` unlock)
3. Add User Story 2 → validate independently (the core `generate` unlock — together with US1, the platform's full two-phase promise)
4. Add User Stories 3, 4, 5 → each validates independently, in any order (genuinely parallel, unlike most prior features)
5. Phase 8: Polish, including the exit-code coverage sweep (T064), the one real smoke test (T065), the `cli.py` independence check (T066), and the mandatory coverage gate (T068)

---

## Notes

- [P] tasks touch different files (or, within a shared file, are still independent test-writing tasks with no unmet dependencies) and have no unmet dependencies
- [Story] label maps each task to its user story for traceability back to spec.md
- Commit after each task or logical group
- Stop at any checkpoint to validate a story independently before moving on
- **This feature's own correctness bar is different from every prior module's**: there is no accuracy criterion analogous to Module 5's SC-001, because this feature detects nothing — T009 through T061 prove the sequencing/translation/gating logic is correct against mocks that stand in for Modules 1-10's own already-proven contracts; T065 (the one real smoke test) proves those mocks weren't lying about what the real modules actually accept and return.
- **FR-006 (no Modules 1-7 access during `generate`)**: partially enforced by T032's runtime assertion (no mock for those modules is ever called) and partially by code review (T067) — confirming `generate()`'s own function body, read top to bottom, has no import or call site referencing any of those six modules at all, not just that a particular test scenario didn't happen to trigger one.
- **FR-015 (CLI contains no sequencing logic)**: enforced by T066's static independence check (no direct import of any pipeline/database module), the same "read the source, not just observe behavior" treatment `tests/contract/test_scoreboard_parsers_contract.py` already established as this platform's precedent for structural (not just behavioral) invariants.
