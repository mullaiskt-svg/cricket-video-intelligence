---

description: "Task list template for feature implementation"
---

# Tasks: Event Database

**Input**: Design documents from `/specs/010-event-database/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/event_database_contract.md](./contracts/event_database_contract.md), [quickstart.md](./quickstart.md)

**Tests**: Included — constitution Principle VII (Test-First Development) requires contract tests at module boundaries, tests written before implementation, and 100% coverage on critical paths (enforced by T055).

**Organization**: Tasks are grouped by user story (from spec.md) to enable independent implementation and testing of each story.

**Note on shared infrastructure**: This feature reuses `src/cvip/common/diagnostics.py`'s emitter and `pyproject.toml`'s existing pytest/coverage configuration (`[tool.coverage.run] source = ["src/cvip"]` already covers any new subpackage). Unlike every prior feature, this one's tests run against a **real temporary SQLite file** (`tmp_path`), not synthetic in-memory-only fixtures — the whole point of this module is durability across a close/reopen cycle (plan.md Testing).

**Note on package layout**: Event Database gets its own subpackage, `src/cvip/db/` — reserved as empty scaffolding since `specs/001-video-loader/plan.md`, populated here for the first time (CLAUDE.md Package Layout, plan.md Structure Decision).

**Note on dependencies**: No new pip package is introduced by this feature — `sqlite3` is Python stdlib (research.md Technical Context).

**Note on Foundational scope**: Unlike a linear pipeline module, this feature's connection-lifecycle checks (creating a fresh schema, `PRAGMA integrity_check`, `PRAGMA user_version` comparison) are implemented in the Foundational phase, not deferred to User Story 4 — every other story needs a working `open_database()` just to begin, the same reasoning Clip Generator's own tasks.md used to move its input validation into Foundational. User Story 4's own phase adds the dedicated tests proving these paths (T043-T044) plus the one check that genuinely depends on User Story 1's status-tracking machinery: rejecting a write against an already-`COMPLETE` match (T048).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3, US4)

## Path Conventions

Single project, per plan.md Project Structure: new files in `src/cvip/db/` (a new subpackage, sibling to `src/cvip/video/`, `src/cvip/events/`, `src/cvip/clips/`), tests in the existing `tests/{contract,integration,unit,benchmark}/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization for this feature's new subpackage and files

- [X] T001 [P] Create `src/cvip/db/{models.py,errors.py,schema.py,database.py}` as empty modules per plan.md Source Code layout (`src/cvip/db/__init__.py` already exists, empty) — first population of the `db/` scaffolding directory reserved since `specs/001-video-loader/plan.md`
- [X] T002 [P] Create empty test file placeholders: `tests/contract/test_event_database_contract.py`, `tests/integration/test_event_database_e2e.py`, `tests/unit/test_event_database_lifecycle.py`, `tests/unit/test_event_database_persistence.py`, `tests/unit/test_event_database_query.py`, `tests/unit/test_event_database_failures.py`, `tests/benchmark/test_event_database_performance.py`
- [X] T003 [P] Confirm `pyproject.toml`'s existing `[tool.coverage.run] source = ["src/cvip"]` and pytest `testpaths` already cover the new `src/cvip/db/` subpackage — no config changes expected; document in a one-line comment if any gap is found

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Schema DDL, core types, and the connection-lifecycle open/create/check logic every user story depends on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [X] T004 [P] Implement the `EventDatabaseFailureReason` enum (`CORRUPTED_DATABASE_FILE`, `SCHEMA_VERSION_MISMATCH`, `WRITE_AGAINST_COMPLETED_MATCH`) and an `EventDatabaseError` exception carrying it, per [contracts/event_database_contract.md](./contracts/event_database_contract.md) and [data-model.md](./data-model.md), in `src/cvip/db/errors.py`
- [X] T005 [P] Implement `AnalysisStatusCondition` enum (`NOT_ANALYZED`, `IN_PROGRESS`, `COMPLETE`), frozen dataclasses `MatchMetadata`, `EventQueryFilter`, `QueriedEvent`, `MatchSummary`, `MatchTimelineExport`, and structural `Protocol`s `ScoreboardReadingLike`/`ReplaySegmentLike`/`EventLike` per [data-model.md](./data-model.md), in `src/cvip/db/models.py`
- [X] T006 [P] Implement `src/cvip/db/schema.py`: the `CREATE TABLE`/`CREATE INDEX` DDL verbatim from `specs/technical_plan.md`'s Database Schema (`matches`, `events`, `replays`, `scoreboard_readings` + their indexes), the `SCHEMA_VERSION` constant (research.md Decision 3), and a `create_schema(conn)` function
- [X] T007 Implement `EventDatabase.__enter__`/`__exit__` connection lifecycle and the `open_database(path)` entry point in `src/cvip/db/database.py`: on an existing file, `PRAGMA integrity_check` first (research.md Decision 4 — anything but `('ok',)` raises `CORRUPTED_DATABASE_FILE`), then `PRAGMA user_version` compared against `SCHEMA_VERSION` (raises `SCHEMA_VERSION_MISMATCH` on mismatch); on a missing file, create fresh via `schema.create_schema()` and set `PRAGMA user_version = SCHEMA_VERSION` (FR-001). Also implement the diagnostics-building helper (module_name `"db.database"`) reusing `src/cvip/common/diagnostics.py` (depends on T004, T005, T006)

