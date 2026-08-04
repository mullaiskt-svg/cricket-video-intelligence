# Contract: Event Database

This module exposes one entry point and a set of methods on the object it returns — not the single `request in, result out` shape every prior module (1-9) uses (`plan.md` Summary, `research.md` Decision 1). It is an internal Python library contract (no network/CLI surface), consistent with constitution Principle V.

## `open_database(path: Path) -> EventDatabase`

**Input**: `path`, an already-resolved database file path (this module never decides the path itself — FR-002; the Pipeline Orchestrator/CLI resolves `--output-db` or the `file_hash[:12]`-derived default before calling this).

**Output**: an `EventDatabase` — a context-manager object.

**Usage**:
```python
with open_database(path) as db:
    ...  # any sequence of the methods below
# on exit (normal or exception): the SQLite connection is closed;
# every write already committed by this point remains durable
```

**On `__enter__`** (research.md Decisions 3, 4): if `path` doesn't exist, a fresh file is created with the full schema (`CREATE TABLE`s per `specs/technical_plan.md`) and `PRAGMA user_version` set to `SCHEMA_VERSION` (FR-001). If `path` exists, `PRAGMA integrity_check` runs first — anything other than `('ok',)` raises `EventDatabaseError(CORRUPTED_DATABASE_FILE)` immediately, before any table is touched (FR-016). Otherwise `PRAGMA user_version` is compared against `SCHEMA_VERSION` — a mismatch raises `EventDatabaseError(SCHEMA_VERSION_MISMATCH)` (FR-017). Both checks emit a diagnostics record on failure.

## Capability 1: Single-pass status (US1)

### `db.check_analysis_status(file_hash: str) -> AnalysisStatusCondition`

Returns `NOT_ANALYZED`, `IN_PROGRESS`, or `COMPLETE` (data-model.md) — a pure read, no diagnostics record required (FR-020 exempts read-only queries), completing in well under a second via `idx_matches_file_hash` regardless of database size (SC-001).

### `db.begin_analysis(metadata: MatchMetadata) -> None`

**Preconditions**: none beyond `metadata.file_hash`/`metadata.source_video_path` being present — `INVALID_INPUT` if either is missing.

**Postconditions**: inserts one `matches` row with `status = 'IN_PROGRESS'` (FR-005). If a row for this `file_hash` already exists, its prior state is left untouched and this call raises `EventDatabaseError(WRITE_AGAINST_COMPLETED_MATCH)` only if that existing row's status is `COMPLETE` — an existing `IN_PROGRESS` or `FAILED` row is silently reused as the active match (matching `reset_for_forced_reanalysis`'s own "no prior row = treat as fresh" precedent, Edge Cases). Sets the connection's tracked status (research.md Decision 5) to `IN_PROGRESS`.

### `db.complete_analysis() -> None` / `db.fail_analysis() -> None`

Updates the current match's `matches.status` to `COMPLETE`/`FAILED` (FR-006) and the connection's tracked status accordingly. Raises `EventDatabaseError(WRITE_AGAINST_COMPLETED_MATCH)` if the tracked status is already `COMPLETE` (a completed match cannot be re-completed or failed after the fact without an explicit reset).

### `db.reset_for_forced_reanalysis(file_hash: str) -> None`

**Postconditions** (FR-007): every `scoreboard_readings`/`replays`/`events` row is deleted (this is a single-match-per-file database, so this is an unconditional `DELETE FROM <table>`, not a `file_hash`-scoped one), the `matches` row for `file_hash` is reset to `status = 'IN_PROGRESS'` (inserted fresh if none existed — Edge Cases), and the connection's tracked status becomes `IN_PROGRESS`. This is the one write path that bypasses the `WRITE_AGAINST_COMPLETED_MATCH` gate by design.

## Capability 2: Persistence (US2)

### `db.persist_scoreboard_readings(readings: Sequence[ScoreboardReadingLike]) -> None`
### `db.persist_replays(segments: Sequence[ReplaySegmentLike]) -> None`
### `db.persist_events(events: Sequence[EventLike]) -> None`

**Preconditions**: the connection's tracked status must not be `COMPLETE` (research.md Decision 5) — otherwise `EventDatabaseError(WRITE_AGAINST_COMPLETED_MATCH)` (FR-018), and no row from this batch is written.

