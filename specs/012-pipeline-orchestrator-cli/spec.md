# Feature Specification: Pipeline Orchestrator and CLI

**Feature Branch**: `012-pipeline-orchestrator-cli`

**Created**: 2026-08-04

**Status**: Draft

**Input**: User description: "Implement the Pipeline Orchestrator and the `cvip` CLI entry point (specs/technical_plan.md's 'Pipeline Orchestrator' and 'CLI (MVP entry point)' sections; full command reference specs/cli.md) -- the piece that sequences Modules 1-10 (all already implemented and merged as independently-callable libraries) into an actual runnable end-to-end tool. Currently nothing wires them together: pyproject.toml declares a `cvip = 'cvip.cli:main'` console-script entry point but no src/cvip/cli.py exists at all. Required capabilities: `cvip analyze` (sequences Modules 1->1a->2->3->4->4a->5, single-pass enforcement via the Event Database, persists each stage's output as it completes, fails fast on any module error); `cvip generate --template match` (queries the Event Database, sequences Modules 8->9, never re-touches Modules 1-7); `cvip export-timeline`; `cvip inspect-db`; `cvip doctor` (environment/dependency check). Also implement specs/cli.md's Recommended Exit Codes table as a shared failure-to-exit-code mapping across every upstream module's own existing failure taxonomy. Architecturally: `src/cvip/orchestrator.py` owns `analyze`/`generate` sequencing (per technical_plan.md's own file-location note); `src/cvip/cli.py` owns argument parsing and delegation only, no sequencing logic of its own. `player`/`team`/`custom` `--template` values for `generate` are V1.5 scope -- accepted at the argument-parsing level per cli.md's own documented convention, rejected with a clear 'not yet implemented' error rather than attempted. An existing `IN_PROGRESS` match row (a prior `analyze` run that died mid-execution) is explicitly scoped down for this feature: `specs/technical_plan.md`'s own Pipeline Orchestrator section leaves true per-module resume as an unresolved follow-up, so this feature treats `IN_PROGRESS` the same as `COMPLETE` for the single-pass gate (blocks without `--force`, restarts fully with it) rather than attempting partial resume."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Analyze a Match Once, End to End (Priority: P1)

A user with a downloaded cricket broadcast video runs one command and, after the pipeline finishes, has a queryable database of every four, six, wicket, and team milestone the platform detected — without having to script together nine separate modules themselves.

**Why this priority**: This is the platform's entire reason to exist. Every module built so far (Video Loader through Event Database) is a correct, tested, independently-callable library with no way for an ordinary user to actually run it end-to-end — this user story is what turns nine finished libraries into one usable tool.

**Independent Test**: Run `cvip analyze` against a short real match video with no prior analysis on record. Confirm a database file exists afterward, `cvip inspect-db` against it reports a `COMPLETE` status with non-zero sample/event counts, and re-running `cvip analyze` against the exact same file without `--force` stops immediately (no frames decoded) rather than reprocessing.

**Acceptance Scenarios**:

1. **Given** a valid, never-before-analyzed MP4/MKV cricket broadcast, **When** the user runs `cvip analyze <path>`, **Then** every pipeline stage (Video Loader, Frame Extraction, Scene Detection, Replay Detection, Scoreboard OCR, OCR Timeline Smoother, Event Detection) runs in order, each stage's output is persisted to the Event Database as soon as that stage completes, and the match's database row ends in status `COMPLETE`.
2. **Given** a video whose exact file content was already analyzed to completion, **When** the user runs `cvip analyze <path>` again without `--force`, **Then** the command stops immediately with the platform's dedicated "already analyzed" exit code, without decoding a single frame or invoking any pipeline module.
3. **Given** the same already-analyzed video, **When** the user runs `cvip analyze <path> --force`, **Then** all of that match's prior scoreboard/replay/event data is discarded and a fresh analysis runs from the beginning.
4. **Given** a video for which some pipeline stage genuinely fails partway through (e.g. an unreadable file, a missing native dependency), **When** `cvip analyze` runs, **Then** the command stops immediately at that stage — no later stage runs — the match's database row (if one was created) ends in status `FAILED`, and the command exits with a specific, distinguishable exit code identifying what kind of failure occurred.
5. **Given** a prior `cvip analyze` run for this exact file that never reached completion (its database row is still `IN_PROGRESS`, e.g. the process was killed), **When** the user runs `cvip analyze <path>` again without `--force`, **Then** the command stops with the same "already analyzed" exit code as Scenario 2 (Assumptions) — a partially-completed prior run is not silently resumed or silently reprocessed.

