# Data Model: Scoreboard OCR

Derived from the Key Entities section of [spec.md](./spec.md). This feature has no persistent storage of its own (plan.md Technical Context) — these are in-memory value objects, mapping onto the existing `scoreboard_readings` table (`specs/technical_plan.md`) once the Pipeline Orchestrator persists a result; no schema change is required (research.md).

## ScoreboardOcrRequest

A caller's request configuration, passed to `extract_scoreboard()`.

| Field | Type | Notes |
|---|---|---|
| `load_result` | `LoadResult` (from Video Loader) | Required. Must have `status == SUCCESS`; validated lazily at `.run()` (FR-001, FR-002), not at construction. |
| `scoreboard_region` | tuple[float, float, float, float] | Required. The `(x, y, width, height)` ROI to OCR, as fractions of frame dimensions — the same shape convention as Replay Detection's `scoreboard_region` field. Validated lazily at `.run()` (FR-017, `INVALID_OCR_CONFIGURATION`). |
| `preprocess_grayscale` | bool | Required. Whether to convert the ROI to grayscale before further preprocessing (research.md: grayscale → upscale → threshold order). |
| `preprocess_threshold` | bool | Required. Whether to apply automatic (Otsu) thresholding as the final preprocessing step. |
| `preprocess_upscale` | int | Required. The integer upscale factor applied to the ROI before thresholding. Must be a positive integer (FR-017); `1` effectively disables upscaling without needing a separate boolean flag. |
| `min_confidence` | float | Required. Must be within `[0.0, 1.0]` (FR-017). Readings with `ocr_confidence` below this are still recorded as-is (FR-011) — this value only affects the diagnostics record's low-confidence count (FR-021), not the stored reading. |

**Validation rules** (enforced lazily inside `.run()`, before any frame is processed — mirroring Replay Detection's own lazy-validation precedent, research.md):
- `load_result.status == SUCCESS`, otherwise rejected with `SOURCE_NOT_VALIDATED`.
- `scoreboard_region`'s four values are each finite and within a sane range (`x`, `y` in `[0.0, 1.0]`; `width`, `height` positive and not pushing the ROI outside `[0.0, 1.0]` bounds), `preprocess_upscale` is a positive integer, and `min_confidence` is within `[0.0, 1.0]` — otherwise rejected with `INVALID_OCR_CONFIGURATION`.

## OCREvidence

An internal record of how one sample's fields and confidence values were reached (spec.md's "OCR Evidence" entity, FR-029) — not part of the public `ScoreboardSample` shape, but preserved by the implementation for diagnostics/debugging/explainability/future tuning (spec.md Assumptions).

| Field | Type | Notes |
|---|---|---|
| `raw_text` | str | The concatenation of all OCR-recognized tokens in the ROI, in detected reading order (research.md). Empty string if the region was undetectable (FR-010) or no tokens were recognized. |
| `preprocessed_image_ref` | Any (an in-memory array reference or a lightweight identifier) | A reference to the preprocessed image this frame's OCR ran against, for debugging (FR-029). Not required to be serializable; an implementation may store a copy of the array, a hash, or a path if persisted to disk for debugging — this is an internal, implementation-defined detail. |
| `ocr_confidence` | float (0.0-1.0) | The same value exposed publicly on `ScoreboardSample.ocr_confidence` — kept here too so `OCREvidence` is a self-contained record of one frame's full OCR outcome. |
| `field_confidences` | dict[str, float] | Per-field OCR confidence (research.md), keyed by field name (`runs`, `wickets`, `over_number`, `ball_in_over`, `batter`, `non_striker`, `bowler`, `run_rate`). A field the parser couldn't attribute to a specific recognized token is absent from this mapping, not assigned a fabricated value. |
| `parsed_fields` | dict[str, Any] | The structured-parsing stage's output (FR-030) before rule validation — the raw parsed value for each field the parser could locate, prior to any `parse_confidence` determination. |
| `validation_passed` | bool or `null` | A tri-state: `True`/`False` when validation actually ran (whether the parsed fields passed structural parsing and rule validation, i.e., whether this reading is *accepted*, FR-012); `null` when validation was never attempted at all (the scoreboard region was undetectable, or zero OCR tokens were recognized) -- distinct from `False`, which means validation ran and a specific check failed (found during code review, addressed pre-merge: PR review finding). |
| `validation_failure_reason` | `ValidationFailureReason` or `null` | The specific reason when `validation_passed` is `False` (FR-031); `null` when `validation_passed` is `True` **or** `null`. |

