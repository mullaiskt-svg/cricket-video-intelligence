# Data Model: Structured Match Metadata Validation Layer

Derived from spec.md's Key Entities plus research.md's architectural decisions. Two kinds of data here: **in-memory value objects** (built and consumed within one `cvip validate` run, `src/cvip/metadata/`) and **persistent Event Database additions** (schema version 1 → 2, `src/cvip/db/schema.py`).

## In-Memory Value Objects

### MetadataEvent

Stage 1 (Ground Truth Extraction) output — one per delivery a `MetadataProvider` classifies as FOUR/SIX/WICKET (research.md Decision 3).

| Field | Type | Notes |
|---|---|---|
| `innings` | int | `1` or `2`, matching the Event Database's own `innings` column convention exactly (not a string label). |
| `over_number` | int | Position in the match. |
| `ball_in_over` | int | Position in the match. |
| `event_type` | str | One of `FOUR`/`SIX`/`WICKET`. |
| `description` | str | The metadata source's own free-text description — retained verbatim for Enrichment (Stage 6) to read dismissal/fielder detail from. |

### GroundTruthEvent

A `MetadataEvent` with alignment already attempted (Stage 2 output feeding Stage 3+). Effectively `MetadataEvent` plus:

| Field | Type | Notes |
|---|---|---|
| `metadata_event` | MetadataEvent | The source event. |
| `alignment` | MatchAlignmentEvidence | See below. Every `GroundTruthEvent` has exactly one, even when alignment failed entirely (`AlignmentOutcome.NO_READING_FOUND`). |

### MetadataProvider (Protocol)

The Ground Truth Extraction extension point (research.md Decision 3).

| Member | Signature | Notes |
|---|---|---|
| `extract` | `(path: str) -> tuple[MetadataEvent, ...]` | Reads a metadata file and returns its FOUR/SIX/WICKET events. Raises `MetadataValidationError(reason=METADATA_FILE_UNREADABLE, ...)` on a malformed/unreadable file (FR-009) — never returns a partial result silently. |

V1 ships exactly one implementation, `providers/ball_by_ball_json.py`, for the shape already proven in `ground_truth_v2/build_ground_truth.py`.

### MatchAlignmentEvidence (internal only — research.md Decision 2)

The shared substrate Accuracy Analysis and Recovery both consume (spec.md point 1).

