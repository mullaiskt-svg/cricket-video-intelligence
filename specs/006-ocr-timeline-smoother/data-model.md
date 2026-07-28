# Data Model: OCR Timeline Smoother

Derived from the Key Entities section of [spec.md](./spec.md). This feature has no persistent storage of its own (plan.md Technical Context) — these are in-memory value objects; the Pipeline Orchestrator remains solely responsible for persisting a result (FR-011).

## OCRTimelineSmootherRequest

A caller's request configuration, passed to `smooth_timeline()`.

| Field | Type | Notes |
|---|---|---|
| `scoreboard_ocr_result` | `ScoreboardOcrResult` (from Scoreboard OCR, `cvip.video.scoreboard_ocr_models`) | Required. The raw sample sequence to clean (FR-001). Must be present and structurally well-formed — ascending, non-decreasing `timestamp_seconds` across `samples` — validated lazily at `.run()` (FR-012), not at construction, mirroring every prior module's own lazy-validation precedent. |
| `outlier_window` | int | Required. The number of nearest *usable* neighbors (research.md Decision 4) required on each side to establish consensus for outlier detection (research.md Decision 1). Must be a positive integer; validated lazily at `.run()` (FR-013, `INVALID_SMOOTHING_CONFIGURATION`). Default recommended by research.md: `2`. |

**Validation rules** (enforced lazily inside `.run()`, before any sample is processed):
- `scoreboard_ocr_result` is present, and `scoreboard_ocr_result.samples` is ordered by strictly ascending `timestamp_seconds` — otherwise rejected with `INVALID_INPUT`.
- `outlier_window` is a real `int` (not `bool`) and `>= 1` — otherwise rejected with `INVALID_SMOOTHING_CONFIGURATION`.

## SmoothingEvidence

An internal record of what happened to one input sample (spec.md's "Smoothing Evidence" entity, FR-008) — not part of the public `Cleaned Scoreboard Sample` shape, but preserved for diagnostics/debugging/future tuning.

| Field | Type | Notes |
|---|---|---|
| `resolution` | `SmoothingResolution` (enum: `PASSED_THROUGH`, `HELD_FORWARD_UNUSABLE`, `HELD_FORWARD_OUTLIER`) | What this feature did with the sample. |
| `original_sample` | `ScoreboardSample` | The original, pre-smoothing sample exactly as Scoreboard OCR produced it — including its own `raw_text`, `ocr_confidence`, and `parse_confidence` — kept for comparison against the resolved `Cleaned Scoreboard Sample` (spec.md Key Entities: "the original (pre-smoothing) field values and confidence fields, for comparison"). |

`SmoothingResolution` is a small internal enum (not a public failure taxonomy — see `OCRTimelineSmootherFailureReason` below for that):

| Value | Meaning |
|---|---|
| `PASSED_THROUGH` | The sample was usable and not flagged as an outlier; its own field values are used as-is in the cleaned output. |
| `HELD_FORWARD_UNUSABLE` | Scoreboard OCR itself flagged this sample unusable (`ocr_confidence = 0` or `parse_confidence = 0`); its cleaned output fields come from the known-good tracker (or are all `null`, for a leading gap). |
| `HELD_FORWARD_OUTLIER` | The sample was usable but flagged as an isolated single-sample outlier (research.md Decisions 1–2); its cleaned output fields come from the known-good tracker. |

## CleanedScoreboardSample

A single per-second cleaned reading — this feature's public output unit (spec.md's "Cleaned Scoreboard Sample" entity, FR-009).

| Field | Type | Notes |
|---|---|---|
| `timestamp_seconds` | float | Carried through unchanged from the corresponding input sample (FR-007). |
| `runs` | int or `null` | `null` only for a leading gap before any known-good reading has been established (FR-006) — never for a mid-timeline or trailing gap, which always hold forward a concrete value. |
| `wickets` | int or `null` | Same leading-gap-only null semantics as `runs`. |
| `over_number` | int or `null` | |
| `ball_in_over` | int or `null` | |
| `batter` | str or `null` | |
| `non_striker` | str or `null` | |
| `bowler` | str or `null` | |
| `run_rate` | float or `null` | |

