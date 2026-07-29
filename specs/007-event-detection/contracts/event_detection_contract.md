# Contract: Event Detection

This module exposes one entry point to the rest of the CVIP pipeline. It is an internal Python library contract (no network/CLI surface), consistent with constitution Principle V (clear input/output contract, independently testable).

## `detect_events(request: EventDetectionRequest) -> EventDetectionRunner`

**Input**: an `EventDetectionRequest` (see [data-model.md](../data-model.md)), wrapping the cleaned scoreboard timeline (`OCRTimelineSmootherResult`, from the OCR Timeline Smoother, `specs/006-ocr-timeline-smoother/`), the raw Scoreboard OCR result (`ScoreboardOcrResult`, from `specs/005-scoreboard-ocr/`), the replay timeline (`ReplayDetectionResult`, from `specs/004-replay-detection/`), a configured `team_milestone_interval`, and a caller-supplied `ranking` mapping (Module 7's per-`event_type` importance scores). Like the OCR Timeline Smoother, this call never touches a `LoadResult`, the Frame Extraction Service, or a video file of any kind (FR-017) — all three upstream inputs are already-structured results from prior modules, and `ranking`/`team_milestone_interval` are plain caller-supplied values, not read from `config/default.yaml` by this module itself.

**Output**: an `EventDetectionRunner` — a context-manager object exposing `.run() -> EventDetectionResult` (which performs the full detection pass, research.md Decision 1, and returns the result) and `.cancel()` (for cooperative cancellation, FR-018).

**Preconditions**: All validated lazily inside `.run()`, in this order — `request.cleaned_timeline`, `request.raw_ocr_result`, and `request.replay_result` are each present and structurally well-formed (FR-020); `request.team_milestone_interval` is a positive integer (FR-029). On the first violation encountered, `.run()` immediately raises `EventDetectionError` with the matching reason (see Error taxonomy) and still emits exactly one diagnostics record — no comparison is processed for any of these rejection cases.

**Usage**:
```
with detect_events(request) as runner:
    result = runner.run()
    # or: runner.cancel() from another point in the Orchestrator's control flow
    # while .run() is in progress on another logical thread of control
# on exit (normal, cancelled, or exception): exactly one
# EventDetectionDiagnostics record emitted
```

**Postconditions**:
- Every `DetectedEvent` in `result.events` is derived purely from diffing consecutive entries of `request.cleaned_timeline.samples` — this module never diffs `request.raw_ocr_result` directly, and never implements its own gap-filling or outlier-detection logic (FR-001; that responsibility belongs entirely to the OCR Timeline Smoother, per its own contract).
- `request.raw_ocr_result` is consulted only for `ocr_confidence`/`parse_confidence` lookup by timestamp (FR-002, FR-014) — never for its values.
- `request.replay_result` is consulted only to set `is_replay` (FR-003, FR-016) — this module never re-derives or second-guesses a replay classification.
- A comparison where either bracketing cleaned reading has a `null` core scoring field yields no `DetectedEvent` (FR-009).
- A comparison matching the innings-transition heuristic (both `runs` and `wickets` dropping) yields no `DetectedEvent` — only an internal counter reset (FR-010).
- At most one of `WICKET`/`FOUR`/`SIX` is derived per comparison; `TEAM_MILESTONE` is independent and may co-occur with any of them or stand alone (FR-023).
- Every `DetectedEvent.confidence` is the minimum of `ocr_confidence`/`parse_confidence` across the two raw readings bracketing the delta (FR-014) — never fabricated, never averaged.
- Every `DetectedEvent.importance` comes from `request.ranking` (the caller-supplied mapping, ultimately sourced from `config/default.yaml`'s `events.ranking`) and never influences whether an event was detected in the first place (FR-015, FR-027).
- Every `DetectedEvent.event_key` is unique within `result.events` and identical across repeated runs against the same input and configuration (FR-025, SC-007).
- `TEAM_MILESTONE` events carry the specific `milestone_value` crossed (FR-026); all other event types leave it `null`.
- `result.events` and `result.total_events` are self-contained, plain values with no reference to any run-internal state (matching Module 4a's own `OCRTimelineSmootherResult` precedent); `result.source_video_id` is carried through from the input.
- The full `result.events` sequence is identical across repeated runs against the same input and configuration (FR-021, SC-005).
- Regardless of how the run ends (completed normally, cancelled, or failed), exactly one `EventDetectionDiagnostics` record is emitted (FR-019). A successful run that detects zero events still emits a valid diagnostics record with `average_confidence = 0.0` (FR-028) — never a division-by-zero failure.
- No network calls are made under any circumstance, no GPU is required or used, and no video frame or OpenCV/decode facility is ever accessed (FR-017).
- This feature never accesses or is aware of the DB `events` table — it produces an in-memory `EventDetectionResult` only; persistence remains the Pipeline Orchestrator's responsibility, matching every prior module's own precedent.

## Error taxonomy (`EventDetectionFailureReason` values)

| Value | Meaning | Example trigger |
|---|---|---|
| `INVALID_INPUT` (FR-020) | One of `cleaned_timeline`, `raw_ocr_result`, or `replay_result` is missing, or not a well-formed instance of its expected result type | Caller passes `None` for any of the three, or a malformed result object |
| `INVALID_DETECTION_CONFIGURATION` (FR-029) | The configured `team_milestone_interval` is not a positive integer | `team_milestone_interval` set to `0` or `-1` |

`EventEvidence` (see [data-model.md](../data-model.md)) is a separate, internal per-event record — it never causes a run to fail; it only explains how each `DetectedEvent` was derived.

## Consumer obligation

The Pipeline Orchestrator MUST obtain the detected event list via `detect_events()` and MUST persist each `DetectedEvent` into the `events` table (`specs/technical_plan.md` Database Schema) without recomputing or second-guessing `confidence`, `importance`, `is_replay`, or `event_key` — this module has already resolved them. A consumer MAY treat `EventEvidence` as an internal record with no stable public contract — no consumer contract depends on it being exposed. A consumer MUST NOT persist events out of order relative to `result.events`, since ties at the same `timestamp_seconds` are already resolved into a stable order by this module (data-model.md `EventDetectionResult.events`).
