# Contract: `cvip validate` (Orchestrator + CLI extension)

Extends `src/cvip/orchestrator.py`/`src/cvip/orchestrator_errors.py`/`src/cvip/cli.py` (`specs/012-pipeline-orchestrator-cli/contracts/`) — this feature adds one function and one subcommand to each, changing nothing about `analyze()`/`generate()`/`export_timeline()`/`inspect_db()`/`run_doctor_checks()` or their own existing tests.

## `orchestrator.validate(request: ValidateRequest) -> ValidateResult`

**Sequence** (research.md Decision 8):

1. Resolve `request.match_id_or_db_path` to a `db_path` — reuses `cli.py`'s existing `_resolve_match_id_and_db_path` logic (already handles both a bare match_id and a direct path, per the fix already shipped for `generate`/`export-timeline`), not a new resolution mechanism.
2. Open the Event Database. If its match status is not `COMPLETE` → `OrchestratorError(INVALID_ARGUMENTS, detail="match is not COMPLETE; validate requires a fully-analyzed match")` (FR-008; `metadata_pipeline_contract.md`'s `MATCH_NOT_COMPLETE`, mapped onto the existing exit code 2 rather than a new code — see "Exit code mapping" below).
3. Run Stage 1 (`extract_ground_truth`). A `MetadataValidationError(METADATA_FILE_UNREADABLE)` → `OrchestratorError(MISSING_INPUT_FILE)` if the file doesn't exist, `OrchestratorError(INVALID_ARGUMENTS)` if it exists but doesn't parse (FR-009).
4. Run Stage 2 (`align`) against the database's own `scoreboard_readings`/`events`. A `MetadataValidationError(POSITION_OUT_OF_RANGE)` → `OrchestratorError(INVALID_ARGUMENTS)` (FR-015).
5. Run Stage 3 (`analyze_accuracy`) — always, regardless of flags (FR-006). This is `ValidateResult.report`.
6. If `request.recover`: run Stages 4-5 (`find_recovery_candidates`, `recover_events`). Any `MetadataValidationError` here → `OrchestratorError(DATABASE_FAILURE)` (a write-path failure, matching `analyze()`'s own precedent for translating Event Database errors).
7. If `request.enrich`: run Stage 6 (`enrich_wickets`). Same error translation as step 6.
8. Return a `ValidateResult`.

**Postconditions**:
- With neither `request.recover` nor `request.enrich`, no write of any kind reaches the database — testable directly by mocking `EventDatabase` and asserting no method beyond read-only calls (`check_analysis_status`, `get_match_summary`, reading `scoreboard_readings`/`events`) is ever invoked (FR-003's structural enforcement, research.md Decision 8).
- `analyze()`/`generate()`/`export_timeline()`/`inspect_db()`/`run_doctor_checks()` are byte-for-byte unchanged by this feature's addition — verified by their own existing test suites continuing to pass unmodified.

## `cvip validate` (CLI)

```text
cvip validate <match_id_or_db_path> --metadata PATH [--recover] [--enrich] [--output PATH]
```

| Argument | Required | Notes |
|---|---|---|
| `match_id_or_db_path` | Yes (positional) | Same dual form `generate`/`export-timeline` already accept. |
| `--metadata` | Yes | Path to the ball-by-ball metadata file. |
| `--recover` | No | Default off. Enables Stages 4-5. |
| `--enrich` | No | Default off. Enables Stage 6. |
| `--output` | No | Where to write the accuracy report (JSON); stdout if omitted. |

`cli.py`'s handler builds a `ValidateRequest` and delegates to `orchestrator.validate()` exactly like every other subcommand's handler — no sequencing logic of its own (the same static-import contract test already covering `cli.py`'s independence, `tests/contract/test_cli_contract.py`, extends to confirm it still never imports `cvip.metadata` directly either, only `cvip.orchestrator`).

**Output**: prints/writes the `AccuracyReport` (recall/precision by type, missed-event list with each one's outcome). When `--recover`/`--enrich` ran, additionally prints how many events were recovered/enriched and how many were skipped as already-done (FR-012).

## Exit code mapping (extends `specs/cli.md`'s existing 9-value table, no new codes added)

| `MetadataValidationFailureReason` | `OrchestratorFailureReason` | Exit code | Rationale |
|---|---|---|---|
| `METADATA_FILE_UNREADABLE` (file missing) | `MISSING_INPUT_FILE` | 3 | Same bucket `analyze()` already uses for a missing video file. |
| `METADATA_FILE_UNREADABLE` (unparseable) | `INVALID_ARGUMENTS` | 2 | The file exists but what was supplied can't be used — a caller-input problem, same bucket `analyze()` already uses for a malformed config file. |
| `MATCH_NOT_COMPLETE` | `INVALID_ARGUMENTS` | 2 | The command was invoked against a match that isn't in a state it can run against — a precondition-on-input problem, not a new failure class distinct enough to warrant its own code. |
| `POSITION_OUT_OF_RANGE` | `INVALID_ARGUMENTS` | 2 | The supplied metadata's own content is invalid for this match — same reasoning as the unparseable-file case above. |
| Any `EventDatabaseError` during Stage 5/6 writes | `DATABASE_FAILURE` | 7 | Matches `analyze()`'s own existing translation for a write-path failure. |

Reusing existing codes (rather than proposing new ones, e.g. a 10th code) was a deliberate choice: `specs/cli.md`'s exit-code table is a small, already-stable, cross-cutting contract every prior feature commits to, and none of this feature's three new failure reasons represent a genuinely new *category* of failure the existing nine don't already cover in spirit — they're all either "bad/missing input" or "database write failed," both already-represented buckets.
