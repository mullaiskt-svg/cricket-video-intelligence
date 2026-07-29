# Contract: Clip Generator

This module exposes one entry point to the rest of the CVIP pipeline. It is an internal Python library contract (no network/CLI surface), consistent with constitution Principle V (clear input/output contract, independently testable).

## `generate_clips(request: ClipGenerationRequest) -> ClipGeneratorRunner`

**Input**: a `ClipGenerationRequest` (see [data-model.md](../data-model.md)), wrapping an already-filtered sequence of `DetectedEvent`-shaped events (structurally: `event_key`/`timestamp_seconds`/`is_replay` — research.md Decision 7), the source video path, the source video's total duration, clip settings (`pre_roll_seconds`/`post_roll_seconds`/`merge_gap_seconds`), and a replay-inclusion flag. This call never queries the Event Database, applies `--player`/`--team`/`--event-type`/`--min-importance` filtering, touches a video file, or performs OCR/replay/scene detection of any kind (FR-001, FR-013) — all filtering has already happened by the time this module receives its input, and `pre_roll_seconds`/`post_roll_seconds`/`merge_gap_seconds`/`include_replays` are plain caller-supplied values, not read from `config/default.yaml` by this module itself.

**Output**: a `ClipGeneratorRunner` — a context-manager object exposing `.run() -> ClipPlan` (which performs the full six-stage Processing Model pass, spec.md, and returns the result).

**Preconditions**: All validated lazily inside `.run()`, in this order — `request.events` is present and, if non-empty, every element is structurally well-formed (FR-015); `request.source_video_path` is present and non-empty (FR-015); `request.video_duration_seconds`, `request.pre_roll_seconds`, `request.post_roll_seconds`, `request.merge_gap_seconds` are each finite and `>= 0` (FR-015). On the first violation encountered, `.run()` immediately raises `ClipGenerationError` with the matching reason (see Error taxonomy) and still emits exactly one diagnostics record — no event is processed for any of these rejection cases.

**Usage**:
```
with generate_clips(request) as runner:
    plan = runner.run()
# on exit (normal or exception): exactly one
# ClipGenerationDiagnostics record emitted
```

**Postconditions**:
- Every `PlannedClip` in `plan.clips` is derived purely from `request.events`, `request.video_duration_seconds`, and the clip settings — this module never re-derives event data, never queries the Event Database, and never opens the source video file (FR-001, FR-013).
- Clip Window Generation and Boundary Clamping (Processing Model Stages 2-3) run for **every** input event, unconditionally, before Replay Filtering (Stage 4) evaluates any event (FR-002, FR-003, FR-018) — this ordering is what lets `ClipEvidence` record a replay-excluded event's would-have-been window.
- Every output `clip_start_seconds` is `>= 0.0` and every `clip_end_seconds` is `<= request.video_duration_seconds` (FR-003).
- When `request.include_replays=False` (default), no `PlannedClip` in `plan.clips` traces back to a replay-flagged event; when `True`, replay-flagged events are windowed and merged exactly like any other event (FR-004, FR-005).
- No two `PlannedClip`s in `plan.clips` overlap or sit within `merge_gap_seconds` of each other (FR-006, FR-007, FR-008) — every merge join is tagged internally with a `MergeReason` (`OVERLAP`, `GAP_THRESHOLD`, or `CHAIN_MERGE`, FR-006, FR-007).
- `plan.clips` is ordered by ascending `clip_start_seconds`, with the FR-009 tie-break rule applied wherever clamped windows share an identical start prior to merging.
- Every `PlannedClip.clip_id` is deterministic (derived from its sorted `source_event_ids`, FR-010) and unique within `plan.clips`.
- Every `PlannedClip` carries `source_event_ids`, `event_count`, `merged`, and `contains_replay` (FR-011) in addition to its timing fields.
- An empty `request.events`, or an `events` sequence where every element is replay-excluded, yields a valid `plan` with `plan.clips == ()` and `plan.total_clips == 0` — never an error (FR-012).
- The full `plan.clips` sequence — including every `clip_id`, `source_event_ids` order, and internal `MergeReason` assignment — is identical across repeated runs against the same input and configuration (FR-014).
- Regardless of how the run ends (completed normally or failed), exactly one `ClipGenerationDiagnostics` record is emitted (FR-017). A successful run that produces zero clips still emits a valid diagnostics record with `average_clip_duration = 0.0` (research.md Decision 6) — never a division-by-zero failure.
- No network calls are made under any circumstance, no GPU is required or used, and no video frame, OpenCV, or FFmpeg facility is ever accessed (FR-013).
- This feature never accesses or is aware of the DB `events` table — it produces an in-memory `ClipPlan` only; persisting `clip_start_seconds`/`clip_end_seconds` back onto `events` rows (if desired) remains the Pipeline Orchestrator's responsibility, matching every prior module's own precedent (FR-019).

## Error taxonomy (`ClipGenerationFailureReason` values)

| Value | Meaning | Example trigger |
|---|---|---|
| `INVALID_INPUT` (FR-015) | `events`, `source_video_path`, or an individual event element is missing or not structurally well-formed | Caller passes `None` for `events`/`source_video_path`, or an event element missing `event_key`/`timestamp_seconds`/`is_replay` |
| `INVALID_CLIP_CONFIGURATION` (FR-015) | `video_duration_seconds`, `pre_roll_seconds`, `post_roll_seconds`, or `merge_gap_seconds` is negative or non-finite | `merge_gap_seconds` set to `-1`, or `video_duration_seconds` set to `NaN` |

`ClipEvidence` (see [data-model.md](../data-model.md)) is a separate, internal per-input-event record — it never causes a run to fail; it only explains how each input event was handled (windowed, clamped, excluded, or merged into a final clip).

## Consumer obligation

The Pipeline Orchestrator MUST obtain the clip plan via `generate_clips()` and pass `plan.clips` (in order) to Module 9 (Video Stitcher) without recomputing or second-guessing `clip_start_seconds`, `clip_end_seconds`, `clip_id`, or merge decisions — this module has already resolved them. A consumer MAY treat `ClipEvidence` as an internal record with no stable public contract — no consumer contract depends on it being exposed. A consumer that wishes to persist `clip_start_seconds`/`clip_end_seconds` back onto `events` rows MAY use each `PlannedClip.source_event_ids` to identify which rows a given clip's window applies to, but MUST NOT persist clips out of order relative to `plan.clips`, since FR-009's tie-break already resolves any ordering ambiguity.
