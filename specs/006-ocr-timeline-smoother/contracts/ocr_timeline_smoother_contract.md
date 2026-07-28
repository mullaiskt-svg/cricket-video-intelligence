# Contract: OCR Timeline Smoother

This module exposes one entry point to the rest of the CVIP pipeline. It is an internal Python library contract (no network/CLI surface), consistent with constitution Principle V (clear input/output contract, independently testable).

## `smooth_timeline(request: OCRTimelineSmootherRequest) -> OCRTimelineSmootherRunner`

**Input**: an `OCRTimelineSmootherRequest` (see [data-model.md](../data-model.md)), wrapping a `ScoreboardOcrResult` from Scoreboard OCR (`specs/005-scoreboard-ocr/`) and a configured `outlier_window`. Unlike every prior module's entry point, this call never touches a `LoadResult`, the Frame Extraction Service, or a video file of any kind (FR-001, FR-002) — its only input is Scoreboard OCR's own already-structured result.

**Output**: an `OCRTimelineSmootherRunner` — a context-manager object exposing `.run() -> OCRTimelineSmootherResult` (which performs the full two-pass smoothing operation, research.md Decision 3, and returns the result) and `.cancel()` (for cooperative cancellation, FR-015).

**Preconditions**: All validated lazily inside `.run()`, in this order — `request.scoreboard_ocr_result` is present and its `samples` form a well-formed, ascending-timestamp-ordered sequence; `request.outlier_window` is a positive integer. On the first violation encountered, `.run()` immediately raises `OCRTimelineSmootherError` with the matching reason (see Error taxonomy) and still emits exactly one diagnostics record — no sample is processed for either of these two rejection cases.

**Usage**:
```
with smooth_timeline(request) as runner:
    result = runner.run()
    # or: runner.cancel() from another point in the Orchestrator's control flow
    # while .run() is in progress on another logical thread of control
# on exit (normal, cancelled, or exception): exactly one
# OCRTimelineSmootherDiagnostics record emitted
```

**Postconditions**:
- `result.samples` has exactly one entry per input sample, in the same order, at the same `timestamp_seconds` — never fewer, never reordered, regardless of how many samples required gap-filling or outlier correction (FR-007, SC-002).
- A sample Scoreboard OCR flagged unusable (`ocr_confidence = 0` or `parse_confidence = 0`) is never left as-is in the cleaned output — its fields are always replaced by holding forward the most recently established known-good reading, or left as explicit `null` fields if no known-good reading exists yet (FR-003, FR-006, SC-003).
- A usable sample that is an isolated single-sample outlier relative to its surrounding usable neighbors (research.md Decisions 1–2) is discounted and replaced the same way as an unusable sample (FR-004, SC-004) — a run of two or more *consecutive* samples agreeing on a divergent value is never discounted this way (spec.md Edge Cases).
- No gap or outlier is ever resolved via numeric interpolation — only by holding forward a previously-established known-good value (FR-005).
- Every `CleanedScoreboardSample`'s fields are plain, self-contained values with no reference to any run-internal state (FR-019, US2 AS1); `result.source_video_id` is carried through from the input (FR-019, US2 AS2).
- The full `result.samples` sequence is identical across repeated runs against the same input and configuration (FR-016, SC-005).
- Regardless of how the run ends (completed normally, cancelled, or failed), exactly one `OCRTimelineSmootherDiagnostics` record is emitted (FR-017, SC-006).
- No network calls are made under any circumstance, and no GPU is required or used (FR-018).
- This feature never derives a scoring event, highlight-worthiness determination, or replay classification from its own output (FR-010) — it produces a cleaned timeline only.

## Error taxonomy (`OCRTimelineSmootherFailureReason` values)

| Value | Meaning | Example trigger |
|---|---|---|
| `INVALID_INPUT` | The supplied `scoreboard_ocr_result` is missing, or its `samples` are not a well-formed, ascending-timestamp-ordered sequence | Caller passes `None`, or a result whose samples are out of timestamp order |
| `INVALID_SMOOTHING_CONFIGURATION` | The configured `outlier_window` is not a positive integer | `outlier_window` set to `0` or `-1` |

This enum is the module's entire stable contract surface for structural failures — the smallest taxonomy of any module on this platform so far, since this feature has no video/frame access and therefore no mid-run decode or source-availability failure is even physically possible (spec.md Assumptions). `SmoothingEvidence` (see [data-model.md](../data-model.md)) is a separate, internal per-sample record — it never causes a run to fail; it only explains what happened to each sample.

## Consumer obligation

Event Detection (Module 5) MUST obtain the cleaned scoreboard timeline via `smooth_timeline()` (or, once built, the Pipeline Orchestrator's persisted representation populated from this feature's output) and MUST NOT diff Scoreboard OCR's raw output directly, nor implement its own gap-filling or outlier-detection logic (spec.md Out of Scope). A consumer MAY treat every field on every `CleanedScoreboardSample` as this feature's best resolved value — there is no remaining confidence field for a consumer to additionally judge (spec.md Assumptions). `SmoothingEvidence` is an internal record this feature preserves for its own diagnostics/tuning purposes; no consumer contract depends on it being exposed.