**Checkpoint**: Foundation ready — user story implementation can now begin

---

## Phase 3: User Story 1 - Never Waste the 40-Minute Analysis Budget Twice (Priority: P1) 🎯 MVP

**Goal**: `check_analysis_status()` correctly distinguishes not-yet-analyzed, already-analyzed, and in-progress; `begin_analysis()`/`complete_analysis()`/`fail_analysis()`/`reset_for_forced_reanalysis()` correctly drive the `matches` row through its lifecycle.

**Independent Test**: Insert a `matches` row for a known `file_hash` with status `COMPLETE`. Ask whether analysis should proceed for that same `file_hash`. Confirm the specific "already analyzed" condition, distinct from "never analyzed" and "analysis in progress."

### Tests for User Story 1 ⚠️

> Write these tests FIRST, ensure they FAIL before implementation

- [X] T008 [P] [US1] Contract test asserting `open_database()` returns an `EventDatabase` matching [contracts/event_database_contract.md](./contracts/event_database_contract.md)'s shape (a working context manager over a fresh temp path), in `tests/contract/test_event_database_contract.py`
- [X] T009 [P] [US1] Unit test: `check_analysis_status()` reports `NOT_ANALYZED` when no `matches` row exists for a `file_hash` (FR-003, Acceptance Scenario US1-1), in `tests/unit/test_event_database_lifecycle.py`
- [X] T010 [P] [US1] Unit test: `begin_analysis()` then `complete_analysis()` makes `check_analysis_status()` report `COMPLETE` (FR-005, FR-006, Acceptance Scenario US1-2), same file
- [X] T011 [P] [US1] Unit test: `begin_analysis()` alone (no `complete_analysis()`) makes `check_analysis_status()` report `IN_PROGRESS`, distinguishable from `COMPLETE` (FR-004, Acceptance Scenario US1-3), same file
- [X] T012 [P] [US1] Unit test: `reset_for_forced_reanalysis()` on a `file_hash` that already has persisted rows removes all `scoreboard_readings`/`replays`/`events` rows and resets `matches.status` to `IN_PROGRESS` (FR-007, Acceptance Scenario US1-4), same file
- [X] T013 [P] [US1] Unit test: `reset_for_forced_reanalysis()` on a `file_hash` with no prior `matches` row is treated as a fresh first-time analysis, not an error (Edge Cases), same file
- [X] T014 [P] [US1] Unit test: `begin_analysis()` against a `file_hash` whose existing `matches` row is `IN_PROGRESS` or `FAILED` reuses it silently (not an error); against an existing `COMPLETE` row it raises (data-model.md `AnalysisStatusCondition` note), same file
- [X] T015 [P] [US1] Integration test: `open_database()` (fresh path) → `begin_analysis()` → `complete_analysis()` → `check_analysis_status()` against a real temp SQLite file, confirming `COMPLETE` (SC-001), in `tests/integration/test_event_database_e2e.py`

### Implementation for User Story 1

- [X] T016 [US1] Implement `check_analysis_status(file_hash)` (FR-003, FR-004) in `src/cvip/db/database.py` (depends on T007)
- [X] T017 [US1] Implement `begin_analysis(metadata)` (FR-005) including the "existing `IN_PROGRESS`/`FAILED` row reused, existing `COMPLETE` row rejected" rule, and initializing the connection's tracked status (research.md Decision 5), in `src/cvip/db/database.py` (depends on T016)
- [X] T018 [US1] Implement `complete_analysis()`/`fail_analysis()` (FR-006) and the tracked-status update, in `src/cvip/db/database.py` (depends on T017)
- [X] T019 [US1] Implement `reset_for_forced_reanalysis(file_hash)` (FR-007) — unconditional `DELETE` across `scoreboard_readings`/`replays`/`events`, `matches` row reset-or-inserted to `IN_PROGRESS`, tracked status updated — in `src/cvip/db/database.py` (depends on T018)

