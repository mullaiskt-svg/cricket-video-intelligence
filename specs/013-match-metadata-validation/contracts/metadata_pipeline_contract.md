# Contract: Metadata Validation Pipeline (`src/cvip/metadata/`)

Six explicit stages (plan.md Summary; spec.md point 2), each independently testable (Constitution Principle V). `orchestrator.validate()` is the only caller — nothing in `src/cvip/metadata/` reads `sys.argv`, a config file path, or opens a database connection itself beyond what's passed in.

```text
Match Metadata
  -> [1] Ground Truth Extraction   (extraction.py)
  -> [2] Timeline Alignment        (alignment.py)
  -> [3] Accuracy Analysis         (validation.py)          -- Story 1, read-only, always runs
  -> [4] Recovery Candidate Generation (recovery.py)         -- only if --recover
  -> [5] Optional Recovery             (recovery.py)         -- only if --recover
  -> [6] Optional Enrichment           (enrichment.py)       -- only if --enrich
```

## Stage 1 — Ground Truth Extraction (`extraction.py`)

**Function**: `extract_ground_truth(metadata_path: str, provider: MetadataProvider = BallByBallJsonProvider()) -> tuple[MetadataEvent, ...]`

**Behavior**: Delegates to `provider.extract(metadata_path)` (research.md Decision 3). Raises `MetadataValidationError(METADATA_FILE_UNREADABLE)` if the file doesn't exist or doesn't parse into the provider's expected shape (FR-009) — never returns a partial list silently.

**Postconditions**: Every returned `MetadataEvent.event_type` is one of `FOUR`/`SIX`/`WICKET` (never `None` or another value) — classification happens here, once, not re-derived downstream.

## Stage 2 — Timeline Alignment (`alignment.py`)

**Function**: `align(ground_truth: tuple[MetadataEvent, ...], scoreboard_readings: tuple[ScoreboardReadingLike, ...], detected_events: tuple[EventLike, ...], ball_radius: int = 8, match_window_seconds: float = 120.0) -> tuple[MatchAlignmentEvidence, ...]`

**Behavior** (research.md Decision 1): for each `MetadataEvent`, search `scoreboard_readings` (filtered to the same `innings`) for a reading at the same `(over_number, ball_in_over)`, preferring a validated reading and widening the ball offset up to `ball_radius`; then attempt to match against `detected_events` of the same type/innings within `match_window_seconds`, greedily, each detected event usable by at most one `MetadataEvent`. Produces exactly one `MatchAlignmentEvidence` per input `MetadataEvent` — never drops one silently, even when both searches fail entirely (`outcome = UNRECOVERABLE_MISS`).

**This is the ONLY function in the subpackage that searches `scoreboard_readings`/`detected_events`** — `validation.py` and `recovery.py` both consume its output exclusively (research.md Decision 1; spec.md point 3).

**Determinism** (FR-018, research.md Decision 7): given identical inputs, `align()`'s return value is byte-for-byte identical across calls — no dependency on dict/set iteration order, wall-clock time, or any other non-deterministic source. Verified by a contract test calling it twice against the same fixture and asserting equality.

**Postconditions**: `len(result) == len(ground_truth)`. Every `MatchAlignmentEvidence.recovery_eligible` is `True` if and only if `matched_scoreboard_reading is not None and matched_detected_event is None`.

## Stage 3 — Accuracy Analysis (`validation.py`)

**Function**: `analyze_accuracy(alignment: tuple[MatchAlignmentEvidence, ...], detected_events: tuple[dict, ...]) -> AccuracyReport`

**Behavior**: Pure aggregation over `alignment` — counts by `AlignmentOutcome`, per-type recall, precision (FR-006). Performs no database write of any kind (FR-005's "pure read-side" requirement is structural here: this function doesn't even receive a database handle, only the already-computed `alignment` tuple plus the same `detected_events` sequence `align()` was given).

