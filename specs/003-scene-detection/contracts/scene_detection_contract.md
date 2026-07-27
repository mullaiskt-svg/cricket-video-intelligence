# Contract: Scene Detection

This module exposes one entry point to the rest of the CVIP pipeline. It is an internal Python library contract (no network/CLI surface), consistent with constitution Principle V (clear input/output contract, independently testable).

## `detect_scenes(request: SceneDetectionRequest) -> SceneDetector`

**Input**: a `SceneDetectionRequest` (see [data-model.md](../data-model.md)), wrapping a successful `LoadResult` from Video Loader (`specs/001-video-loader/`) and a `scene_threshold`.

**Output**: a `SceneDetector` — a context-manager object exposing `.run() -> SceneDetectionResult` (which performs the full detection pass and returns the result) and `.cancel()` (for cooperative cancellation, FR-019 — stopping cleanly and leaving the *Pipeline Orchestrator* able to resume the overall `cvip analyze` workflow; this feature does not itself support resuming mid-detection from a checkpoint). It internally consumes frames via `extract_frames()` (`specs/002-frame-extraction-service/`) in `SamplingMode.FULL`, never opening the video file itself (FR-003, research.md Decision 1).

**Preconditions**: `request.load_result.status == SUCCESS`. If not, `.run()` immediately raises `SceneDetectionError(SceneDetectionFailureReason.SOURCE_NOT_VALIDATED)` rather than attempting any file access (FR-001, FR-002) — consistent with Video Loader's and the Frame Extraction Service's own "reject before touching the file" pattern.

**Usage**:
```
with detect_scenes(request) as detector:
    result = detector.run()
    # or: detector.cancel() from another point in the Orchestrator's control flow
    # while .run() is in progress on another logical thread of control
# on exit (normal, cancelled, or exception): resources released, exactly one
# SceneDetectionDiagnostics record emitted
```

**Postconditions**:
- `result.boundaries` is strictly ordered by ascending `timestamp_seconds`, with no duplicate timestamps and no duplicate boundaries (FR-006).
- Every `SceneBoundary.confidence` is present and within `[0.0, 1.0]` — never absent (FR-008, SC-009).
- The full `result.boundaries` sequence, including classifications and confidence scores, is identical across repeated runs against the same video and the same `scene_threshold` (FR-020, SC-008).
- The video is read in exactly one forward pass via the Frame Extraction Service — no backward seeking, no re-decoding of any previously processed segment (FR-004).
- Regardless of how the run ends (completed normally, cancelled, or failed), exactly one `SceneDetectionDiagnostics` record is emitted (FR-015, FR-019).
- No network calls are made under any circumstance (FR-016).
- No GPU is required or used (FR-017).

## Error taxonomy (`SceneDetectionFailureReason` values)

| Value | Meaning | Example trigger |
|---|---|---|
| `SOURCE_NOT_VALIDATED` | The supplied `LoadResult` isn't a successful one | Caller passes a `FAILURE` `LoadResult` from Video Loader |
| `SOURCE_UNAVAILABLE_MID_RUN` | The source video became inaccessible after detection began | File deleted or locked partway through a long-running run |
| `DECODE_FAILURE_MID_RUN` | A specific frame failed to decode partway through an otherwise-good video | A corrupted frame later in the file |

This enum is the module's stable contract surface, distinct from Video Loader's and the Frame Extraction Service's own failure taxonomies (different modules' — data-model.md).

## Consumer obligation

Replay Detection (and, eventually, Event Detection) MUST obtain scene boundaries via `detect_scenes()` and MUST NOT re-run shot-boundary detection itself (FR-013, spec.md Out of Scope). A consumer MUST NOT treat a `REPLAY_TRANSITION` classification as proof that a segment is an actual replay — combining this signal with Replay Detection's other independently-weighted signals to make that determination is Replay Detection's exclusive responsibility (FR-021, spec.md Out of Scope).