**No confidence fields** (`ocr_confidence`, `parse_confidence`) appear on this shape — a deliberate omission (spec.md Assumptions, FR-009): every returned sample already represents this feature's best resolved value, so there is no remaining trustworthiness judgment for a consumer to make. The original confidence values remain available internally via `SmoothingEvidence.original_sample`.

## OCRTimelineSmootherResult

The complete, ordered output of one smoothing run (spec.md's "OCR Timeline Smoother Result" entity).

| Field | Type | Notes |
|---|---|---|
| `source_video_id` | string | Carried through from `scoreboard_ocr_result.source_video_id` (FR-019), consistent with every prior module's identifier convention. |
| `samples` | tuple[`CleanedScoreboardSample`, ...] | The ordered (same order, same timestamps as the input) cleaned sample list (FR-007). A `tuple`, not a `list`, so the frozen result is genuinely immutable end-to-end — same reasoning as Scoreboard OCR's own `ScoreboardOcrResult.samples`. |
| `total_samples` | int | `len(samples)`. Always equal to the input's own `total_samples` (FR-007, FR-002 US1 AS5). |

## OCRTimelineSmootherFailureReason

The run-level failure taxonomy for this feature (spec.md's "OCR Timeline Smoother Failure Reason" entity, FR-014) — the smallest taxonomy of any module on this platform so far, since this feature has no video/frame access at all and therefore no mid-run decode or source-availability failure is even physically possible (spec.md Assumptions).

| Value | Meaning |
|---|---|
| `INVALID_INPUT` | The supplied `scoreboard_ocr_result` is missing, or its `samples` are not a well-formed, ascending-timestamp-ordered sequence. |
| `INVALID_SMOOTHING_CONFIGURATION` | The configured `outlier_window` is not a positive integer. |

## OCRTimelineSmootherDiagnostics

Exactly one per smoothing run (FR-017), including cancelled and failed runs. Reuses the platform-wide `ExecutionDiagnostics` shape (`src/cvip/common/diagnostics.py`, research.md Decision 5) rather than defining a new one:

| `ExecutionDiagnostics` field | How this feature populates it |
|---|---|
| `module_name` | `"video.ocr_timeline_smoother"` |
| `input_summary` | The request's `source_video_id`, total input sample count, and configured `outlier_window` |
| `output_summary` | Total samples processed, held-forward-due-to-unusable-flag count, held-forward-due-to-outlier count, no-reliable-value-yet count (a subset of the unusable-flag count — those with no known-good tracker value yet), processing duration |
| `warnings` | Reserved for future use — no warning conditions are currently defined for this feature |
| `failure_reason` | An `OCRTimelineSmootherFailureReason` value, or `null` on a normal (including cleanly cancelled) completion |

## Known-Good Tracker (internal, not part of any public entity)

The minimal rolling state the runner maintains for the fill pass (research.md Decision 3) — only the most recently established known-good reading's full field set, replaced in place each time a `PASSED_THROUGH` sample is encountered.

| Field | Type | Notes |
|---|---|---|
| `fields` | dict-like of the 8 `CleanedScoreboardSample` fields (excluding `timestamp_seconds`), or `null` | `null` before the first usable, non-outlier sample is seen (the leading-gap case, FR-006). Replaced wholesale (not merged field-by-field) each time a `PASSED_THROUGH` sample occurs. |

**Cold-start handling**: before any sample has been passed through, there is nothing to hold forward — any unusable-flagged or outlier-flagged sample encountered before the first `PASSED_THROUGH` sample is emitted as all-`null` fields (FR-006), and the first `PASSED_THROUGH` sample (guaranteed never to be flagged as an outlier itself — research.md Decision 1's "not enough usable neighbors yet" guard) seeds this tracker.

## Usable/Outlier Flag State (internal, not part of any public entity)

The output of research.md Decision 3's flag pass — one boolean-like classification per input sample, consumed by the fill pass.

| Field | Type | Notes |
|---|---|---|
| `is_unusable` | bool, per sample | `True` when `ocr_confidence == 0.0 or parse_confidence == 0.0` on the original sample (research.md Decision 4). |
| `is_outlier` | bool, per sample | `True` only for a usable sample (`is_unusable == False`) with at least `outlier_window` usable neighbors available on both sides, all of which agree with each other on the core scoring tuple while the target sample itself disagrees (research.md Decisions 1–2). Always `False` for an unusable sample (outlier detection only applies to samples Scoreboard OCR itself marked usable, FR-004). |
