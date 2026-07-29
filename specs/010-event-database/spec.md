# Feature Specification: Event Database

**Feature Branch**: `010-event-database`

**Created**: 2026-07-29

**Status**: Draft

**Input**: User description: "Implement the Event Database (the 'db' module referenced throughout specs/technical_plan.md's Database Schema section): the SQLite persistence and query layer underneath the whole CVIP pipeline, owning the matches, events, replays, and scoreboard_readings tables exactly as defined in specs/technical_plan.md's Database Schema. This module is not a linear pipeline stage like Modules 1-9 (each of which returns a self-contained in-memory result and explicitly does NOT write to the database itself, per their own contracts) -- it is the data-access layer those results eventually get persisted into, and the query layer Module 8 (Clip Generator) and the CLI (`cvip inspect-db`, `cvip export-timeline`, `cvip generate`) read back from. Required capabilities: (1) open-or-create a match database file (by file_hash-derived default path or a caller-supplied --output-db path, per specs/cli.md), (2) insert a `matches` row at the start of `cvip analyze` with status IN_PROGRESS, and update it to COMPLETE or FAILED at the end -- this is what makes the Pipeline Orchestrator's Single-Pass Analysis enforcement (constitution Principle III, exit code 9 per specs/cli.md) actually checkable: a fast file_hash lookup against the matches table before any analysis work begins; (3) bulk-insert `scoreboard_readings` rows (Module 4/4a's output), `replays` rows (Module 3's output), and `events` rows (Module 5's output, later updated with clip_start_seconds/clip_end_seconds by Module 8) after each corresponding pipeline stage completes; (4) a query API for `cvip generate`'s filter surface (--player, --team, --event-type, --min-importance, --start-over/--end-over per specs/cli.md) that returns an already-filtered event sequence structurally compatible with Module 8's ClipGenerationRequest.events input; (5) read-back queries for `cvip inspect-db` (match metadata, sample/event/replay counts, event counts by type, average confidence by type) and `cvip export-timeline` (the full scoreboard/event timeline as JSON or CSV). Must fail fast with specific reasons (e.g., corrupted database file, schema version mismatch, a write attempted against a match already marked COMPLETE) per constitution Principle VI, and must never itself touch a video frame, run OCR, or perform any analysis -- it is a pure persistence/query layer. See specs/technical_plan.md's Database Schema (exact table/column definitions, already finalized across Modules 1-9's own specs) and specs/cli.md for the full consumer surface this module must support."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Never Waste the 40-Minute Analysis Budget Twice (Priority: P1)

A user who accidentally (or deliberately, without `--force`) runs `cvip analyze` against a video file that's already been fully analyzed gets stopped immediately, before any frame is decoded or any OCR call is made -- not partway through a multi-hour re-run.

**Why this priority**: This is the mechanism behind constitution Principle III (Single-Pass Analysis) and `specs/cli.md`'s exit code 9 -- without it, that principle is aspirational prose with nothing actually enforcing it. Every other capability in this module exists to support a pipeline that only ever runs once per video.

**Independent Test**: Insert a `matches` row for a known `file_hash` with status `COMPLETE`. Ask the Event Database whether analysis should proceed for that same `file_hash`. Confirm it reports the specific "already analyzed" condition, distinct from "never analyzed" and from "analysis in progress."

**Acceptance Scenarios**:

1. **Given** no `matches` row exists for a candidate `file_hash`, **When** the caller checks whether to proceed, **Then** the Event Database reports that analysis has not yet run for this file.
2. **Given** a `matches` row exists for a candidate `file_hash` with status `COMPLETE`, **When** the caller checks whether to proceed, **Then** the Event Database reports the specific "already analyzed" condition.
3. **Given** a `matches` row exists for a candidate `file_hash` with status `IN_PROGRESS` (a prior run died mid-analysis), **When** the caller checks whether to proceed, **Then** the Event Database reports a specific "analysis in progress" condition, distinguishable from "already analyzed."
4. **Given** a caller explicitly requests a forced re-analysis for a `file_hash` that already has a `matches` row, **When** the Event Database is instructed to reset that match, **Then** all of that `file_hash`'s prior `scoreboard_readings`/`replays`/`events` rows are removed and the `matches` row is reset to `IN_PROGRESS`, so a fresh analysis can proceed without old and new data mixing.

---

### User Story 2 - Every Analysis Result Survives to Generate Highlights Later (Priority: P2)

A user who runs `cvip analyze` once, closes their terminal, and comes back days later to run `cvip generate` gets a highlight video built entirely from what was persisted during that single analysis run -- no re-analysis, no lost data.

**Why this priority**: This is what makes the platform's core two-phase promise ("analyze once, generate unlimited highlights") actually true. It's the write side of the persistence layer -- without it, every prior module's carefully-designed in-memory result (Module 3's replay segments, Module 4/4a's scoreboard readings, Module 5's detected events) evaporates the moment the process exits.