**Checkpoint**: User Story 1 is fully functional and independently testable — single-pass enforcement works end-to-end against a real database file.

---

## Phase 4: User Story 2 - Every Analysis Result Survives to Generate Highlights Later (Priority: P2)

**Goal**: `persist_scoreboard_readings()`/`persist_replays()`/`persist_events()`/`update_clip_window()` correctly write and preserve every field, surviving a connection close and reopen.

**Independent Test**: Supply a synthetic batch of scoreboard readings, replay segments, and detected events for a match. Persist them. Re-open the database (a fresh connection) and confirm every row and field comes back unchanged.

### Tests for User Story 2 ⚠️

- [X] T020 [P] [US2] Unit test: `persist_scoreboard_readings()` preserves every field and `timestamp_seconds` order (FR-008, Acceptance Scenario US2-1), in `tests/unit/test_event_database_persistence.py`
- [X] T021 [P] [US2] Unit test: `persist_replays()` preserves every field, inserted with the caller-supplied explicit `replay_id` (FR-009, data-model.md `ReplaySegmentLike` note, Acceptance Scenario US2-2), same file
- [X] T022 [P] [US2] Unit test: `persist_events()` preserves every field, `clip_start_seconds`/`clip_end_seconds` both `None` immediately after (FR-010, Acceptance Scenario US2-3), same file
- [X] T023 [P] [US2] Unit test: `update_clip_window()` changes only `clip_start_seconds`/`clip_end_seconds` on the targeted event — every other column of that row, and every other row, is untouched (FR-011, Acceptance Scenario US2-4), same file
- [X] T024 [P] [US2] Unit test: `persist_scoreboard_readings(())`/`persist_replays(())`/`persist_events(())` (empty batches) succeed as no-ops, zero rows inserted (Edge Cases), same file
- [X] T025 [P] [US2] Unit test: repeated `update_clip_window()` calls for the same event each succeed and reflect only the most recent call (Edge Cases), same file
- [X] T026 [P] [US2] Integration test: `begin_analysis()` → persist all three batch types → `complete_analysis()` → close connection → open a **fresh** connection to the same path → `get_match_timeline()` confirms everything survives exactly, all fields intact (User Story 2's own core scenario, SC-002), in `tests/integration/test_event_database_e2e.py`

### Implementation for User Story 2

- [X] T027 [US2] Implement `persist_scoreboard_readings(readings)` (FR-008) via one batched `executemany()` per call in `src/cvip/db/database.py` (depends on T019)
- [X] T028 [US2] Implement `persist_replays(segments)` (FR-009), explicit `replay_id` insert, in `src/cvip/db/database.py` (depends on T027)
- [X] T029 [US2] Implement `persist_events(events)` (FR-010), `clip_start_seconds`/`clip_end_seconds` always `NULL` on insert, in `src/cvip/db/database.py` (depends on T028)
- [X] T030 [US2] Implement `update_clip_window(event_key, clip_start_seconds, clip_end_seconds)` (FR-011) — `UPDATE events SET ... WHERE event_id = ?` — in `src/cvip/db/database.py` (depends on T029)

**Checkpoint**: User Stories 1 AND 2 both work independently — every upstream module's output survives to a later process.

---

## Phase 5: User Story 3 - Query and Inspect What Was Found (Priority: P3)

**Goal**: `query_events()` correctly applies every filter (individually and combined); `get_match_summary()`/`get_match_timeline()` accurately reflect persisted data.

**Independent Test**: Persist a representative mixed set of events. Query with each supported filter individually and in combination; confirm exact matches, zero false positives/negatives. Request a match summary and a full timeline export; confirm both accurately reflect the persisted data.

### Tests for User Story 3 ⚠️

- [X] T031 [P] [US3] Unit test: `query_events(EventQueryFilter(player=...))` returns only that player's events, exact match (FR-012, Acceptance Scenario US3-1), in `tests/unit/test_event_database_query.py`
- [X] T032 [P] [US3] Unit test: `query_events(EventQueryFilter(event_types=(...)))` returns only matching-type events (FR-012, Acceptance Scenario US3-2), same file
- [X] T033 [P] [US3] Unit test: `query_events(EventQueryFilter(min_importance=...))` returns only events at or above the threshold (FR-012, Acceptance Scenario US3-3), same file
- [X] T034 [P] [US3] Unit test: `query_events(EventQueryFilter(start_over=..., end_over=...))` returns only events whose `over_number` falls in the whole-over range (FR-012, Acceptance Scenario US3-4), same file
- [X] T035 [P] [US3] Unit test: several filters combined return only events matching all of them (FR-012, Acceptance Scenario US3-5), same file
- [X] T036 [P] [US3] Unit test: a filter combination matching zero events returns `()`, not an error (Edge Cases), same file
- [X] T037 [P] [US3] Unit test: `QueriedEvent.event_key` is `str(event_id)` and results are ordered by ascending `timestamp_seconds` (FR-013, research.md Decision 10), same file
- [X] T038 [P] [US3] Unit test: `get_match_summary()` reports duration/resolution/frame rate/codec/status, sample/event/replay counts, event counts by type, and average confidence by type, each accurate against persisted data — a type with zero events is absent from the dict, not a `0` entry (FR-014, Acceptance Scenario US3-6, data-model.md note), same file
- [X] T039 [P] [US3] Unit test: `get_match_timeline()` returns every scoreboard reading and event as `snake_case`-keyed dicts, ordered by `timestamp_seconds` (FR-015, Acceptance Scenario US3-7), same file
- [X] T040 [P] [US3] Integration test: `query_events()`'s returned `QueriedEvent` tuple is passed directly (no adaptation) as `ClipGenerationRequest.events` to `cvip.clips.generator.generate_clips()` and completes successfully — proving FR-013's structural-compatibility claim against Clip Generator's real, already-implemented contract, not just an isolated field-shape assertion, in `tests/integration/test_event_database_e2e.py`

### Implementation for User Story 3

- [X] T041 [US3] Implement the `EventQueryFilter` → parameterized `(where_clause, params)` builder (research.md Decision 6) in `src/cvip/db/database.py` (depends on T029)
- [X] T042 [US3] Implement `query_events(filter)` (FR-012, FR-013) using the builder, mapping each row to `QueriedEvent` with `event_key = str(event_id)` (research.md Decision 10), ordered by `timestamp_seconds`, in `src/cvip/db/database.py` (depends on T041)
- [X] T043 [US3] Implement `get_match_summary()` (FR-014) — `COUNT`/`GROUP BY` aggregates over `scoreboard_readings`/`events`/`replays` joined with the `matches` row — in `src/cvip/db/database.py` (depends on T029)
- [X] T044 [US3] Implement `get_match_timeline()` (FR-015) — full `scoreboard_readings`/`events` row dumps as plain dicts — in `src/cvip/db/database.py` (depends on T029)

**Checkpoint**: User Stories 1, 2, AND 3 all work independently — the full write/query/read-back lifecycle is usable end-to-end.

---

## Phase 6: User Story 4 - Fail Clearly on Corruption or Misuse (Priority: P4)

**Goal**: A corrupted file, a schema-version mismatch, and a write against an already-`COMPLETE` match each produce a specific, distinguishable failure — never silent misbehavior.

**Independent Test**: Present a database file that isn't valid SQLite (or one whose schema version doesn't match); confirm each is reported as a specific, distinguishable failure before any read or write is attempted. Attempt a write against a `COMPLETE` match outside the explicit reset path; confirm rejection with a specific reason.

