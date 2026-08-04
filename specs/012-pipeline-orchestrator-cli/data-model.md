# Data Model: Pipeline Orchestrator and CLI

Derived from the Key Entities section of [spec.md](./spec.md). This feature has no persistent storage of its own (Event Database, Module 10, owns all of it) — these are in-memory request/result value objects, built by `cli.py` and consumed by `orchestrator.py`.

## AnalyzeRequest

Built by `cli.py` from parsed `argparse` output plus `config/default.yaml`; passed to `orchestrator.analyze()`.

| Field | Type | Notes |
|---|---|---|
| `video_path` | str | Required. The positional `cvip analyze <video_path>` argument. |
| `config` | dict | The fully-parsed `config/default.yaml` (or `--config`-supplied path), validated shape per `config/default.yaml`'s own documented schema — `orchestrator.py` reads specific keys from it per stage (research.md Decision 4), never the whole file blindly. |
| `output_db_path` | Optional[str] | `--output-db`. `None` means "use the `file_hash[:12]`-derived default" (`specs/cli.md`'s documented behavior, Assumptions). |
| `timeline_path` | Optional[str] | `--timeline`. Where to additionally write a timeline JSON after analysis, if supplied. |
| `force` | bool | `--force`. Default `False`. |

## AnalysisRun

The result `orchestrator.analyze()` returns on success (spec.md Key Entities "Analysis Run").

| Field | Type | Notes |
|---|---|---|
| `match_id` | str | The Event Database's own match identifier (`file_hash[:12]` by default). |
| `db_path` | str | The resolved database file path actually used. |
| `file_hash` | str | Video Loader's own sampled digest for this video. |
| `status` | str | Always `"COMPLETE"` for a returned `AnalysisRun` — a failed run raises `OrchestratorError` instead of returning a `FAILED`-status result (constitution Principle VI: fail loudly, not via a status field a caller might not check). |
| `stages_completed` | Tuple[str, ...] | The ordered list of stage names that ran (`"video_loader"`, `"scene_detection"`, `"replay_detection"`, `"scoreboard_ocr"`, `"ocr_timeline_smoother"`, `"event_detection"`) — always all six on a successful return. |
| `event_count` | int | Convenience summary — the number of events Event Detection produced and Event Database persisted this run. |

## GenerateRequest

Built by `cli.py` from parsed `argparse` output; passed to `orchestrator.generate()`.

| Field | Type | Notes |
|---|---|---|
| `match_id` | str | Required. The positional `cvip generate <match_id>` argument. |
| `db_path` | str | Resolved from `match_id` (`data/matches/<match_id>.sqlite`, `specs/cli.md`'s documented convention — `cli.py`'s own resolution, not `orchestrator.py`'s). |
| `template` | str | `--template`. One of `match`/`player`/`team`/`custom` — only `match` actually runs (FR-007); the other three are accepted here and rejected inside `orchestrator.generate()` with a specific `OrchestratorFailureReason`. |
| `output_path` | str | Required. `--output`. |
| `player`, `team`, `event_types`, `min_importance`, `start_over`, `end_over` | primitive (str/Tuple[str,...]/int, all optional) | Taken directly from `--player`/`--team`/`--event-type`/`--min-importance`/`--start-over`/`--end-over`, plain fields rather than a pre-built `cvip.db.models.EventQueryFilter` (research.md Decision 8 correction) — `orchestrator.generate()` builds the real `EventQueryFilter` internally, since `cli.py` must never import `cvip.db` itself (FR-015). |
| `include_replays` | bool | `--include-replays`. Default `False`. |
| `pre_roll_seconds`, `post_roll_seconds`, `merge_gap_seconds` | float | From `config/default.yaml`'s `events.*` keys (the same values `analyze` itself would have used) — `generate` reuses them for consistent clip windowing, not a separate `generate`-only config surface. |

## GenerateResult

The result `orchestrator.generate()` returns on success (spec.md Key Entities "Generate Request" — the read-side counterpart).

| Field | Type | Notes |
|---|---|---|
| `output_path` | str | Where the final stitched video was written (Video Stitcher's own `StitchResult.output_path`, passed through). |
| `clip_count` | int | `ClipPlan.total_clips`, passed through. |
| `event_count` | int | How many events `query_events()` returned before clip generation — `0` is valid (Edge Cases: empty filter results). |

## OrchestratorFailureReason

The exit-code-oriented failure taxonomy for this feature (spec.md Key Entities "Exit Code Mapping"; research.md Decision 7's full mapping table).

| Value | Exit code | Meaning |
|---|---|---|
| `GENERAL_FAILURE` | 1 | Catch-all for a genuine, unanticipated failure not otherwise categorized |
| `INVALID_ARGUMENTS` | 2 | A CLI argument or config value was invalid/malformed |
| `MISSING_INPUT_FILE` | 3 | The source video, or a `generate`/`inspect-db`/`export-timeline` target database, doesn't exist |
| `UNSUPPORTED_VIDEO_FORMAT` | 4 | Video Loader rejected the file's format |
| `MISSING_NATIVE_DEPENDENCY` | 5 | FFmpeg or Tesseract not found on `PATH` |
| `OCR_FAILURE` | 6 | Scoreboard OCR failed for a reason other than a missing dependency |
| `DATABASE_FAILURE` | 7 | An Event Database operation failed |
| `EXPORT_FAILURE` | 8 | Video Stitcher failed for a reason other than a missing dependency |
| `ALREADY_ANALYZED` | 9 | The single-pass gate found an existing `COMPLETE`/`IN_PROGRESS` match without `--force` |

## OrchestratorError

Raised by `orchestrator.py`, caught only at `cli.py`'s top level (research.md Decision 7).

| Field | Type | Notes |
|---|---|---|
| `reason` | `OrchestratorFailureReason` | |
| `exit_code` | int | Redundant with `reason` (each reason has exactly one exit code) but carried directly for `cli.py`'s own convenience — `sys.exit(error.exit_code)` needs no lookup. |
| `detail` | str | Human-readable — usually wraps the original module-level exception's own `detail`. |

## DependencyCheckResult

One row of `cvip doctor`'s output, and the shape `_check_native_dependencies()` (research.md Decision 6) returns (spec.md Key Entities — implicit in User Story 5, not separately named there).

| Field | Type | Notes |
|---|---|---|
| `name` | str | e.g. `"FFmpeg"`, `"Tesseract"`, `"Python"`, `"SQLite"`, `"Data directory"`. |
| `ok` | bool | |
| `detail` | Optional[str] | Populated only when `ok=False` — what's missing/wrong and, where practical, how to fix it. |

## Config Keys Consumed (no new type — `AnalyzeRequest.config`'s own already-existing shape)

Not a new entity — documents which of `config/default.yaml`'s existing keys `orchestrator.py` reads, per stage, confirming no new config surface is introduced by this feature:

| Stage | Keys read |
|---|---|
| Scene Detection | `video.scene_threshold` |
| Replay Detection | `replay.confidence_threshold`, `replay.min_segment_seconds`, `replay.logo_template_path`, `replay.signals.*` |
| Scoreboard OCR | `ocr.scoreboard_region`, `ocr.preprocess.*`, `ocr.min_confidence` |
| Event Detection | `events.team_milestone_interval`, `events.ranking` |
| Clip Generator (`generate` only) | `events.pre_roll_seconds`, `events.post_roll_seconds`, `events.merge_gap_seconds` |
| Video Stitcher (`generate` only) | `output.container`, `output.avoid_reencode` |