**Independent Test**: Supply a synthetic batch of scoreboard readings, replay segments, and detected events for a `file_hash`. Persist them. Re-open the database (a fresh connection, simulating a later `cvip generate` run) and confirm every row and every field comes back unchanged.

**Acceptance Scenarios**:

1. **Given** a batch of scoreboard readings from Module 4/4a, **When** persisted, **Then** every reading is retrievable afterward with all fields intact, in timestamp order.
2. **Given** a batch of replay segments from Module 3, **When** persisted, **Then** every segment is retrievable afterward with all fields intact.
3. **Given** a batch of detected events from Module 5, **When** persisted, **Then** every event is retrievable afterward with all fields intact, `clip_start_seconds`/`clip_end_seconds` initially `NULL`.
4. **Given** an already-persisted event, **When** its `clip_start_seconds`/`clip_end_seconds` are updated, **Then** only those two fields change -- every other column of that event's row is untouched.

---

### User Story 3 - Query and Inspect What Was Found (Priority: P3)

A user running `cvip generate --player "Virat Kohli" --event-type SIX` gets exactly the events matching that filter, ready to feed into Clip Generator -- and a user running `cvip inspect-db` or `cvip export-timeline` gets an accurate, complete picture of what a given analysis actually found.

**Why this priority**: This is the read side that makes the persisted data (User Story 2) actually useful -- Clip Generator needs a filtered event list to do anything, and users need visibility into their analyzed matches. It depends on User Story 2's data already existing, but doesn't block the platform's core analyze/persist value on its own.

**Independent Test**: Persist a representative mixed set of events (multiple players, teams, event types, importance scores, overs). Query with each supported filter individually and in combination; confirm each query returns exactly the matching events, in timestamp order, with zero false positives or negatives. Separately, request a match summary and a full timeline export; confirm both accurately reflect the persisted data.

**Acceptance Scenarios**:

1. **Given** events from multiple players, **When** queried with a `player` filter, **Then** only that player's events are returned (exact match, per `specs/cli.md`'s documented no-fuzzy-matching behavior).
2. **Given** events of multiple types, **When** queried with one or more `event_type` filters, **Then** only matching-type events are returned.
3. **Given** events with a range of `importance` scores, **When** queried with a minimum-importance filter, **Then** only events at or above that threshold are returned.
4. **Given** events across many overs, **When** queried with an over-range filter, **Then** only events whose `over_number` falls within that whole-over range are returned.
5. **Given** several filters combined, **When** queried, **Then** only events matching *all* supplied filters are returned.
6. **Given** a fully analyzed match, **When** a match summary is requested, **Then** it reports duration/resolution/frame rate/codec, analysis status, sample/event/replay counts, event counts by type, and average confidence by type -- each accurate against the persisted data.
7. **Given** a fully analyzed match, **When** a full timeline export is requested, **Then** every scoreboard reading and every event is included, with `snake_case` field names matching `specs/cli.md`'s documented export convention.

---

### User Story 4 - Fail Clearly on Corruption or Misuse (Priority: P4)

A user whose database file has become corrupted, or whose database file was written by an incompatible earlier version of this module, gets a clear and specific error the moment they try to use it -- never a silent misread that produces wrong or partial results.

**Why this priority**: An operational-reliability concern rather than a blocking one for the platform's core value (User Stories 1-3 all work correctly on a healthy database), but critical for trust in exactly the same way Video Stitcher's Output Validation is -- a database that silently returns wrong data because it was corrupted or from a different schema version is worse than an outright failure.

**Independent Test**: Present a database file that isn't valid SQLite (or one whose schema version doesn't match); confirm each is reported as a specific, distinguishable failure before any read or write is attempted against it. Separately, attempt a write against a `matches` row already marked `COMPLETE` (outside the explicit forced-reset path); confirm this is rejected with a specific reason.

**Acceptance Scenarios**:

1. **Given** a file at the resolved database path that is not a valid SQLite database, **When** the Event Database is opened, **Then** it fails fast with a specific reason identifying the corruption.
2. **Given** a valid SQLite database file whose schema version doesn't match this module's own expected version, **When** the Event Database is opened, **Then** it fails fast with a specific reason identifying the mismatch.
3. **Given** a `matches` row already marked `COMPLETE`, **When** a write (other than an explicit forced reset, User Story 1 Acceptance Scenario 4) is attempted against that match's data, **Then** it fails fast with a specific reason rather than silently corrupting a finished analysis.

---

### Edge Cases

