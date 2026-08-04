# Implementation Plan: Event Database

**Branch**: `010-event-database` | **Date**: 2026-08-03 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/010-event-database/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

The SQLite persistence and query layer underneath the whole pipeline (`specs/technical_plan.md`'s Database Schema: `matches`, `events`, `replays`, `scoreboard_readings`) — one `.sqlite` file per analyzed match (`match_id` = `file_hash[:12]` by default, or a caller-supplied friendly path), opened once per CLI invocation and used for the lifetime of that invocation. Unlike every prior module (1-9), this is not a linear pipeline stage returning one self-contained result from one `.run()` call — it's a stateful, multi-operation data-access object: single-pass-analysis status checks (constitution Principle III's actual enforcement mechanism), batched writes after each upstream stage completes, an event query API for `cvip generate`'s filter surface, and read-back views for `cvip inspect-db`/`cvip export-timeline`. Because one database file represents exactly one match, `events`/`replays`/`scoreboard_readings` need no `match_id` foreign key at all (per `specs/technical_plan.md`'s schema) — every write/query after `begin_analysis()` implicitly targets "the" match this open connection represents; only the single-pass check and lifecycle transitions (`begin`/`complete`/`fail`/`reset`) key off `file_hash` explicitly, since that's the identity being checked *before* a `matches` row is known to exist.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: `sqlite3` (Python standard library — no new pip dependency; consistent with this platform's minimal-dependency posture and the constitution's offline-first/open-source-only stack). Accepts `ScoreboardSample`-shaped (Module 4/4a), `ReplaySegment`-shaped (Module 3), and `DetectedEvent`-shaped (Module 5) records as input by structural shape, matching Clip Generator's own precedent (research.md Decision 1) of not hard-importing upstream modules' dataclasses — this module's own `db/models.py` defines the batch/row shapes it actually persists.

**Storage**: SQLite, one file per match (`specs/technical_plan.md` Database Schema) — this module *is* the storage layer every other module explicitly defers to.

**Testing**: pytest — contract test for the module boundary (open/close lifecycle, error taxonomy, every public method's shape); unit tests per capability area (single-pass status transitions, batch persistence field-fidelity, query filter combinations, match summary/timeline accuracy, corruption/schema-mismatch/already-COMPLETE-write rejection); an integration test exercising the full lifecycle end-to-end (open fresh -> begin -> persist three batches -> complete -> reopen a fresh connection -> query/summarize/export, confirming everything survives a connection close/reopen exactly like a real `analyze` process exiting and a later `generate` process starting) against a real temp SQLite file (`tmp_path`, not a checked-in fixture — this module's whole job is to be tested against a real database file, unlike every prior module's synthetic-in-memory-only precedent). A lightweight benchmark test for SC-002/SC-005 (persisting a full match's worth of data — ~12,600 scoreboard readings, a few hundred events, a few dozen replay segments — well under a minute).

**Target Platform**: Windows 11 desktop, CPU-only — trivially satisfied; `sqlite3` is stdlib, no GPU/network surface of any kind.

**Project Type**: Single project. Per CLAUDE.md's Package Layout section, Event Database gets its own subpackage, `src/cvip/db/` — already reserved as empty scaffolding since Module 1 (`specs/001-video-loader/plan.md`), populated here for the first time, the same way `src/cvip/events/` and `src/cvip/clips/` were.

**Performance Goals**: SC-001 (single-pass status check) well under a second regardless of database size — a single indexed lookup (`idx_matches_file_hash`). SC-002/SC-005 (persisting a full match) well under a minute — a small fraction of the platform's overall 40-minute `analyze` budget, dominated by disk I/O for ~13,000 total rows via batched `executemany()`, not per-row round trips.

**Constraints**: Fully offline (trivially — a local file); single-process access only (Assumptions — SQLite's own file locking is sufficient, no concurrent multi-writer support needed for MVP); every write against an already-`COMPLETE` match rejected except the explicit forced-reset path (FR-018); schema-version and corruption detection fail fast with specific, distinguishable reasons (FR-016, FR-017) before any other read/write is attempted; this module never touches a video frame, OCR engine, or performs analysis of any kind (FR-019).

**Scale/Scope**: One open `EventDatabase` connection per CLI invocation (`analyze` or `generate`/`inspect-db`/`export-timeline`), used for that invocation's full lifetime; on the order of 12,600 scoreboard readings, a few hundred events, a few dozen replay segments for a full match.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate | Status |
|---|---|---|
| I. Offline-First, Always | No network/cloud calls anywhere | PASS (trivially) — `sqlite3` is a local, stdlib, file-based engine; no external calls of any kind |
| II. Performance is Non-Negotiable | Fits within the overall 40 min / 6GB / CPU-only budget | PASS — SC-002/SC-005's expectation (well under a minute for a full match's data) is a small fraction of the 40-minute budget; batched `executemany()` writes and indexed lookups keep this negligible relative to OCR/video-decode costs elsewhere in the pipeline |
| III. Single-Pass Analysis Principle | Each match analyzed only once, no reprocessing | PASS — this module **is** the enforcement mechanism (FR-003/FR-004, the `matches` table + `idx_matches_file_hash`); without it, Principle III has nothing actually checking it |
| IV. Detection Accuracy Requirements | Confidence scores on detected events; contributes to ≥95% detection accuracy | N/A — this module detects nothing; it persists and reads back `confidence`/`ocr_confidence`/`parse_confidence` values Modules 4/4a/5 already computed, unaltered (FR-008, FR-010) |
| V. Modular & Extensible Architecture | Independently testable, clear I/O contract | PASS — a clear, if unusually-shaped (stateful, multi-method rather than single-run), contract: open/close lifecycle + four independent capability groups (status, persistence, query, read-back), each independently testable per User Story 1-4's own Independent Test sections |
| VI. Fail Fast, Never Silently | Crash loudly on structural failure, no silent fallback, detailed logging | PASS — FR-016/FR-017/FR-018's three-reason failure taxonomy (corrupted file, schema mismatch, write against a `COMPLETE` match) covers every way this module could otherwise silently misbehave; FR-020 requires a diagnostics record per significant write operation |
| VII. Test-First Development | Contract tests at module boundary; 100% coverage on critical paths | PASS — contract test planned ahead of implementation; coverage gate planned in tasks.md Polish phase, matching every prior feature's precedent |

No violations identified. Complexity Tracking table not required.

**Post-Phase 1 re-check**: Design artifacts (data-model.md, contracts/, quickstart.md) introduce no new dependency beyond stdlib `sqlite3`, no network/GPU surface, and no change to the Database Schema itself (already finalized in `specs/technical_plan.md` across every prior module's own spec — this module implements it, doesn't redesign it). All gates above still PASS after design; no re-justification needed.

## Project Structure

### Documentation (this feature)

```text
specs/010-event-database/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md         # Phase 1 output (/speckit-plan command)
├── quickstart.md         # Phase 1 output (/speckit-plan command)
├── contracts/            # Phase 1 output (/speckit-plan command)
└── tasks.md              # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
src/cvip/
├── common/
│   └── diagnostics.py    # existing — reused as-is for ExecutionDiagnostics/emit_diagnostics
├── events/models.py       # existing — DetectedEvent's structural shape (event_type/timestamp_seconds/
│                           # innings/over_number/ball_in_over/player/team/confidence/importance/
│                           # is_replay/milestone_value) this module's event-batch input matches
├── video/scoreboard_ocr_models.py     # existing — ScoreboardSample's structural shape
├── video/replay_detection_models.py   # existing — ReplaySegment's structural shape
└── db/                     # NEW population — already-reserved empty scaffolding (CLAUDE.md
    │                        # Package Layout; specs/001-video-loader/plan.md's original scaffold)
    ├── __init__.py          # existing (empty)
    ├── models.py            # NEW: MatchMetadata, ScoreboardReadingRow, ReplaySegmentRow, EventRow,
    │                         #      EventQueryFilter, MatchSummary, MatchTimelineExport,
    │                         #      AnalysisStatusCondition (enum) — see data-model.md
    ├── errors.py            # NEW: EventDatabaseFailureReason + EventDatabaseError
    ├── schema.py            # NEW: CREATE TABLE DDL (verbatim from specs/technical_plan.md), the
    │                         #      embedded SCHEMA_VERSION this module checks on open, and the
    │                         #      open-or-create-schema logic (FR-001, FR-016, FR-017)
    └── database.py          # NEW: EventDatabase class + open_database() entry point — the
                               #      connection-lifecycle context manager wrapping all FR-003
                               #      through FR-018 operations (research.md Decision 1)

tests/
├── contract/
│   └── test_event_database_contract.py     # asserts db/database.py matches
│                                             # contracts/event_database_contract.md
├── integration/
│   └── test_event_database_e2e.py          # full lifecycle against a real temp SQLite file:
│                                             # fresh open -> begin -> persist three batches ->
│                                             # complete -> close -> reopen -> query/summarize/export
├── unit/
│   ├── test_event_database_lifecycle.py    # single-pass status (US1): not-yet-analyzed /
│   │                                        # already-analyzed / in-progress / forced reset
│   ├── test_event_database_persistence.py  # US2: batch persistence field-fidelity, empty-batch
│   │                                        # no-op, clip-window update isolation
│   ├── test_event_database_query.py        # US3: every filter individually and combined,
│   │                                        # match summary, timeline export
│   └── test_event_database_failures.py     # US4: corrupted file, schema-version mismatch,
│                                             # write-against-COMPLETE rejection
└── benchmark/
    └── test_event_database_performance.py  # SC-002/SC-005 against a full-match-scale synthetic
                                              # dataset (~12,600 readings, a few hundred events,
                                              # a few dozen replay segments)
```

**Structure Decision**: Single project (Option 1). Event Database gets its own subpackage, `src/cvip/db/`, exactly as CLAUDE.md's Package Layout section directs and exactly as `specs/001-video-loader/plan.md` originally scaffolded (`db/  # empty scaffolding — populated by the Event Database feature`). Within `db/`, files follow the same short-name, one-file-per-concern convention `events/` and `clips/` established (`models.py`, `errors.py`, and a primary module named after its function), with one addition specific to this module: `schema.py`, separating the DDL/schema-versioning concern from `database.py`'s runtime operations — a split neither `events/` nor `clips/` needed since neither owns a persistent schema. Tests use a real temporary SQLite file (`tmp_path`) rather than synthetic in-memory objects for the integration test specifically, since round-tripping through an actual file (close, reopen, still there) is the one thing this module exists to prove that no prior module's own test suite could exercise.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

None — the Constitution Check above found no violations, so no complexity needs justifying.