---

### User Story 2 - Generate Highlights From an Already-Analyzed Match (Priority: P2)

A user who analyzed a match days or weeks ago runs one command to produce a highlight video from what's already stored — without re-running any video analysis.

**Why this priority**: This is the second half of the platform's core promise ("analyze once, generate unlimited highlights") — but it depends on User Story 1 having produced a database to read from, so it's the natural next slice rather than the first.

**Independent Test**: Against an already-`COMPLETE` match database (seeded directly, no real analysis needed for this story's own test), run `cvip generate <match_id> --template match --output <path>`. Confirm a playable output video file is produced whose content corresponds to the persisted events, and that no OCR/scene/replay-detection code path is ever invoked during the run.

**Acceptance Scenarios**:

1. **Given** a match database with several persisted events, **When** the user runs `cvip generate <match_id> --template match --output <path>` with no additional filters, **Then** an output video is produced from clips windowing every persisted, non-replay event, without re-touching Modules 1 through 7 or re-decoding the full source video beyond what clip extraction itself requires.
2. **Given** the same database, **When** the user adds `--min-importance`/`--start-over`/`--end-over`/`--event-type` filters, **Then** only clips for events matching all supplied filters are included in the output.
3. **Given** a `--template` value of `player`, `team`, or `custom`, **When** the user runs `cvip generate`, **Then** the command reports a clear "not yet implemented — planned for V1.5" error rather than attempting to run, crashing, or silently ignoring the flag.
4. **Given** a `match_id` with no corresponding database file, **When** the user runs `cvip generate`, **Then** the command fails fast with a specific "match not found" error rather than crashing on a missing-file exception.

---

### User Story 3 - Inspect an Analyzed Match's Contents (Priority: P3)

A user wants to see, at a glance, what a given analysis actually found before deciding how to filter a highlight reel from it.

**Why this priority**: Operational visibility that makes User Story 2's filters actually usable in practice (e.g. seeing the exact player-name strings OCR captured before filtering by one) — valuable, but the platform delivers its core value without it.

**Independent Test**: Against a seeded match database, run `cvip inspect-db <db_path>`. Confirm the printed summary's every field matches the database's actual persisted content exactly.

**Acceptance Scenarios**:

1. **Given** a fully analyzed match database, **When** the user runs `cvip inspect-db <db_path>`, **Then** the output includes match ID, source video path, duration, resolution, frame rate, analysis status and timestamp, scoreboard-sample/event/replay counts, event counts by type, and average confidence by type — each accurate against the persisted data.
2. **Given** a database file path that doesn't exist or isn't a valid CVIP database, **When** the user runs `cvip inspect-db`, **Then** the command fails fast with a specific, distinguishable error.

---

### User Story 4 - Export a Match's Full Timeline (Priority: P3)

A user wants the complete scoreboard and event timeline for a match as a plain data file, for their own external tooling, search, or debugging.

**Why this priority**: Same tier as User Story 3 — a read-only visibility capability, equally valuable and equally non-blocking for the platform's core value.

**Independent Test**: Against a seeded match database, run `cvip export-timeline <match_id> --format json --output <path>`. Confirm the output file contains every persisted scoreboard reading and event, field-for-field, with `snake_case` keys.

**Acceptance Scenarios**:

1. **Given** a fully analyzed match, **When** the user runs `cvip export-timeline <match_id> --format json --output <path>`, **Then** the output file is valid JSON containing every scoreboard reading and every event, `snake_case`-keyed exactly matching the database's own column names.
2. **Given** the same match, **When** the user runs the same command with `--format csv`, **Then** the output is a valid CSV covering the same event data.

---

### User Story 5 - Confirm the Local Machine Is Ready Before Analyzing (Priority: P4)

A user setting up the platform for the first time (or troubleshooting a failure) runs one command to confirm every required native tool and directory is actually available, before attempting a multi-hour analysis run that would otherwise fail partway through.

**Why this priority**: Pure operational convenience — genuinely useful for a fast, actionable diagnosis, but every check it performs would otherwise just surface as a slower, later failure inside `cvip analyze` itself; nothing about the platform's core value depends on this command existing.

**Independent Test**: Run `cvip doctor` on a machine with every dependency present; confirm an overall `OK` status. Remove or rename the `ffmpeg` executable from `PATH` and re-run; confirm `doctor` specifically flags FFmpeg as missing while every other check still reports its own individual status.

**Acceptance Scenarios**:

1. **Given** a machine with Python, FFmpeg, Tesseract, and all required Python packages present, and writable data/output/log directories, **When** the user runs `cvip doctor`, **Then** every individual check reports `OK` and the overall status is `OK`.
2. **Given** a machine missing one required native tool (FFmpeg or Tesseract), **When** the user runs `cvip doctor`, **Then** that specific check reports failure while every other check still runs and reports its own status, and the overall status is not `OK`.

---

### Edge Cases

- The source video path passed to `cvip analyze` doesn't exist, or exists but isn't a valid MP4/MKV — fails fast with the platform's "missing input file"/"unsupported video format" exit codes (specs/cli.md), before any pipeline module runs.
- A required native dependency (FFmpeg or Tesseract) is missing when `cvip analyze` or `cvip generate` actually needs it — fails fast with the platform's "missing native dependency" exit code, distinct from a `cvip doctor` check (which is voluntary and advisory; the pipeline itself must never silently proceed without the tool it actually needs, per constitution Principle VI).
- `--config` points to a config file with an unrecognized `config_version`, or a value outside a module's own already-documented valid range (e.g. a negative `pre_roll_seconds`) — fails fast with "invalid CLI arguments" before any module runs, since every value the config translates into is already validated by that module's own existing contract.
- `cvip generate` is run with filter combinations matching zero persisted events — produces a valid, empty highlight output (or a clear "no matching events" message), not a crash; matches Event Database's and Clip Generator's own established "empty result is valid, not an error" precedent.
- `cvip analyze` is interrupted by the user (e.g. Ctrl-C) mid-run — the in-progress match's database row remains `IN_PROGRESS`, handled identically to a crash (Acceptance Scenario US1-5) the next time `analyze` is run against the same file.
- Two different source videos happen to hash to file_hash collisions — out of scope; this feature inherits Video Loader's own existing file_hash collision assumptions verbatim, without re-deciding them.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST provide a `cvip analyze <video_path>` command that sequences Video Loader, Frame Extraction, Scene Detection, Replay Detection, Scoreboard OCR, the OCR Timeline Smoother, and Event Detection in that order, passing each stage's real output into the next per that stage's own already-established contract (Acceptance Scenario US1-1).
- **FR-002**: Before any pipeline stage runs, System MUST check the candidate video's file hash against the Event Database's existing match records; if a record already exists with status `COMPLETE` or `IN_PROGRESS` and the user did not pass `--force`, System MUST stop immediately without decoding any frame or invoking any pipeline stage, and exit with the platform's dedicated "already analyzed" exit code (Acceptance Scenarios US1-2, US1-5; constitution Principle III).
- **FR-003**: When `--force` is supplied against a video with an existing match record, System MUST discard that match's prior scoreboard/replay/event data and run a complete fresh analysis (Acceptance Scenario US1-3).
- **FR-004**: System MUST create a match record with status `IN_PROGRESS` before the first pipeline stage begins, and MUST persist each stage's output to the Event Database as soon as that stage completes — not deferred until the entire run finishes (Acceptance Scenario US1-1).
- **FR-005**: System MUST update the match record to status `COMPLETE` only after every pipeline stage has finished successfully, and to status `FAILED` if any stage fails, with no later stage ever running after an earlier stage's failure (Acceptance Scenario US1-4; constitution Principle VI).
- **FR-006**: System MUST provide a `cvip generate <match_id> --template match` command that reads already-persisted event data from the Event Database (filtered per any supplied `--player`/`--team`/`--event-type`/`--min-importance`/`--start-over`/`--end-over`/`--include-replays` arguments) and produces a highlight video from it, without invoking Video Loader, Frame Extraction, Scene Detection, Replay Detection, Scoreboard OCR, the OCR Timeline Smoother, or Event Detection at any point (Acceptance Scenarios US2-1, US2-2; constitution Principle III).
- **FR-007**: System MUST accept `--template player`, `--template team`, and `--template custom` as valid argument values, but MUST reject each with a clear "not yet implemented — planned for V1.5" error rather than attempting to run it (Acceptance Scenario US2-3).
- **FR-008**: System MUST fail fast with a specific "match not found" error when `cvip generate`, `cvip export-timeline`, or `cvip inspect-db` is given a `match_id`/database path with no corresponding, valid database file (Acceptance Scenario US2-4).
- **FR-009**: System MUST provide a `cvip export-timeline <match_id> --format json|csv` command producing every persisted scoreboard reading and event, `snake_case`-field-named, in the requested format (Acceptance Scenarios US4-1, US4-2).
- **FR-010**: System MUST provide a `cvip inspect-db <db_path>` command reporting match ID, source video path, duration, resolution, frame rate, analysis status and timestamp, scoreboard-sample/event/replay counts, event counts by type, and average confidence by type (Acceptance Scenario US3-1).
- **FR-011**: System MUST provide a `cvip doctor` command that independently checks Python version, FFmpeg availability, Tesseract availability, required Python package importability, and writable data/output/log directories, reporting each check's own individual status plus one overall status (Acceptance Scenarios US5-1, US5-2).
- **FR-012**: System MUST map every distinguishable failure this feature or any upstream module can produce onto the platform's documented exit-code table (`specs/cli.md`): 0 success, 1 general failure, 2 invalid CLI arguments, 3 missing input file, 4 unsupported video format, 5 missing native dependency, 6 OCR failure, 7 database failure, 8 FFmpeg export failure, 9 analysis already exists without `--force`.
- **FR-013**: System MUST validate CLI arguments (required arguments present, `--format`/`--template` values within their accepted sets, numeric filters well-formed) before invoking any pipeline stage or database operation, failing fast with exit code 2 on the first invalid argument found.
- **FR-014**: System MUST read every module's tuning configuration (scene detection threshold, OCR region/preprocessing, replay-detection signal weights, event pre-roll/post-roll/ranking, output container) from the `--config`-supplied YAML file exactly once per invocation, translating it into each module's own existing request configuration — no module reads the config file itself.
- **FR-015**: The `cvip` command-line entry point (argument parsing, help text, exit-code translation) MUST contain no pipeline-sequencing logic of its own — sequencing MUST live entirely in a separate orchestration layer the CLI delegates to, so that layer remains testable without spawning a subprocess or parsing argv.
- **FR-016**: System MUST log a clear, human-readable marker for the start and outcome of every pipeline stage during `cvip analyze`, so a long-running invocation's progress and eventual failure point are both visible without needing to inspect the Event Database directly.
- **FR-017**: An interrupted or crashed `cvip analyze` run MUST leave the match record in status `IN_PROGRESS`, never silently `COMPLETE` or silently deleted (Edge Cases; constitution Principle VI).

### Key Entities

- **Analysis Run**: One `cvip analyze` invocation's end-to-end progress through the seven analysis stages, tracked via the Event Database's own match-record lifecycle (`IN_PROGRESS` → `COMPLETE`/`FAILED`) — this feature's own coordination state, not a new persisted entity beyond what Event Database (Module 10) already defines.
- **Generate Request**: One `cvip generate` invocation's resolved inputs — the target match's database, the requested template, and the translated `EventQueryFilter` (Event Database's own filter shape) built from the command's `--player`/`--team`/`--event-type`/`--min-importance`/`--start-over`/`--end-over` arguments.
- **Exit Code Mapping**: The fixed translation table (FR-012) from every upstream module's own already-defined failure-reason taxonomy (Video Loader's, Scoreboard OCR's, Event Database's, Video Stitcher's, and this feature's own CLI-argument/single-pass conditions) to one of the ten documented process exit codes.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user with a working native-dependency setup can go from a raw match video file to a queryable, `COMPLETE` match database using a single command, with no manual scripting or direct Python calls into any individual module.
- **SC-002**: Re-running `cvip analyze` against an already-analyzed video without `--force` never re-decodes a frame or re-invokes a pipeline stage — verified by confirming the command returns before any pipeline-stage log marker (FR-016) is ever emitted.
- **SC-003**: A user can produce a highlight video from an already-analyzed match using a single command, and that command's execution time is dominated entirely by video stitching — never by re-running OCR, scene detection, or replay detection (SC-002's guarantee, applied to `generate`).
- **SC-004**: Every one of the ten documented exit codes (`specs/cli.md`) is reachable by at least one concrete, reproducible failure scenario — verified by a dedicated test per code, not left as an aspirational table with no enforcement behind it.
- **SC-005**: A user can diagnose a missing native dependency via `cvip doctor` in under a few seconds, without needing to start (and wait for) a multi-hour `cvip analyze` run just to discover the same problem partway through.
- **SC-006**: Every field `cvip inspect-db` and `cvip export-timeline` report is verifiably accurate against the underlying database's actual persisted content — zero discrepancies across a representative analyzed match.