- The resolved database file doesn't exist yet at all (first-ever analysis for this match) -- created fresh with the full schema (User Story 1 Acceptance Scenario 1).
- A batch to persist (scoreboard readings, replay segments, or events) is empty -- accepted as a valid, no-op batch, not an error (e.g., a match with zero replay segments detected).
- A query's filter combination matches zero events -- returns a valid, empty result, not an error.
- `clip_start_seconds`/`clip_end_seconds` are updated more than once for the same event across repeated `cvip generate` runs with different filters/settings -- each update succeeds and reflects only the most recent call; this is best-effort tracking, not the mechanism `generate` relies on for correctness (see Assumptions).
- A forced re-analysis (User Story 1 Acceptance Scenario 4) is requested for a `file_hash` that has *no* prior `matches` row -- treated the same as a fresh first-time analysis, not an error.
- The database file's parent directory doesn't exist -- out of scope for this module to create; see Assumptions (matches every prior module's "clean input/output contract" boundary).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST create the `matches`, `events`, `replays`, and `scoreboard_readings` tables (per `specs/technical_plan.md`'s Database Schema, exact column definitions) the first time a database file is opened at a path with no existing schema.
- **FR-002**: System MUST resolve the database file path from either a caller-supplied path or a `file_hash`-derived default, matching `specs/cli.md`'s `--output-db` behavior -- this module does not decide which to use, only accepts whichever the caller resolves.
- **FR-003**: Before any analysis work begins for a candidate `file_hash`, System MUST report whether a `matches` row already exists for it with status `COMPLETE` -- a specific, distinguishable "already analyzed" condition (Acceptance Scenario US1-2).
- **FR-004**: System MUST report a specific, distinguishable "analysis in progress" condition -- distinct from FR-003's "already analyzed" -- when an existing `matches` row's status is `IN_PROGRESS` (Acceptance Scenario US1-3).
- **FR-005**: System MUST insert one `matches` row with status `IN_PROGRESS` at the start of a new analysis for a `file_hash` with no prior row (Acceptance Scenario US1-1).
- **FR-006**: System MUST update a `matches` row's status to `COMPLETE` or `FAILED` as instructed by the caller at the end of an analysis run.
- **FR-007**: When explicitly instructed to start a forced re-analysis for a `file_hash` that already has a `matches` row, System MUST remove that `file_hash`'s prior `scoreboard_readings`/`replays`/`events` rows and reset its `matches` row to `IN_PROGRESS` before returning control to the caller (Acceptance Scenario US1-4).
- **FR-008**: System MUST persist a batch of `scoreboard_readings` rows, preserving every field and timestamp order (Acceptance Scenario US2-1).
- **FR-009**: System MUST persist a batch of `replays` rows, preserving every field (Acceptance Scenario US2-2).
- **FR-010**: System MUST persist a batch of `events` rows, preserving every field, with `clip_start_seconds`/`clip_end_seconds` initially `NULL` (Acceptance Scenario US2-3).
- **FR-011**: System MUST support updating an already-persisted event's `clip_start_seconds`/`clip_end_seconds` independently, without altering any other column of that event's row (Acceptance Scenario US2-4).
- **FR-012**: System MUST provide an event query supporting any combination of: exact-match `player`, exact-match `team`, one or more `event_type` values, a minimum `importance` threshold, and a whole-over `over_number` range -- matching `specs/cli.md`'s `generate` filter surface -- returning matches ordered by `timestamp_seconds` (Acceptance Scenarios US3-1 through US3-5).
- **FR-013**: The event sequence FR-012's query returns MUST be structurally compatible with Module 8's `ClipGenerationRequest.events` input (an `event_id`/`timestamp_seconds`/`is_replay`-exposing shape, per Clip Generator's own structural contract).
- **FR-014**: System MUST provide a match-summary read -- duration, resolution, frame rate, codec, analysis status, sample/event/replay counts, event counts by type, and average confidence by type -- for `cvip inspect-db` (Acceptance Scenario US3-6).
- **FR-015**: System MUST provide a full-timeline read (every `scoreboard_readings` and `events` row for a match) in a form ready for JSON/CSV serialization with `snake_case` field names, matching `specs/cli.md`'s `export-timeline` convention (Acceptance Scenario US3-7).
- **FR-016**: System MUST fail fast with a specific, distinguishable reason if the file at the resolved database path exists but is not a valid SQLite database (Acceptance Scenario US4-1).
- **FR-017**: System MUST fail fast with a specific, distinguishable reason if an existing database file's schema version does not match this module's own expected version (Acceptance Scenario US4-2).
- **FR-018**: System MUST fail fast with a specific, distinguishable reason if a write (other than the explicit forced-reset path, FR-007) is attempted against a `matches` row already marked `COMPLETE` (Acceptance Scenario US4-3).
- **FR-019**: System MUST NOT touch a video file, video frame, OCR engine, or perform any form of match analysis -- it operates purely on already-computed data supplied by callers (constitution Principle III; matching every prior module's own "clean input/output contract" boundary, in reverse -- this module is the one prior modules explicitly deferred writing to).
- **FR-020**: System MUST emit one diagnostics record (the platform's shared `ExecutionDiagnostics` shape) per significant write operation -- database/schema creation, the single-pass check, each bulk-insert batch, a status update, and a forced reset -- matching every prior module's own diagnostics precedent. Read-only queries are not required to each emit their own diagnostics record.

### Key Entities

- **Match Record**: One row's worth of match-level state -- `match_id`, `file_hash`, video metadata (duration/resolution/frame rate/codec), `status` (`IN_PROGRESS`/`COMPLETE`/`FAILED`), `analyzed_at`.
- **Scoreboard Reading Batch**: A caller-supplied sequence of raw per-second OCR readings (Module 4/4a's output shape) to persist in one call.
- **Replay Segment Batch**: A caller-supplied sequence of replay segments (Module 3's output shape) to persist in one call.
- **Event Batch**: A caller-supplied sequence of detected events (Module 5's output shape) to persist in one call.
- **Event Query Filter**: The caller-supplied combination of `player`, `team`, `event_type`(s), minimum `importance`, and over-range used to select a subset of persisted events (FR-012).
- **Match Summary**: The read-only aggregate view of one match's persisted state, for `cvip inspect-db` (FR-014).
- **Match Timeline Export**: The read-only full-detail view of one match's persisted scoreboard/event data, for `cvip export-timeline` (FR-015).
- **Event Database Failure Reason**: The run-level failure taxonomy for this feature -- covers a corrupted/unreadable database file, a schema-version mismatch, and a rejected write against an already-`COMPLETE` match.
- **Analysis Status Condition**: The three-way outcome of checking whether analysis should proceed for a `file_hash` -- not yet analyzed, already analyzed (`COMPLETE`), or in progress (`IN_PROGRESS`) -- distinct from `Event Database Failure Reason`, since none of these three outcomes represents this module malfunctioning.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Checking whether a `file_hash` has already been analyzed completes in well under a second regardless of database size, and correctly distinguishes "never analyzed," "already analyzed," and "analysis in progress" with zero misclassifications.
- **SC-002**: Every scoreboard reading, replay segment, and detected event supplied to this module is retrievable afterward with all fields intact and unchanged, verified for representative full-match volumes (on the order of 12,600 scoreboard readings, a few hundred events, a few dozen replay segments).
- **SC-003**: An event query filtered by any single criterion or any combination of criteria returns exactly the matching events, in timestamp order, with zero false positives or false negatives, verified against a representative mixed dataset.
- **SC-004**: A corrupted database file, a schema-version mismatch, and a write against an already-`COMPLETE` match each produce a specific, distinguishable failure reason, with zero silent misbehavior, verified across all three cases.
- **SC-005**: Persisting a full match's worth of data (on the order of 12,600 scoreboard readings, a few hundred events, a few dozen replay segments) completes in well under a minute -- a small fraction of the platform's overall 40-minute `analyze` budget.
- **SC-006**: `cvip inspect-db`'s summary and `cvip export-timeline`'s full timeline both exactly reflect the data persisted for a representative match, field for field.

## Assumptions

- **Single-process access only**: this module assumes one CLI invocation (one `cvip analyze` or `cvip generate` process) accesses a given match database at a time -- concurrent multi-process read/write support is not required for MVP; SQLite's own file-level locking is sufficient for this access pattern.
- **`clip_start_seconds`/`clip_end_seconds` persistence (FR-011) is best-effort tracking, not the mechanism `generate` relies on for correctness**: each `cvip generate` invocation recomputes its own clip plan fresh via Clip Generator, using only FR-012's query results (`timestamp_seconds`, not any previously-persisted clip window) -- this matters because a single event can appear in many different generated highlight videos with different pre-roll/post-roll settings, so no single "the" clip window can be authoritative for an event across repeated `generate` calls.
- **This module does not create the database file's parent directory**: matching every prior module's "clean input/output contract" boundary, directory creation (if desired) is the Pipeline Orchestrator's or CLI's responsibility.
- **This module does not decide whether `--force` applies**: it exposes the primitives ("check for existing analysis," FR-003/FR-004; "reset for forced re-analysis," FR-007) that the Pipeline Orchestrator uses to implement `--force`'s actual behavior -- this module never reads CLI flags itself, matching every prior module's own precedent of accepting caller-resolved values, not config/CLI state directly.
- **`player`/`team` filtering (FR-012) is exact-match only**: matching `specs/cli.md`'s own documented limitation, no fuzzy matching, alias table, or player-roster normalization is in scope.
- **Schema version is a value this module embeds in and checks against the database file itself** (distinct from `config/default.yaml`'s own `config_version`), so a database file written by an incompatible future or past version of this module is detected (FR-017) rather than silently misread.
