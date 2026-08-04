# Contract: Pipeline Orchestrator (`src/cvip/orchestrator.py`)

Two entry points, both plain functions (research.md Decision 1) — not the Runner-context-manager shape every detection/transformation module (2-9) uses, since this module composes those Runners rather than being one itself.

## `analyze(request: AnalyzeRequest) -> AnalysisRun`

**Input**: an `AnalyzeRequest` (data-model.md) — built entirely by `cli.py`; this function never reads `sys.argv`, a config file path, or any CLI flag itself (research.md Decision 8).

**Sequence** (FR-001, research.md Decisions 2, 3, 6):

1. Run Video Loader (`load_video`). On `FailureReason.FILE_NOT_FOUND` → `OrchestratorError(MISSING_INPUT_FILE)`; on `FailureReason.UNSUPPORTED_FORMAT` → `OrchestratorError(UNSUPPORTED_VIDEO_FORMAT)`; any other `FailureReason` → `OrchestratorError(GENERAL_FAILURE)`.
2. Open the Event Database at the resolved `output_db_path` (`--output-db`, or the `file_hash[:12]`-derived default). Call `check_analysis_status(file_hash)`. If `COMPLETE` or `IN_PROGRESS` and `request.force` is `False` → `OrchestratorError(ALREADY_ANALYZED)`, no further stage runs (FR-002). If `request.force` is `True` and a prior record exists, call `reset_for_forced_reanalysis(file_hash)` (FR-003).
3. Run the native-dependency preflight check (research.md Decision 6). Either missing → `OrchestratorError(MISSING_NATIVE_DEPENDENCY)`.
4. Call `begin_analysis(MatchMetadata(...))` (FR-004).
5. Run Scene Detection (`detect_scenes`), passing `load_result` and `config`-derived `scene_threshold`. Persist nothing from this stage directly (its result feeds Replay Detection; Event Database has no `scene_detection` table of its own per `specs/technical_plan.md`'s schema).
6. Run Replay Detection (`detect_replays`), passing `load_result`, the Scene Detection result, and `config`-derived signal weights/thresholds. Persist its segments via `persist_replays()` immediately on success (FR-004).
7. Run Scoreboard OCR (`extract_scoreboard`), passing `load_result` and `config`-derived region/preprocessing/confidence settings. Persist its raw samples via `persist_scoreboard_readings()` immediately on success (FR-004).
8. Run the OCR Timeline Smoother (`smooth_timeline`), passing the raw OCR result.
9. Run Event Detection (`detect_events`), passing the cleaned timeline, the raw OCR result, the replay result, and `config`-derived `team_milestone_interval`/`ranking`. Persist its events via `persist_events()` immediately on success (FR-004).
10. Call `complete_analysis()` (FR-005). If `request.timeline_path` was supplied, additionally write `get_match_timeline()`'s JSON there.
11. Return an `AnalysisRun`.

Any stage's own typed error (steps 5-9) is caught, `fail_analysis()` is called on the open `EventDatabase` connection (FR-005), and the stage's own reason is translated per research.md Decision 7's mapping table before re-raising as `OrchestratorError`. No stage after the failing one ever runs (FR-005; constitution Principle VI).

**Postconditions**:
- A returned `AnalysisRun` always has `status == "COMPLETE"` and `stages_completed` containing all six stage names in order.
- Every raised `OrchestratorError` corresponds to a match record left in status `FAILED` (if a record was ever created) or, for `ALREADY_ANALYZED`/argument-validation failures, no new record created/modified at all beyond what already existed (FR-002, FR-017).
- A human-readable log marker is emitted at the start and outcome of every one of the six stages (FR-016), regardless of success or failure.

## `generate(request: GenerateRequest) -> GenerateResult`

**Input**: a `GenerateRequest` (data-model.md).

**Sequence** (FR-006, FR-007):

1. If `request.template != "match"` → `OrchestratorError(INVALID_ARGUMENTS, detail="template '{template}' not yet implemented -- planned for V1.5")` (FR-007). No database is opened for this rejection.
2. If `request.db_path` doesn't resolve to a valid, existing database file → `OrchestratorError(MISSING_INPUT_FILE)` (FR-008).
3. Build an `EventQueryFilter` (Event Database's own type) from `request`'s primitive `player`/`team`/`event_types`/`min_importance`/`start_over`/`end_over` fields (research.md Decision 8 correction — `GenerateRequest` itself carries only primitives, never a pre-built `EventQueryFilter`, so `cli.py` never needs to import `cvip.db`). Open the Event Database. Call `query_events(filter)`.
4. Build a `ClipGenerationRequest` (Clip Generator's own existing type) directly from the query result (`QueriedEvent` is already structurally compatible, per Event Database's own FR-013) plus `request.include_replays`/`pre_roll_seconds`/`post_roll_seconds`/`merge_gap_seconds`. Run Clip Generator (`generate_clips`).
5. Build a `StitchRequest` from the resulting `ClipPlan` and `request.output_path`. Run Video Stitcher (`stitch_video`). On `VideoStitchingFailureReason.MISSING_FFMPEG` → `OrchestratorError(MISSING_NATIVE_DEPENDENCY)`; any other reason → `OrchestratorError(EXPORT_FAILURE)`.
6. Return a `GenerateResult`.

**Postconditions**:
- Modules 1-7 (Video Loader through Event Detection) are never imported or called anywhere in this function's own call graph (FR-006; constitution Principle III).
- An `EventQueryFilter` matching zero events still produces a valid `GenerateResult` with `clip_count == 0` and `event_count == 0` — Clip Generator's and Video Stitcher's own established "empty is valid" precedents are not overridden here (Edge Cases).

## `inspect_db(db_path: str) -> MatchSummary`

**Input**: an already-resolved database file path (`cli.py`'s own resolution from the `cvip inspect-db <db_path>` positional argument — this command takes a path directly, not a `match_id`, per `specs/cli.md`).

**Sequence** (FR-010): open the Event Database at `db_path`; on `EventDatabaseError` → `OrchestratorError(DATABASE_FAILURE)` (or `MISSING_INPUT_FILE` if the path doesn't exist at all, checked before attempting to open — FR-008). Call `get_match_summary()`. Return it unchanged — `MatchSummary` (Event Database's own type) is already the exact shape `cli.py` needs to print.

Thin by design: this command has no multi-module sequence of its own (it reads one already-persisted view from one module), but still lives in `orchestrator.py` rather than being called directly from `cli.py`, so `cli.py`'s own "only ever imports `cvip.orchestrator`" rule (FR-015) has no exception to it.

## `export_timeline(match_id: str, db_path: str) -> MatchTimelineExport`

**Input**: `match_id` (for the returned `MatchTimelineExport.match_id` field) plus the already-resolved database path (`cli.py`'s own resolution: `data/matches/<match_id>.sqlite`, `specs/cli.md`'s documented convention — the same resolution `generate` uses).

**Sequence** (FR-009): open the Event Database; same error translation as `inspect_db`. Call `get_match_timeline()`. Return it unchanged — `cli.py` handles `--format json`/`--format csv` serialization itself (a presentation concern, not a sequencing one), since `MatchTimelineExport`'s fields are already plain, serialization-ready dicts (Event Database's own data-model.md note).

## `run_doctor_checks() -> Tuple[DependencyCheckResult, ...]`

**Input**: none.

**Sequence** (FR-011): runs every `cvip doctor` check independently, catching each check's own individual failure so one broken check never prevents the others from running: Python version (`sys.version_info` against the platform's documented `3.11+` minimum), FFmpeg availability, Tesseract availability (both via the same `shutil.which()` helper `analyze()`'s own preflight — research.md Decision 6 — reuses), every required Python package importable (`importlib.import_module` over the platform's known dependency list), and `data/`/`output/`/`logs/` directory writability (attempting a real temp-file write-then-delete in each, not just an `os.access()` check, which can be unreliable on Windows). Returns one `DependencyCheckResult` per check, in the order `specs/cli.md`'s example output lists them. Never raises `OrchestratorError` itself — a failing individual check is data in the returned tuple, not a thrown exception (Acceptance Scenario US5-2: every other check still runs and reports).

**Postconditions**: `cli.py` computes the overall `OK`/`FAIL` status by checking whether every `DependencyCheckResult.ok` is `True` — `run_doctor_checks()` itself does not compute or return an aggregate status, keeping "what to check" (this function) and "how to summarize/print it" (`cli.py`) cleanly separated, the same division every other command in this contract already follows.

## Error taxonomy

See [research.md](../research.md) Decision 7 for the full `OrchestratorFailureReason` → exit-code mapping table; [data-model.md](../data-model.md) for the type shape.

## Consumer obligation

`cli.py` MUST call every one of `analyze()`/`generate()`/`inspect_db()`/`export_timeline()` inside a single top-level `try`/`except OrchestratorError` per command, translate `error.exit_code` directly to `sys.exit()`, and MUST NOT itself inspect `error.reason` to make any further sequencing decision (FR-015) — the reason exists for logging/messaging only at that point. `cli.py` MUST NOT import any `cvip.video.*`/`cvip.events.*`/`cvip.clips.*`/`cvip.stitcher.*`/`cvip.db.*` module directly; only `cvip.orchestrator` (FR-015) — including for the two read-only commands above, which are thin pass-throughs but still live behind this same single boundary.