## ScoreboardSample

A single per-frame raw reading — this feature's public output unit (spec.md's "Scoreboard Sample" entity).

| Field | Type | Notes |
|---|---|---|
| `timestamp_seconds` | float | Double-precision, from the sampled frame's own timestamp (FR-027), converted to seconds regardless of native units. |
| `runs` | int or `null` | `null` if the field could not be structurally parsed from the raw text (FR-030) — distinct from `0`, a legitimate score. |
| `wickets` | int or `null` | Same null-vs-zero distinction as `runs`. |
| `over_number` | int or `null` | |
| `ball_in_over` | int or `null` | |
| `batter` | str or `null` | |
| `non_striker` | str or `null` | |
| `bowler` | str or `null` | |
| `run_rate` | float or `null` | |
| `raw_text` | str | Unparsed OCR output, kept for debugging OCR accuracy — same field name and purpose as `specs/technical_plan.md`'s `scoreboard_readings.raw_text` column. |
| `ocr_confidence` | float (0.0-1.0) | Always present (FR-009). `0.0` when the scoreboard region was undetectable (FR-010). |
| `parse_confidence` | float (0.0-1.0) | Always present (FR-009). `0.0` when structural parsing failed on an essential field or a rule-consistency check failed (FR-013, FR-030, FR-031); otherwise a value reflecting parse quality (`1.0` for a clean, fully rule-consistent reading). |

**`innings` is intentionally absent** from this shape (spec.md FR-008/Assumptions) — the corresponding `scoreboard_readings.innings` column is left `NULL` by whatever process persists this feature's output.

## ScoreboardOcrResult