### Tests for User Story 4 ⚠️

- [X] T045 [P] [US4] Unit test: `open_database()` against a file containing arbitrary non-SQLite bytes raises `EventDatabaseError(CORRUPTED_DATABASE_FILE)` before any table is queried (FR-016, Acceptance Scenario US4-1), in `tests/unit/test_event_database_failures.py`
- [X] T046 [P] [US4] Unit test: `open_database()` against a valid SQLite file whose `PRAGMA user_version` doesn't match `SCHEMA_VERSION` raises `EventDatabaseError(SCHEMA_VERSION_MISMATCH)` (FR-017, Acceptance Scenario US4-2), same file
- [X] T047 [P] [US4] Unit test: after `complete_analysis()`, calling `persist_scoreboard_readings()`/`persist_replays()`/`persist_events()`/`update_clip_window()` (no explicit reset) each raises `EventDatabaseError(WRITE_AGAINST_COMPLETED_MATCH)`, and no row is written (FR-018, Acceptance Scenario US4-3), same file
- [X] T048 [P] [US4] Unit test: `reset_for_forced_reanalysis()` on a `COMPLETE` match succeeds despite the write gate — confirming research.md Decision 5's documented, deliberate bypass — same file
- [X] T049 [P] [US4] Unit test: every `EventDatabaseError`-raising path (`CORRUPTED_DATABASE_FILE`, `SCHEMA_VERSION_MISMATCH`, `WRITE_AGAINST_COMPLETED_MATCH`) still emits exactly one diagnostics record with the matching `failure_reason` (FR-020), same file

