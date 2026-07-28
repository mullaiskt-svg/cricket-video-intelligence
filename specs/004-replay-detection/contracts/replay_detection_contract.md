# Contract: Replay Detection

This module exposes one entry point to the rest of the CVIP pipeline. It is an internal Python library contract (no network/CLI surface), consistent with constitution Principle V (clear input/output contract, independently testable).

## `detect_replays(request: ReplayDetectionRequest) -> ReplayDetector`

**Input**: a `ReplayDetectionRequest` (see [data-model.md](../data-model.md)), wrapping a successful `LoadResult` from Video Loader (`specs/001-video-loader/`), a `SceneDetectionResult` from Scene Detection (`specs/003-scene-detection/`), the five configured signal weights, a confidence threshold, a minimum segment duration, the scoreboard ROI (for the scoreboard-absence signal), and an optional logo template path.

**Output**: a `ReplayDetector` — a context-manager object exposing `.run() -> ReplayDetectionResult` (which performs the full detection pass and returns the result) and `.cancel()` (for cooperative cancellation, FR-023). It internally consumes frames via `extract_frames()` (`specs/002-frame-extraction-service/`) at the platform's configured 1 FPS rate (research.md Decision 2), never opening the video file itself.

**Preconditions**: All validated lazily inside `.run()`, in this order — `request.load_result.status == SUCCESS`; `request.scene_detection_result` corresponds to the same video; the five weights sum to 1.0 and `confidence_threshold`/`min_segment_seconds` are within valid ranges. On the first violation encountered, `.run()` immediately raises `ReplayDetectionError` with the matching reason (see Error taxonomy) and still emits exactly one diagnostics record — no frame is processed for any of these three rejection cases.

**Usage**:
```
with detect_replays(request) as detector:
    result = detector.run()
    # or: detector.cancel() from another point in the Orchestrator's control flow
    # while .run() is in progress on another logical thread of control
# on exit (normal, cancelled, or exception): resources released, exactly one
# ReplayDetectionDiagnostics record emitted
```

**Postconditions**:
- `result.segments` is strictly ordered by ascending `start_seconds`, tie-broken by ascending `end_seconds`, then by stable detection order (FR-018).
- Every `ReplaySegment.confidence` is present and within `[0.0, 1.0]` — never absent (FR-013).
- Every `ReplaySegment.replay_id` is unique within `result.segments` (FR-014, SC-011).
- No reported segment is shorter than `request.min_segment_seconds` (FR-012, SC-003).
- No reported segment's combined confidence is below `request.confidence_threshold` (FR-011).
- The full `result.segments` sequence, including confidence scores, is identical across repeated runs against the same `load_result`, `scene_detection_result`, and configuration (FR-024, SC-006).
- The video is read in exactly one forward pass via the Frame Extraction Service, at the configured 1 FPS rate — no backward seeking, no re-decoding of any previously processed segment (FR-019, SC-005).
- Regardless of how the run ends (completed normally, cancelled, or failed), exactly one `ReplayDetectionDiagnostics` record is emitted (FR-025).
- No network calls are made under any circumstance (FR-020).
- No GPU is required or used (FR-021).
- No other module's replay classification is recomputed by this feature, and this feature's own classification is never expected to be recomputed downstream (FR-028) — this is a mutual constraint documented here for both sides of the contract.

## Error taxonomy (`ReplayDetectionFailureReason` values)

| Value | Meaning | Example trigger |
|---|---|---|
| `SOURCE_NOT_VALIDATED` | The supplied `LoadResult` isn't a successful one | Caller passes a `FAILURE` `LoadResult` from Video Loader |
| `INVALID_SCENE_DETECTION_RESULT` | The supplied Scene Detection result is missing, malformed, or doesn't match the video | `scene_detection_result.source_video_id` differs from `load_result.source.file_hash` |
| `INVALID_REPLAY_CONFIGURATION` | The configured weights, threshold, or minimum duration are invalid | The five weights sum to 0.9 instead of 1.0 |
| `SOURCE_UNAVAILABLE_MID_RUN` | The source video became inaccessible after detection began | File deleted or locked partway through a long-running run |
| `DECODE_FAILURE_MID_RUN` | A specific frame failed to decode partway through an otherwise-good video | A corrupted frame later in the file |

This enum is the module's stable contract surface, distinct from Video Loader's, the Frame Extraction Service's, and Scene Detection's own failure taxonomies (different modules' — data-model.md).

## Consumer obligation

Event Detection (Module 5) and Clip Generator (Module 8) MUST obtain replay segments via `detect_replays()` (or, once built, the Pipeline Orchestrator's persisted `replays` table populated from this feature's output) and MUST NOT re-run replay detection themselves (FR-026, spec.md Out of Scope). A consumer MUST treat `ReplaySegment.confidence` and the fact that a segment was reported at all as final — it MUST NOT recompute replay classification from scratch or apply a different confidence threshold to second-guess this feature's decision (FR-028).