**Postconditions**: every element is inserted via one batched `executemany()` call inside a single transaction (all-or-nothing per batch — a mid-batch failure leaves no partial rows from that call), preserving every field exactly and `scoreboard_readings`' own `timestamp_seconds` order (FR-008, FR-009, FR-010). An empty sequence is a valid no-op — zero rows inserted, no error (Edge Cases). `events.clip_start_seconds`/`clip_end_seconds` are always `NULL` immediately after `persist_events` (FR-010). Each call emits one diagnostics record (FR-020).

### `db.update_clip_window(event_key: str, clip_start_seconds: float, clip_end_seconds: float) -> None`

**Postconditions**: updates only `clip_start_seconds`/`clip_end_seconds` on the `events` row whose `event_id = int(event_key)` — every other column of that row is untouched (FR-011). Subject to the same `WRITE_AGAINST_COMPLETED_MATCH` gate as the batch-persist methods. Repeated calls for the same `event_key` each succeed and reflect only the most recent call (Edge Cases; Assumptions — best-effort tracking, not `generate`'s correctness mechanism).

## Capability 3: Query and inspection (US3)

### `db.query_events(filter: EventQueryFilter) -> tuple[QueriedEvent, ...]`

Pure read. Returns every `events` row matching **all** supplied filter criteria (research.md Decision 6), ordered by ascending `timestamp_seconds` (FR-012). An all-`None`/empty filter returns every event. A filter combination matching nothing returns `()`, never an error (Edge Cases). The returned `QueriedEvent.event_key` is `str(event_id)` (data-model.md, research.md Decision 10) — structurally compatible with Clip Generator's `ClipGenerationRequest.events` input as-is, with no adaptation needed by the caller (FR-013).

### `db.get_match_summary() -> MatchSummary`

Pure read. Aggregates the current match's `matches` row plus `COUNT`/`GROUP BY` aggregates over `scoreboard_readings`/`events`/`replays` (FR-014, data-model.md). `event_counts_by_type`/`average_confidence_by_type` omit any `event_type` with zero rows rather than reporting a synthetic `0` (data-model.md note).

### `db.get_match_timeline() -> MatchTimelineExport`

Pure read. Every `scoreboard_readings` and `events` row as plain `snake_case`-keyed dicts, ordered by `timestamp_seconds` (FR-015), ready for direct JSON/CSV serialization with no further field-name translation (`specs/cli.md`'s documented export convention).

## Error taxonomy (`EventDatabaseFailureReason` values)

| Value | Meaning | Example trigger |
|---|---|---|
| `CORRUPTED_DATABASE_FILE` (FR-016) | The file at `path` exists but fails `PRAGMA integrity_check` | A truncated or non-SQLite file at the resolved path |
| `SCHEMA_VERSION_MISMATCH` (FR-017) | An existing file's `PRAGMA user_version` doesn't match this module's `SCHEMA_VERSION` | A database written by an incompatible past/future version of this module |
| `WRITE_AGAINST_COMPLETED_MATCH` (FR-018) | A write (other than `reset_for_forced_reanalysis`) is attempted while the tracked match status is `COMPLETE` | Calling `persist_events()` after `complete_analysis()` without an explicit reset |

Every raise is `EventDatabaseError(reason, detail)`, matching every prior module's own error-taxonomy shape (`cvip.<module>.errors`).

## Consumer obligation

The Pipeline Orchestrator MUST call `begin_analysis()` before any of Modules 1-9 run, persist each stage's output as soon as that stage completes (not batched to the very end — FR-020's per-operation diagnostics granularity assumes this), and call `complete_analysis()`/`fail_analysis()` exactly once at the end of an `analyze` invocation, regardless of outcome. A `generate`/`inspect-db`/`export-timeline` consumer MUST open the database read-only in intent (no persistence calls) and MUST pass `query_events()`'s results to Clip Generator (`ClipGenerationRequest.events`) without re-deriving or adapting `event_key`/`timestamp_seconds`/`is_replay` — this module already produces the exact shape Clip Generator's own contract requires (FR-013, research.md Decision 10).