## Assumptions

- **An `IN_PROGRESS` match record is treated identically to `COMPLETE` for the single-pass gate, not resumed** (Acceptance Scenario US1-5, FR-002): `specs/technical_plan.md`'s own Pipeline Orchestrator section explicitly leaves "the exact resume granularity (per-module vs. full-restart)" as an unresolved follow-up decision, not something that document itself settles. Building true per-module resume (skipping already-completed stages, restarting only from the point of failure) is real, additional design work with no existing specification to implement against. This feature instead makes the simplest safe choice consistent with the constitution's fail-fast principle: an interrupted run is never silently resumed or silently reprocessed — a user must explicitly pass `--force` to restart it, exactly as they would for a `COMPLETE` match. True per-module resume remains valid future scope, undesigned.
- **`--output-db` path resolution follows `specs/cli.md`'s already-documented default**: `data/matches/<file_hash[:12]>.sqlite` when omitted, a caller-supplied path otherwise — this feature implements that documented behavior, it does not redesign it.
- **Frame Extraction (Module 1a) is invoked as the shared service it already is**, once per consumer stage (Scene Detection, Replay Detection, Scoreboard OCR) at that stage's own required sampling rate, per each module's own existing contract — this feature does not introduce a new single shared extraction step; that would change three already-tested modules' own established calling convention.
- **`cvip doctor`'s checks are advisory, not a hard gate on `analyze`/`generate`**: a user can still attempt `cvip analyze` without running `doctor` first; `doctor`'s value is faster, clearer diagnosis, not enforcement. The pipeline's own real dependency checks (e.g. failing fast with exit code 5 if FFmpeg is actually invoked and missing) remain the enforcement mechanism, matching constitution Principle VI's "never silently proceed" requirement independent of whether `doctor` was ever run.
- **This feature does not implement `player`/`team`/`custom` `generate` templates' actual behavior** (FR-007) — only their argument-parsing acceptance and a clear rejection message. Implementing them is explicitly V1.5 scope per `specs/cli.md`'s own "Template implementation status" note, requiring V1.5-scope filtering logic this feature does not design.
- **No GUI, no interactive prompts, no network calls of any kind** — a strict, non-interactive command-line surface only, consistent with constitution Principle I (offline-first) and `specs/cli.md`'s own "Non-Goals for MVP CLI" section.