The complete, ordered output of one extraction run for one video (spec.md's "Scoreboard OCR Result" entity).

| Field | Type | Notes |
|---|---|---|
| `source_video_id` | string | Reuses Video Loader's `MatchVideoSource.file_hash`, consistent with every prior module's identifier convention (FR-028). |
| `samples` | tuple[`ScoreboardSample`, ...] | The ordered (ascending `timestamp_seconds`) sample list (FR-006, FR-020). A `tuple`, not a `list`, so the frozen result is genuinely immutable end-to-end — same reasoning as Replay Detection's `ReplayDetectionResult.segments`. |
| `total_samples` | int | `len(samples)`. |

## ScoreboardOcrFailureReason

The run-level structural failure taxonomy for this feature (FR-018) — distinct from the other four modules' own taxonomies, per this platform's established per-module-taxonomy convention.

| Value | Meaning |
|---|---|
| `SOURCE_NOT_VALIDATED` | The supplied `LoadResult` does not have `status == SUCCESS`. |
| `INVALID_OCR_CONFIGURATION` | The configured scoreboard region, preprocessing settings, or minimum confidence are invalid. |
| `SOURCE_UNAVAILABLE_MID_RUN` | The source video became inaccessible after extraction had already begun. |
| `DECODE_FAILURE_MID_RUN` | A frame failed to decode partway through an otherwise-successful run. |

## ValidationFailureReason

The per-reading validation failure taxonomy (spec.md's "Validation Failure Reason" entity, FR-031), recorded in `OCREvidence.validation_failure_reason` whenever `parse_confidence` is reduced to `0.0`. Distinct from `ScoreboardOcrFailureReason` above, which covers run-level structural failures, not per-reading validation outcomes.

| Value | Meaning |
|---|---|
| `RUNS_DECREASED` | Parsed `runs` is lower than the last accepted reading's `runs`, and this comparison wasn't suppressed by the innings-transition heuristic. |
| `WICKETS_DECREASED` | Parsed `wickets` is lower than the last accepted reading's `wickets`, and this comparison wasn't suppressed by the innings-transition heuristic. |
| `INVALID_OVER_SEQUENCE` | Parsed `over_number` decreased relative to the last accepted reading (and wasn't suppressed by the innings-transition heuristic), or is otherwise out of sequence. |
| `INVALID_BALL_NUMBER` | Parsed `ball_in_over` falls outside its valid range (research.md/spec.md Assumptions: 0-6). |
| `PLAYER_PARSE_FAILED` | A field essential to a usable reading (e.g., `batter`) could not be structurally parsed from the raw OCR text at all (FR-030). |

This taxonomy is not a hard ceiling (FR-031) — future reasons may be added without changing this contract's shape.

## ScoreboardOcrDiagnostics

Exactly one per extraction run (FR-021), including cancelled and failed runs. Reuses the platform-wide `ExecutionDiagnostics` shape (`src/cvip/common/diagnostics.py`) rather than defining a new one:

| `ExecutionDiagnostics` field | How this feature populates it |
|---|---|
| `module_name` | `"video.scoreboard_ocr"` |
| `input_summary` | The request's `source_video_id` and configured ROI/preprocessing/min-confidence values |
| `output_summary` | Frames processed, undetectable-region count, average `ocr_confidence`, low-`ocr_confidence` count, average `parse_confidence`, `parse_confidence = 0` count (with a `Validation Failure Reason` breakdown), count served via the ROI-unchanged skip (FR-021, research.md Decision 1), the platform's configuration version, processing duration |
| `warnings` | Reserved for future use — no warning conditions are currently defined for this feature |
| `failure_reason` | A `ScoreboardOcrFailureReason` value, or `null` on a normal (including cleanly cancelled) completion |

## Last-Accepted-Reading Tracker (internal, not part of any public entity)

The minimal rolling state the extractor maintains for rule validation (FR-012, FR-013, FR-014; research.md) — only the most recent *accepted* reading's numeric fields, replaced in place each time a new reading is accepted.

| Field | Type | Notes |
|---|---|---|
| `runs` | int | The last accepted reading's `runs`. |
| `wickets` | int | The last accepted reading's `wickets`. |
| `over_number` | int | The last accepted reading's `over_number`. |
| `ball_in_over` | int | The last accepted reading's `ball_in_over`. |

**Cold-start handling**: before any reading has been accepted, there is nothing to compare against — the first reading with successfully-parsed numeric fields is accepted unconditionally (FR-016), and its fields seed this tracker.

**Innings-transition suppression**: when a would-be comparison finds both `wickets` and `runs` dropping relative to the tracked values, the `runs`/`wickets`/`over_number` monotonic checks (FR-013) are skipped for that one comparison (FR-014) — the reading is still otherwise validated (e.g., `ball_in_over`'s range check still applies) and, if it passes, becomes the new tracked reading.

## ROI-Unchanged Skip State (internal, not part of any public entity)

The single piece of state the extractor retains to implement research.md's Decision 1.

| Field | Type | Notes |
|---|---|---|
| `previous_roi_frame` | array-like or `null` | The raw (pre-preprocessing) pixel content of the most recently *OCR'd* (not skipped) sampled frame's ROI, for comparison against the next sampled frame's ROI. `null` before the first sample. |
| `previous_sample` | `ScoreboardSample` or `null` | The most recently produced sample (whether freshly OCR'd or itself reused via a skip) — reused verbatim, aside from `timestamp_seconds`, when the next frame's ROI is unchanged. |

A frame's ROI is considered unchanged when the whole-ROI difference (`cv2.absdiff(...).mean()`) against `previous_roi_frame` falls below a small, fixed tolerance (research.md) — chosen to absorb ordinary video-compression noise on an otherwise-static graphic without masking a genuine scoreboard update.
