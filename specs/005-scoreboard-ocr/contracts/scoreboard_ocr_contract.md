# Contract: Scoreboard OCR

This module exposes one entry point to the rest of the CVIP pipeline. It is an internal Python library contract (no network/CLI surface), consistent with constitution Principle V (clear input/output contract, independently testable).

## `extract_scoreboard(request: ScoreboardOcrRequest) -> ScoreboardOcrExtractor`

**Input**: a `ScoreboardOcrRequest` (see [data-model.md](../data-model.md)), wrapping a successful `LoadResult` from Video Loader (`specs/001-video-loader/`), the scoreboard region (ROI), preprocessing settings (grayscale/upscale/threshold), and a minimum OCR confidence.

**Output**: a `ScoreboardOcrExtractor` — a context-manager object exposing `.run() -> ScoreboardOcrResult` (which performs the full extraction pass and returns the result) and `.cancel()` (for cooperative cancellation, FR-019). It internally consumes frames via `extract_frames()`'s shared `FrameContext` (`specs/002-frame-extraction-service/`) at the platform's configured 1 FPS rate, never opening the video file itself.

**Preconditions**: All validated lazily inside `.run()`, in this order — `request.load_result.status == SUCCESS`; the scoreboard region, preprocessing settings, and minimum confidence are within valid ranges. On the first violation encountered, `.run()` immediately raises `ScoreboardOcrError` with the matching reason (see Error taxonomy) and still emits exactly one diagnostics record — no frame is processed for either of these two rejection cases.

**Usage**:
```
with extract_scoreboard(request) as extractor:
    result = extractor.run()
    # or: extractor.cancel() from another point in the Orchestrator's control flow
    # while .run() is in progress on another logical thread of control
# on exit (normal, cancelled, or exception): resources released, exactly one
# ScoreboardOcrDiagnostics record emitted
```

**Postconditions**:
- `result.samples` is strictly ordered by ascending `timestamp_seconds`, one entry per frame sampled at the platform's configured rate (FR-006, FR-020) — never fewer, regardless of how many individual readings were low-confidence or rule-violating.
- Every `ScoreboardSample` carries both `ocr_confidence` and `parse_confidence`, each present and within `[0.0, 1.0]` — never absent (FR-009).
- A sample whose scoreboard region was undetectable has `ocr_confidence = 0.0` and empty `raw_text` (FR-010) — this is a valid, non-error outcome, not a failure.
- A sample whose parsed numeric fields violate the applicable monotonic rule against the last *accepted* reading, or whose essential fields could not be structurally parsed at all, has `parse_confidence = 0.0` (FR-013, FR-015, FR-030) — never a fabricated corrected value.
- The full `result.samples` sequence, including both confidence fields, is identical across repeated runs against the same `load_result` and configuration (FR-020, SC-006) — this holds regardless of whether any given sample was freshly OCR'd or served via the ROI-unchanged skip (research.md Decision 1), since the skip decision itself is a deterministic function of frame content.
- The video is read in exactly one forward pass via the Frame Extraction Service, at the configured 1 FPS rate — no backward seeking, no re-decoding of any previously processed frame (FR-024, SC-005).
- Regardless of how the run ends (completed normally, cancelled, or failed), exactly one `ScoreboardOcrDiagnostics` record is emitted (FR-021).
- No network calls are made under any circumstance (FR-025).
- No GPU is required or used (FR-026).
- This feature never derives a scoring event, highlight-worthiness determination, or replay classification from its own output (FR-023) — it produces raw readings only.

## Error taxonomy (`ScoreboardOcrFailureReason` values)

| Value | Meaning | Example trigger |
|---|---|---|
| `SOURCE_NOT_VALIDATED` | The supplied `LoadResult` isn't a successful one | Caller passes a `FAILURE` `LoadResult` from Video Loader |
| `INVALID_OCR_CONFIGURATION` | The configured scoreboard region, preprocessing settings, or minimum confidence are invalid | `min_confidence` set to `1.5`, outside `[0.0, 1.0]` |
| `SOURCE_UNAVAILABLE_MID_RUN` | The source video became inaccessible after extraction began | File deleted or locked partway through a long-running run |
| `DECODE_FAILURE_MID_RUN` | A specific frame failed to decode partway through an otherwise-good video | A corrupted frame later in the file |

This enum is the module's stable contract surface for *run-level* structural failures — distinct from `ValidationFailureReason` (see [data-model.md](../data-model.md)), which describes *per-reading* validation outcomes and never aborts a run, and distinct from every other module's own failure taxonomy on this platform.

## Consumer obligation

Event Detection (Module 5) MUST obtain the raw scoreboard timeline via `extract_scoreboard()` (or, once built, the Pipeline Orchestrator's persisted `scoreboard_readings` table populated from this feature's output) and MUST NOT run its own OCR or re-derive raw readings from video frames itself (spec.md Out of Scope). A consumer MUST treat a sample with `parse_confidence = 0` as unusable for deriving an event (US2 Acceptance Scenario 3) — it MUST NOT attempt its own correction, reinterpretation, or re-validation of the raw text. `OCREvidence` is an internal record this feature preserves for its own diagnostics/tuning purposes; no consumer contract depends on it being exposed.