**Self-caught correction (implementation)**: an earlier draft of this contract took only `alignment`. `false_positives` (a detected scoring event with no corresponding ground-truth entry) cannot be computed from `alignment` alone — `MatchAlignmentEvidence` has exactly one entry per *ground-truth* event, so an unmatched *detected* event has no representation in it at all. `detected_events` is required for this reason.

**Postconditions**: `report.true_positives + report.false_negatives_no_signal + report.false_negatives_with_signal == len(alignment)`.

## Stage 4 — Recovery Candidate Generation (`recovery.py`)

**Function**: `find_recovery_candidates(alignment: tuple[MatchAlignmentEvidence, ...]) -> tuple[MatchAlignmentEvidence, ...]`

**Behavior**: Filters `alignment` to entries where `recovery_eligible` is `True`. Pure filter — no write.

## Stage 5 — Optional Recovery (`recovery.py`)

**Function**: `recover_events(candidates: tuple[MatchAlignmentEvidence, ...], db: EventDatabase, metadata_file_path: str, metadata_file_hash: str) -> tuple[RecoveredEvent, ...]`

**Behavior** (FR-010 through FR-013, FR-017):
1. Refuse (`MetadataValidationError(MATCH_NOT_COMPLETE)`) if the open database's match status is not `COMPLETE` (FR-008).
2. For each candidate, compute a stable `metadata_event_identifier` (e.g. `f"innings={innings} over_ball={over_number}.{ball_in_over} type={event_type}"`) and query `metadata_operations` for an existing `RECOVERY` row with the same `(metadata_file_hash, metadata_event_identifier)`. If found, skip (FR-012) — logged, not silent.
3. Otherwise, insert a new `events` row (`source='METADATA'`) and a corresponding `metadata_operations` row (`operation_type='RECOVERY'`) in the same transaction — both succeed or both roll back together, matching Event Database's own established `_run_operation` all-or-nothing pattern (`specs/010-event-database/research.md` Decision 5).
4. Never touches an existing `events` row, never changes the match's `status` (FR-013).

**Postconditions**: Calling this function twice with the same `candidates`/`metadata_file_hash` produces the same final `events`/`metadata_operations` state after the second call as after the first (FR-012, idempotent).

## Stage 6 — Optional Enrichment (`enrichment.py`)

**Function**: `enrich_wickets(alignment: tuple[MatchAlignmentEvidence, ...], db: EventDatabase, metadata_file_path: str, metadata_file_hash: str) -> tuple[DismissalDetail, ...]`

**Behavior** (FR-014, FR-017): for each `MatchAlignmentEvidence` whose `metadata_event.event_type == "WICKET"` and `outcome == TRUE_POSITIVE` (only enriches an event that's already confirmed to exist — recovered events are enriched in the same pass that recovers them, not a separate lookup), attempt phrase extraction (research.md Decision 9) against `metadata_event.description`. On a confident match, `UPDATE events SET dismissal_type = ?, fielder = ? WHERE event_id = ?` for the matched event, plus an `ENRICHMENT` row in `metadata_operations`. On no confident match, does nothing for that event (FR-014's "leaving it unset... rather than guessing") — not even an audit row, since nothing was actually changed.

**Postconditions**: Never modifies `timestamp_seconds`, `confidence`, `event_type`, or any other pre-existing `events` column — only ever writes `dismissal_type`/`fielder` on a row that already exists.

## Shared error taxonomy (`errors.py`)

| `MetadataValidationFailureReason` | Meaning |
|---|---|
| `METADATA_FILE_UNREADABLE` | The `--metadata` file doesn't exist or doesn't parse into the expected shape (FR-009). |
| `MATCH_NOT_COMPLETE` | The target match's analysis status isn't `COMPLETE` (FR-008). |
| `POSITION_OUT_OF_RANGE` | A `MetadataEvent` references an over/ball outside the analyzed match's own known range (FR-015). |

`MetadataValidationError(reason, detail)` — same shape as every prior module's own typed error (`EventDatabaseError`, `OrchestratorError`, etc.), translated to an `OrchestratorFailureReason`/exit code at the `orchestrator.py` boundary (see `orchestrator_validate_contract.md`), never leaking a raw exception past it.