| Field | Type | Notes |
|---|---|---|
| `metadata_event` | MetadataEvent | The event being aligned. |
| `matched_scoreboard_reading` | Optional[ScoreboardReadingLike] | The nearest usable reading found for this event's `(innings, over_number, ball_in_over)`, if any (research.md Decision 1's search). |
| `matched_detected_event` | Optional[EventLike] | An already-detected (OCR-sourced) event this ground-truth event corresponds to, if the search found one within the match window — this is what makes it a true positive for Accuracy Analysis. |
| `alignment_confidence` | AlignmentConfidenceTier | One of the fixed tiers (research.md Decision 10). |
| `outcome` | AlignmentOutcome | See below. |
| `recovery_eligible` | bool | `True` only when `matched_scoreboard_reading is not None and matched_detected_event is None` — a real position in the video was found, but no event already exists there (Recovery's own precondition, FR-010). |
| `reason` | str | A short, human-readable explanation (e.g. `"matched validated reading at exact over.ball"`, `"no reading within radius 8"`) — surfaced in diagnostics (research.md point 6) and CLI output, never silently dropped. |

### AlignmentConfidenceTier (enum)

`EXACT_BALL_VALIDATED_READING` / `EXACT_BALL_ANY_READING` / `NEARBY_BALL_RADIUS_N` / `NO_READING_FOUND` (research.md Decision 10).

### AlignmentOutcome (enum)

| Value | Meaning |
|---|---|
| `TRUE_POSITIVE` | A matching detected event was found — this ground-truth event was already correctly detected. |
| `RECOVERABLE_MISS` | No matching detected event, but a scoreboard reading exists nearby — `recovery_eligible = True`. |
| `UNRECOVERABLE_MISS` | No matching detected event, and no scoreboard reading exists anywhere nearby — this is spec.md's "no signal at all" case (FR-007), never recoverable regardless of `--recover`. |

## AccuracyReport (public — Story 1)

Built from a list of `MatchAlignmentEvidence`; the object `cvip validate` prints/writes without `--recover`/`--enrich`.

| Field | Type | Notes |
|---|---|---|
| `ground_truth_total` | int | Total `MetadataEvent`s extracted. |
| `true_positives` | int | Count of `AlignmentOutcome.TRUE_POSITIVE`. |
| `false_negatives_no_signal` | int | Count of `AlignmentOutcome.UNRECOVERABLE_MISS` (FR-007's required split). |
| `false_negatives_with_signal` | int | Count of `AlignmentOutcome.RECOVERABLE_MISS` (FR-007's required split). |
| `false_positives` | int | Detected scoring events with no corresponding ground-truth entry. |
| `recall_by_event_type` | dict[str, float] | Per FOUR/SIX/WICKET. |
| `precision` | float | Overall. |
| `missed_events` | tuple[MetadataEvent, ...] | Both `RECOVERABLE_MISS` and `UNRECOVERABLE_MISS`, each tagged with its outcome — for a human to read, not just a count. |

## RecoveredEvent (public — Story 2)

The shape `recovery.py` inserts into `events` and reports back to the caller.

| Field | Type | Notes |
|---|---|---|
| `event_type` | str | From the source `MetadataEvent`. |
| `timestamp_seconds` | float | From `matched_scoreboard_reading.timestamp_seconds` — the estimated position in the video (FR-010 requires this to have succeeded before recovery runs at all). |
| `innings`, `over_number`, `ball_in_over` | int | From the source `MetadataEvent`. |
| `source` | str | Always `"METADATA"` (FR-011; `events.source` column, Decision below). |
| `confidence` | float | A fixed, conservative value distinct from OCR-derived confidence scoring (Module 5) — this event's certainty comes from independently-sourced metadata, not a video-derived signal, so it is not computed the same way. |

## DismissalDetail (Story 3)

Enrichment's output for one wicket event.

| Field | Type | Notes |
|---|---|---|
| `dismissal_type` | Optional[str] | One of `BOWLED`/`CAUGHT`/`LBW`/`RUN_OUT`/`STUMPED`/`HIT_WICKET`, or `None` if the description wasn't confidently readable (FR-014). |
| `fielder` | Optional[str] | Present only for `CAUGHT`/`RUN_OUT`/`STUMPED` when the description named one. |

## ValidateRequest / ValidateResult (Orchestrator level)

Mirrors `AnalyzeRequest`/`AnalysisRun`'s existing pattern (`specs/012-pipeline-orchestrator-cli/data-model.md`) — built by `cli.py`, consumed by `orchestrator.validate()`.

| Field | Type | Notes |
|---|---|---|
| `match_id_or_db_path` | str | The positional `cvip validate` argument — resolved to a `db_path` the same way `generate`/`export-timeline` already do (`cli.py`'s existing `_resolve_match_id_and_db_path`, reused as-is). |
| `metadata_path` | str | `--metadata`. Required. |
| `recover` | bool | `--recover`. Default `False`. |
| `enrich` | bool | `--enrich`. Default `False`. |
| `output_path` | Optional[str] | `--output`. Where to write the `AccuracyReport`; stdout if omitted. |

`ValidateResult` carries the `AccuracyReport` plus, only when requested, the count of events recovered/enriched.

## Persistent Schema Additions (Event Database, schema version 1 → 2)

Per research.md Decisions 4-5 — additive only, no existing column redefined.

### `events` (existing table, three new nullable/defaulted columns)

| New Column | Type | Notes |
|---|---|---|
| `source` | TEXT, `CHECK (source IN ('OCR','METADATA'))`, `NOT NULL DEFAULT 'OCR'` | Every pre-existing row implicitly becomes `'OCR'` on re-analysis (there is no in-place migration of old rows — a v1 database is simply unreadable by v2 code, per Module 10's existing `SCHEMA_VERSION_MISMATCH` behavior, until re-analyzed fresh). |
| `dismissal_type` | TEXT, `CHECK (... OR dismissal_type IS NULL)`, nullable | Set only by Enrichment, only on `WICKET` rows. |
| `fielder` | TEXT, nullable | Set only by Enrichment, alongside `dismissal_type` when applicable. |

### `metadata_operations` (new table)

```sql
CREATE TABLE metadata_operations (
  operation_id INTEGER PRIMARY KEY,
  operation_type TEXT CHECK (operation_type IN ('RECOVERY', 'ENRICHMENT')),
  metadata_file_path TEXT NOT NULL,
  metadata_file_hash TEXT NOT NULL,
  metadata_event_identifier TEXT NOT NULL,
  affected_event_id INTEGER,
  recovery_version TEXT NOT NULL,
  performed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  detail TEXT
);

CREATE UNIQUE INDEX idx_metadata_operations_dedup
  ON metadata_operations (metadata_file_hash, metadata_event_identifier, operation_type);

CREATE INDEX idx_metadata_operations_event ON metadata_operations (affected_event_id);
```

The unique index is defense-in-depth (research.md Decision 6) — the real idempotency check is an explicit pre-write query, not reliance on a constraint-violation catch.

## Relationships

```text
MetadataProvider.extract() -> MetadataEvent (many)
MetadataEvent --[Timeline Alignment]--> MatchAlignmentEvidence (one each)
MatchAlignmentEvidence (all) --[Accuracy Analysis]--> AccuracyReport (one)
MatchAlignmentEvidence (recovery_eligible=True) --[Recovery]--> RecoveredEvent (many) --> events row (source='METADATA') + metadata_operations row (operation_type='RECOVERY')
GroundTruthEvent.description --[Enrichment]--> DismissalDetail (optional, per WICKET) --> events.dismissal_type/fielder + metadata_operations row (operation_type='ENRICHMENT')
```
