# Contract: Frame Extraction Service

This module exposes one entry point to the rest of the CVIP pipeline. It is an internal Python library contract (no network/CLI surface), consistent with constitution Principle V (clear input/output contract, independently testable) — and it is itself the concrete implementation of that principle for frame access across the platform (see `specs/technical_plan.md` "Module 1a: Frame Extraction Service").

## `extract_frames(request: ExtractionRequest) -> FrameExtractor`

**Input**: an `ExtractionRequest` (see [data-model.md](../data-model.md)), wrapping a successful `LoadResult` from Video Loader (`specs/001-video-loader/`), a `SamplingMode`, and optional resume parameters.

**Output**: a `FrameExtractor` — an iterable, context-manager object. It is not itself the frames; iterating over it yields `FrameContext` instances one at a time (FR-005: this must never require holding the whole video in memory).

**Preconditions**: `request.load_result.status == SUCCESS`. If not, `extract_frames()` returns a `FrameExtractor` whose iteration immediately raises with `ExtractionFailureReason.SOURCE_NOT_VALIDATED` rather than attempting any file access (FR-001, FR-002) — consistent with Video Loader's own "always return a typed outcome, don't raise for expected failure cases" pattern.

**Usage**:
```
with extract_frames(request) as extractor:
    for frame_context in extractor:
        ... consume frame_context ...
        # extractor.progress is readable here at any point
    # extractor.progress reflects the final state after the loop
# on exit (normal, break, or exception): resources released, exactly one
# ExtractionDiagnostics record emitted
```

**Postconditions**:
- Every yielded `FrameContext` has a `frame_index`/`timestamp_seconds` consistent with FR-004 — the timestamp always comes from the actually-decoded frame, never computed from an assumed constant rate (research.md).
- The sequence of `frame_index`/`timestamp_seconds` pairs is identical across repeated runs against the same video and the same `ExtractionRequest` configuration (FR-006).
- `FrameExtractor.progress` (an `ExtractionProgress`, see data-model.md) is readable at any point during iteration, not only at completion (FR-007).
- `FrameExtractor.cancel()` may be called at any point; it stops further iteration, and — like any other exit path — triggers exactly one diagnostics emission and resource release (FR-015).
- Regardless of how iteration ends (exhausted normally, cancelled, or failed), exactly one `ExtractionDiagnostics` record is emitted (FR-010, FR-015).
- No network calls are made under any circumstance (FR-011).
- No GPU is required or used (FR-012).

## Error taxonomy (`ExtractionFailureReason` values)

| Value | Meaning | Example trigger |
|---|---|---|
| `SOURCE_NOT_VALIDATED` | The supplied `LoadResult` isn't a successful one | Caller passes a `FAILURE` `LoadResult` from Video Loader |
| `RESUME_POINT_OUT_OF_RANGE` | The requested resume point is outside the video's actual range | `resume_from_frame_index` greater than the video's total frame count |
| `SOURCE_UNAVAILABLE_MID_RUN` | The source video became inaccessible after extraction began | File deleted or locked partway through a long-running extraction |
| `DECODE_FAILURE_MID_RUN` | A specific frame failed to decode partway through an otherwise-good video | A corrupted frame later in the file |

This enum is the module's stable contract surface, distinct from Video Loader's own `FailureReason` (a different module's taxonomy — data-model.md).

## Consumer obligation

Any module that reads video frames — Scene Detection, Replay Detection, Scoreboard OCR, and (when built) Fielding Detection — MUST obtain them via `extract_frames()` and MUST NOT open the video file directly via OpenCV or any other means (FR-013; `specs/technical_plan.md`'s "single shared abstraction for frame access" decision). A consumer MUST NOT retain a `FrameContext`'s `frame` data past the point where it advances to the next iteration step without copying it first (FR-005, data-model.md ownership note).