### Implementation for User Story 4

- [X] T050 [US4] Wire the `WRITE_AGAINST_COMPLETED_MATCH` gate (research.md Decision 5) into `persist_scoreboard_readings`/`persist_replays`/`persist_events`/`update_clip_window`, checked against `self._current_status`, in `src/cvip/db/database.py` (depends on T030, T043, T044 — every write method must exist first)
- [X] T051 [US4] Harden T007's corruption/schema-mismatch checks against T045-T046's dedicated tests, filling any gap found, in `src/cvip/db/database.py` (depends on T007, T045, T046)

**Checkpoint**: All four user stories are independently functional — the full lifecycle works correctly, and every misuse/corruption path fails loudly and specifically.

**Post-merge-review correction (PR #14 Codex review, addressed before merge)**: T047/T050 as originally written included `update_clip_window()` in the `WRITE_AGAINST_COMPLETED_MATCH` gate — confirmed wrong (it would make `cvip generate`'s clip-window bookkeeping unusable, since `generate` only ever runs after the match is already `COMPLETE`) and removed from the gate; see [research.md](./research.md) Decision 5's own correction note and [contracts/event_database_contract.md](./contracts/event_database_contract.md). A second finding from the same review — a failed batch write left partial rows silently committed by a later, unrelated commit — was fixed by adding an explicit rollback to `_run_operation`'s exception handling, with two new regression tests (`test_update_clip_window_succeeds_against_a_completed_match`, `test_a_failed_batch_write_rolls_back_and_is_not_persisted_by_a_later_commit`, `tests/unit/test_event_database_failures.py`).

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Improvements and gates that affect the whole feature, not any single story

- [X] T052 [P] Run all five [quickstart.md](./quickstart.md) scenarios manually and record pass/fail results in `specs/010-event-database/quickstart.md`
- [X] T053 [P] Add docstrings to all public functions/classes in `src/cvip/db/{models,errors,schema,database}.py`
- [X] T054 [P] Benchmark test: persist a full-match-scale synthetic dataset (~12,600 scoreboard readings, a few hundred events, a few dozen replay segments) and confirm completion well under a minute (SC-002, SC-005), in `tests/benchmark/test_event_database_performance.py`
- [X] T055 Implement the full FR-020 diagnostics field list (`schema_version=` on every record; operation-specific fields per data-model.md's `EventDatabaseDiagnostics`) across every write method, verified by a dedicated diagnostics-completeness unit test, in `src/cvip/db/database.py`
- [X] T056 Run the full test suite (`pytest`) and confirm all tests pass, including every prior feature's existing tests (regression check across the whole repo, now including `src/cvip/db/`)
- [X] T057 Run the constitution-mandated coverage gate: `pytest --cov=src/cvip/db --cov-fail-under=100`. This feature is not complete until this passes — add targeted tests for any branch it reports as uncovered (Constitution Principle VII)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories
- **User Story 1 (Phase 3)**: Depends on Foundational only
- **User Story 2 (Phase 4)**: Depends on Foundational; its write-method gate (T050, later) will depend on US1's tracked-status machinery, but US2's own persistence logic (T027-T030) only needs a valid open connection (T007)
- **User Story 3 (Phase 5)**: Depends on Foundational and on US2's persisted data existing to query (T029) — reads what US2 writes
- **User Story 4 (Phase 6)**: Depends on Foundational (T007, for corruption/mismatch) and on every write method from US1/US2/US3 existing (T019, T030, T043, T044) — this is the one story that genuinely can't be fully implemented before the others, since it hardens paths they create
- **Polish (Phase 7)**: Depends on all four user stories being complete

### Within Each User Story

- Tests are written first and must fail before implementation begins
- Foundational's schema/models/errors (T004-T006) before the connection lifecycle (T007)
- US1: status check (T016) before lifecycle transitions (T017, T018) before forced reset (T019) — each builds on the tracked-status state the previous introduces
- US2: readings (T027) before replays (T028) before events (T029) before clip-window update (T030) — purely sequential by file-convenience, no real data dependency between them
- US3: the filter builder (T041) before `query_events()` (T042); `get_match_summary()`/`get_match_timeline()` (T043, T044) are independent of the query builder and of each other
- US4: T050 (the write gate) is the *last* implementation task overall — it wraps every write method US1-US3 already built; T051 only hardens T007, which already exists from Foundational

### Parallel Opportunities

- T001, T002, T003 (Setup) can run in parallel
- T004, T005, T006 (Foundational) can run in parallel — different files
- T008-T015 (all 8 US1 tests) can run in parallel
- T020-T026 (all 7 US2 tests) can run in parallel
- T031-T040 (all 10 US3 tests) can run in parallel
- T045-T049 (all 5 US4 tests) can run in parallel
- T052, T053, T054 (Polish) can run in parallel

---

## Parallel Example: User Story 1

```bash
# Launch all eight US1 tests together (write first, confirm they fail):
Task: "Contract test in tests/contract/test_event_database_contract.py"
Task: "NOT_ANALYZED status unit test in tests/unit/test_event_database_lifecycle.py"
Task: "COMPLETE status unit test in tests/unit/test_event_database_lifecycle.py"
Task: "IN_PROGRESS status unit test in tests/unit/test_event_database_lifecycle.py"
Task: "Forced reset with prior data unit test in tests/unit/test_event_database_lifecycle.py"
Task: "Forced reset with no prior row unit test in tests/unit/test_event_database_lifecycle.py"
Task: "begin_analysis reuse-vs-reject unit test in tests/unit/test_event_database_lifecycle.py"
Task: "Full lifecycle integration test in tests/integration/test_event_database_e2e.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (blocks everything else)
3. Complete Phase 3: User Story 1
4. **STOP and VALIDATE**: confirm single-pass enforcement works end-to-end against a real database file
5. This alone makes constitution Principle III actually checkable — the Pipeline Orchestrator could integrate just this much and already prevent re-analyzing the same video, even before persistence/query/failure-hardening land

### Incremental Delivery

1. Setup + Foundational → foundation ready (a working, openable, schema-versioned database file)
2. Add User Story 1 → validate independently (single-pass enforcement)
3. Add User Story 2 → validate independently (every upstream module's output survives a reconnect)
4. Add User Story 3 → validate independently (filtering, summary, timeline — including real cross-module compatibility with Clip Generator)
5. Add User Story 4 → validate independently (corruption/mismatch/already-COMPLETE-write all fail specifically and loudly)
6. Phase 7: Polish, including the mandatory coverage gate (T057)

---

## Notes

- [P] tasks touch different files (or, within `database.py`, are still independent test-writing tasks even when the *implementation* they'll eventually validate lands in one shared file) and have no unmet dependencies
- [Story] label maps each task to its user story for traceability back to spec.md
- Commit after each task or logical group
- Stop at any checkpoint to validate a story independently before moving on
- **FR-019 (no video/frame/OCR access, no analysis of any kind)**: satisfied by construction — no code in `src/cvip/db/` imports `cv2`, `pytesseract`, or any video/frame-analysis module; every public method's input is either a plain identifier (`file_hash`, `event_key`) or an already-computed batch/filter object (data-model.md). Not independently testable as a positive runtime behavior — enforced by code review (T056), the same treatment Clip Generator gave its own analogous FR-013.
- **FR-002 (path resolution is the caller's job)**: satisfied by construction — `open_database(path)` takes an already-resolved `Path`; no method anywhere reads `--output-db`, `file_hash`, or any CLI/config state to *decide* a path itself. Enforced by code review, same treatment.
- **The `WRITE_AGAINST_COMPLETED_MATCH` gate (T050) is deliberately the very last piece of write-path logic wired in** — every other write method (US2's persistence, US1's lifecycle transitions) is built and independently tested *before* this gate wraps them, so each story's own tests can confirm its core behavior in isolation first, exactly mirroring Clip Generator's own precedent of building a pipeline stage before wrapping it with a cross-cutting concern.
- **T040 (US3's Clip Generator cross-module integration test) is the one test in this feature that imports another feature's code** (`cvip.clips.generator`) — a deliberate exception to "test this module in isolation," because FR-013's whole claim is empty unless verified against Clip Generator's *real* implementation, not a hand-rolled shape assertion that could pass while still being wrong about what Clip Generator actually checks (`getattr(event, "event_key", None)`, research.md Decision 10).
