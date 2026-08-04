# Data Model: Event Database

Derived from the Key Entities section of [spec.md](./spec.md) and `specs/technical_plan.md`'s Database Schema (the authoritative table/column definitions this module implements, not redesigns). Unlike every prior module, this feature *does* own persistent storage — most entities below map directly onto a schema table; a few (`EventQueryFilter`, `AnalysisStatusCondition`, `MatchSummary`, `MatchTimelineExport`) are pure in-memory request/response shapes with no table of their own.

**Naming note (`event_key` vs. `event_id`)**: `research.md` Decision 10. `events.event_id` (the schema's own SQLite autoincrement primary key, an `int`) is this module's internal row identity. `QueriedEvent.event_key` (a `str`, `= str(event_id)`) is what `query_events()` actually returns on each row — the literal attribute name Clip Generator's own, already-implemented structural contract requires (`src/cvip/clips/generator.py`), not the `event_id` naming spec.md's FR-013 prose loosely used.

## MatchMetadata

Input to `begin_analysis()` — the caller-supplied (Video Loader's `LoadResult`-derived, per FR-005) values for a new `matches` row.

| Field | Type | Notes |
|---|---|---|
| `file_hash` | str | Required. Video Loader's FR-014 sampled digest — the single-pass identity (FR-003/FR-004). |
| `source_video_path` | str | Required. |
| `duration_seconds` | float or `None` | |
| `resolution_width` | int or `None` | |
| `resolution_height` | int or `None` | |
| `frame_rate` | float or `None` | |
| `codec` | str or `None` | |

## ScoreboardReadingLike (structural input shape)

One element of the sequence passed to `persist_scoreboard_readings()` (research.md Decision 8) — the real-world input is Module 4/4a's `ScoreboardSample`/`CleanedScoreboardSample`, matched by field, not by import.

| Field | Type | Maps to column |
|---|---|---|
| `timestamp_seconds` | float | `scoreboard_readings.timestamp_seconds` |
| `innings` | int or `None` | `scoreboard_readings.innings` — reconstructed by the caller (Pipeline Orchestrator), since no upstream module tracks innings itself (`specs/007-event-detection/spec.md` Assumptions); this module never derives it. |
| `over_number` | int or `None` | `scoreboard_readings.over_number` |
| `ball_in_over` | int or `None` | `scoreboard_readings.ball_in_over` |
| `runs` | int or `None` | `scoreboard_readings.runs` |
| `wickets` | int or `None` | `scoreboard_readings.wickets` |
| `batter` | str or `None` | `scoreboard_readings.batter` |
| `non_striker` | str or `None` | `scoreboard_readings.non_striker` |
| `bowler` | str or `None` | `scoreboard_readings.bowler` |
| `run_rate` | float or `None` | `scoreboard_readings.run_rate` |
| `raw_text` | str | `scoreboard_readings.raw_text` |
| `ocr_confidence` | float | `scoreboard_readings.ocr_confidence` |
| `parse_confidence` | float | `scoreboard_readings.parse_confidence` |

## ReplaySegmentLike (structural input shape)

One element of the sequence passed to `persist_replays()` — matches Module 3's `ReplaySegment` by field.

| Field | Type | Maps to column |
|---|---|---|
| `start_seconds` | float | `replays.start_seconds` |
| `end_seconds` | float | `replays.end_seconds` |
| `confidence` | float | `replays.confidence` |

`replays.replay_id` is assigned by Replay Detection itself (`specs/technical_plan.md`'s schema comment: "intended to be inserted here as the literal primary key value... not an auto-assigned rowid") — so `ReplaySegmentLike` also exposes `replay_id: int`, inserted explicitly rather than left to SQLite's autoincrement, unlike `events`/`scoreboard_readings`.

## EventLike (structural input shape)

One element of the sequence passed to `persist_events()` — matches Module 5's `DetectedEvent` by field (research.md Decision 8). `event_id` is **not** read from this shape — it's always SQLite-assigned on insert (Decision 10's whole premise: the schema's primary key is the durable identity, `DetectedEvent.event_key` is a pre-persistence-only concern, research.md Decision 7 of *this* module).

| Field | Type | Maps to column |
|---|---|---|
| `timestamp_seconds` | float | `events.timestamp_seconds` |
| `innings` | int | `events.innings` |
| `over_number` | int | `events.over_number` |
| `ball_in_over` | int | `events.ball_in_over` |
| `event_type` | str | `events.event_type` (`FOUR`/`SIX`/`WICKET`/`TEAM_MILESTONE`) |
| `player` | str or `None` | `events.player` |
| `team` | str or `None` | `events.team` |
| `confidence` | float | `events.confidence` |
| `importance` | int | `events.importance` |
| `milestone_value` | int or `None` | `events.milestone_value` |
| `is_replay` | bool | `events.is_replay` |

`events.clip_start_seconds`/`clip_end_seconds` are always `NULL` on insert (FR-010) — populated later, only via `update_clip_window()`.

## AnalysisStatusCondition

The three-way outcome of `check_analysis_status(file_hash)` (spec.md Key Entities, FR-003/FR-004) — an enum, not a free-form string.

| Value | Meaning |
|---|---|
| `NOT_ANALYZED` | No `matches` row exists for this `file_hash`. |
| `IN_PROGRESS` | A `matches` row exists with `status = 'IN_PROGRESS'` (a prior run is active or died mid-analysis). |
| `COMPLETE` | A `matches` row exists with `status = 'COMPLETE'`. |

A `matches` row with `status = 'FAILED'` also reports `NOT_ANALYZED` — a failed prior run is not "already analyzed" in any sense a caller checking whether to proceed should be blocked by; a fresh `begin_analysis()` for the same `file_hash` overwrites it the same way a first-ever analysis would (FR-005 doesn't distinguish "no row" from "a `FAILED` row" as a precondition).

## EventQueryFilter

The caller-supplied combination of criteria for `query_events()` (spec.md Key Entities, FR-012). Every field is optional; `None`/empty means "no constraint from this field" (research.md Decision 6).

| Field | Type | Notes |
|---|---|---|
| `player` | str or `None` | Exact match (`specs/cli.md`'s documented no-fuzzy-matching behavior). |
| `team` | str or `None` | Exact match. |
| `event_types` | tuple[str, ...] or `None` | One or more of `FOUR`/`SIX`/`WICKET`/`TEAM_MILESTONE`; `IN (...)` when supplied. |
| `min_importance` | int or `None` | `importance >= min_importance`. |
| `start_over` | int or `None` | Whole-over integer, inclusive (`specs/cli.md`: over granularity, not ball granularity). |
| `end_over` | int or `None` | Whole-over integer, inclusive. |

## QueriedEvent

One row `query_events()` returns — structurally compatible with Clip Generator's `ClipGenerationRequest.events` input (FR-013, research.md Decision 10) and with everything `cvip inspect-db`/`export-timeline` need per-event.

| Field | Type | Notes |
|---|---|---|
| `event_key` | str | `str(events.event_id)` — see Decision 10; the field name/type Clip Generator's real contract requires. |
| `timestamp_seconds` | float | |
| `innings` | int | |
| `over_number` | int | |
| `ball_in_over` | int | |
| `event_type` | str | |
| `player` | str or `None` | |
| `team` | str or `None` | |
| `confidence` | float | |
| `importance` | int | |
| `milestone_value` | int or `None` | |
| `is_replay` | bool | |
| `clip_start_seconds` | float or `None` | |
| `clip_end_seconds` | float or `None` | |

Ordered by ascending `timestamp_seconds` (FR-012), matching every prior module's own output-ordering convention (Module 5's `DetectedEvent` sequence, Module 8's `PlannedClip` sequence).

## MatchSummary

The read-only aggregate view for `cvip inspect-db` (spec.md Key Entities, FR-014, `specs/cli.md`'s documented output fields).

| Field | Type | Notes |
|---|---|---|
| `match_id` | str | |
| `source_video_path` | str | |
| `file_hash` | str | |
| `duration_seconds` | float or `None` | |
| `resolution_width` | int or `None` | |
| `resolution_height` | int or `None` | |
| `frame_rate` | float or `None` | |
| `codec` | str or `None` | |
| `status` | str | `IN_PROGRESS`/`COMPLETE`/`FAILED` |
| `analyzed_at` | str | ISO timestamp, as stored. |
| `scoreboard_reading_count` | int | `COUNT(*)` from `scoreboard_readings`. |
| `event_count` | int | `COUNT(*)` from `events`. |
| `replay_count` | int | `COUNT(*)` from `replays`. |
| `event_counts_by_type` | dict[str, int] | e.g. `{"FOUR": 12, "SIX": 3, "WICKET": 7, "TEAM_MILESTONE": 4}` — a type with zero events is simply absent, never a `0`-valued key (matches SQL `GROUP BY`'s natural behavior; no synthetic zero-filling). |
| `average_confidence_by_type` | dict[str, float] | Same per-type-presence rule as `event_counts_by_type`. |

## MatchTimelineExport

The read-only full-detail view for `cvip export-timeline` (spec.md Key Entities, FR-015).

| Field | Type | Notes |
|---|---|---|
| `match_id` | str | |
| `scoreboard_readings` | tuple[dict, ...] | Every `scoreboard_readings` row, `snake_case` keys matching column names exactly (`specs/cli.md`'s documented export convention), ordered by `timestamp_seconds`. |
| `events` | tuple[dict, ...] | Every `events` row, `snake_case` keys matching column names exactly, ordered by `timestamp_seconds`. |

Returned as plain `dict`s (not typed dataclasses) specifically because the caller's own job (JSON/CSV serialization, `--format`) needs exactly this shape with zero further field-name translation — matching `specs/cli.md`'s explicit callout that JSON field names must match the database schema's own `snake_case` columns verbatim.

## EventDatabaseFailureReason

The run-level failure taxonomy for this feature (spec.md Key Entities, FR-016 through FR-018).

| Value | Meaning |
|---|---|
| `CORRUPTED_DATABASE_FILE` | The file at the resolved path exists but fails `PRAGMA integrity_check` (research.md Decision 4). |
| `SCHEMA_VERSION_MISMATCH` | An existing file's `PRAGMA user_version` doesn't match this module's own `SCHEMA_VERSION` (research.md Decision 3). |
| `WRITE_AGAINST_COMPLETED_MATCH` | A write (other than the explicit forced-reset path) is attempted while the open connection's tracked match status is `COMPLETE` (research.md Decision 5). |

## EventDatabaseDiagnostics

One per significant write operation (FR-020, research.md Decision 9) — reuses the platform-wide `ExecutionDiagnostics` shape (`src/cvip/common/diagnostics.py`) rather than defining a new one.

| `ExecutionDiagnostics` field | How this feature populates it |
|---|---|
| `module_name` | `"db.database"` |
| `input_summary` | The operation performed (e.g. `"persist_events"`, `"begin_analysis"`, `"reset_for_forced_reanalysis"`) plus its own relevant parameters (e.g. batch size, `file_hash`) |
| `output_summary` | Operation-specific: e.g. for a persist, `rows_written=`; for a status check, `status_reported=`; for a reset, `readings_removed=`/`replays_removed=`/`events_removed=`; always includes `schema_version=` |
| `warnings` | Reserved for future use — no warning conditions are currently defined for this feature |
| `failure_reason` | An `EventDatabaseFailureReason` value, or `null` on success |
