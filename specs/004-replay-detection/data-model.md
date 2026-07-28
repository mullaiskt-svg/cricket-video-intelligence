# Data Model: Replay Detection

Derived from the Key Entities section of [spec.md](./spec.md). This feature has no persistent storage of its own (plan.md Technical Context) — these are in-memory value objects, except where noted that a field is intended to map onto the `replays` table once the Pipeline Orchestrator persists a result (research.md Decision 1).

## ReplayDetectionRequest

A caller's request configuration, passed to `detect_replays()`.

| Field | Type | Notes |
|---|---|---|
| `load_result` | `LoadResult` (from Video Loader) | Required. Must have `status == SUCCESS`; validated lazily at `.run()` (FR-001, FR-003), not at construction. |
| `scene_detection_result` | `SceneDetectionResult` (from Scene Detection) | Required. Must correspond to the same video as `load_result` (same `source_video_id`); validated lazily at `.run()` (FR-002, `INVALID_SCENE_DETECTION_RESULT`). |
| `logo_weight`, `scoreboard_weight`, `motion_weight`, `transition_weight`, `camera_angle_weight` | float | Required. Must sum to 1.0 within a small tolerance (FR-010); validated lazily at `.run()`, not at construction (research.md). Defaults sourced from `config/default.yaml`'s `replay.signals` block by the caller, not read by this feature itself. |
| `confidence_threshold` | float | Required. Must be within `[0.0, 1.0]` (FR-010). A candidate segment's combined confidence must meet or exceed this to be reported (FR-011). |
| `min_segment_seconds` | float | Required. Must be finite and non-negative (FR-010). A candidate segment shorter than this is never reported, regardless of confidence (FR-012). |
| `logo_template_path` | str or `null` | Optional. Path to a reference image for the logo-presence signal (research.md). When `null`, that signal always scores 0.0 (FR-015) rather than failing the run. |
| `scoreboard_region` | tuple[float, float, float, float] | Required. The `(x, y, width, height)` ROI to check for the scoreboard-absence signal (FR-008), as fractions of frame dimensions — the same shape as `config/default.yaml`'s `ocr.scoreboard_region`, sourced by the caller, not read by this feature itself (consistent with how signal weights are also caller-supplied). |

**Validation rules** (enforced lazily inside `.run()`, before any frame is processed — research.md's "lazy validation" decision):
- `load_result.status == SUCCESS`, otherwise rejected with `SOURCE_NOT_VALIDATED`.
- `scene_detection_result` is present and its `source_video_id` matches `load_result.source.file_hash`, otherwise rejected with `INVALID_SCENE_DETECTION_RESULT`.
- The five weights sum to 1.0 (±1e-6 tolerance), `confidence_threshold` is within `[0.0, 1.0]`, and `min_segment_seconds` is finite and non-negative — otherwise rejected with `INVALID_REPLAY_CONFIGURATION`.

## ReplayEvidence

An internal record of how one candidate segment's combined confidence was reached (spec.md's "Replay Evidence" entity) — not part of the public `ReplaySegment`/`ReplayDetectionResult` shape, but preserved by the implementation for diagnostics/explainability/future tuning (spec.md Assumptions).

| Field | Type | Notes |
|---|---|---|
| `logo_score` | float (0.0-1.0) | Per-segment mean of the logo-presence signal across sampled frames (FR-029); 0.0 if no template configured (FR-015). |
| `scoreboard_score` | float (0.0-1.0) | Per-segment mean of the scoreboard-absence signal (FR-029), relative to the live-action baseline (research.md). |
| `motion_score` | float (0.0-1.0) | Per-segment mean of the motion-profile signal (FR-029), relative to the live-action baseline. |
| `transition_score` | float (0.0-1.0) | Scene Detection's own `REPLAY_TRANSITION` confidence for the boundary bracketing this segment (FR-007) — `0.0` if the bracketing boundary was `ORDINARY_CUT` instead. |
| `camera_angle_score` | float (0.0-1.0) | Per-segment mean of the camera-angle-difference signal (FR-029), relative to the live-action baseline. |
| `combined_confidence` | float (0.0-1.0) | The weighted sum of the five scores above using the request's configured weights (FR-009). This value becomes `ReplaySegment.confidence` for segments that clear the threshold. |

## ReplaySegment

A single detected stretch of replay footage — this feature's public output unit (spec.md's "Replay Segment" entity).

| Field | Type | Notes |
|---|---|---|
| `replay_id` | int | 0-based sequential integer, unique within this detection run, assigned in ascending-order-of-report (FR-014). Intended to become the literal `replays.replay_id` primary key value once persisted (research.md Decision 1). |
| `start_seconds` | float | Double-precision, from Scene Detection's boundary timestamps (or the video's own start, per spec.md's Edge Cases, for a segment with no leading boundary). |
| `end_seconds` | float | Same precision/source conventions as `start_seconds`, or the video's own end. |
| `confidence` | float (0.0-1.0) | Always present — the `ReplayEvidence.combined_confidence` that cleared the threshold (FR-013). |

**Ordering/uniqueness**: The full list of `ReplaySegment` values within one `ReplayDetectionResult` is strictly ordered by ascending `start_seconds`; ties broken by ascending `end_seconds`, then by stable input (detection) order (FR-018).

## ReplayDetectionResult

The complete, ordered output of one detection run for one video (spec.md's "Replay Detection Result" entity).

| Field | Type | Notes |
|---|---|---|
| `source_video_id` | string | Reuses Video Loader's `MatchVideoSource.file_hash`, consistent with the Frame Extraction Service's and Scene Detection's own identifier convention (FR-017). |
| `segments` | list[`ReplaySegment`] | The ordered segment list (FR-016, FR-018). Empty list is a valid outcome. |
| `total_segments` | int | `len(segments)`. |
| `total_replay_duration` | float | Sum of `(end_seconds - start_seconds)` across all reported segments. |

## ReplayDetectionFailureReason

The failure taxonomy for this feature (FR-022) — distinct from the other three modules' own taxonomies, per this platform's established per-module-taxonomy convention.

| Value | Meaning |
|---|---|
| `SOURCE_NOT_VALIDATED` | The supplied `LoadResult` does not have `status == SUCCESS`. |
| `INVALID_SCENE_DETECTION_RESULT` | The supplied Scene Detection result is missing, malformed, or does not correspond to the video being analyzed. |
| `INVALID_REPLAY_CONFIGURATION` | The configured signal weights don't sum to 1.0, or the threshold/minimum-duration are out of range. |
| `SOURCE_UNAVAILABLE_MID_RUN` | The source video became inaccessible after detection had already begun. |
| `DECODE_FAILURE_MID_RUN` | A frame failed to decode partway through an otherwise-successful run. |

## ReplayDetectionDiagnostics

Exactly one per detection run (FR-025), including cancelled and failed runs. Reuses the platform-wide `ExecutionDiagnostics` shape (`src/cvip/common/diagnostics.py`) rather than defining a new one:

| `ExecutionDiagnostics` field | How this feature populates it |
|---|---|
| `module_name` | `"video.replay_detection"` |
| `input_summary` | The request's `source_video_id` and configured weights/threshold/min-duration |
| `output_summary` | Candidate segments evaluated, replay segments accepted, replay segments rejected, average confidence, highest confidence, longest replay duration, total replay duration, sampling rate used |
| `warnings` | Reserved for future use — no warning conditions are currently defined for this feature |
| `failure_reason` | A `ReplayDetectionFailureReason` value, or `null` on a normal (including cleanly cancelled) completion |

## Live-Action Baseline (internal, not part of any public entity)

The rolling reference state the detector maintains for the three baseline-relative signals (research.md), updated only from frames outside any currently-open candidate segment.

| Field | Type | Notes |
|---|---|---|
| `scoreboard_region_signature_mean` | float | Rolling mean of the scoreboard-ROI content measure from recent non-candidate frames. |
| `frame_diff_magnitude_mean` | float | Rolling mean of whole-frame difference magnitude from recent non-candidate frames. |
| `frame_fingerprint_mean` | array-like | Rolling mean of the coarse whole-frame descriptor from recent non-candidate frames. |
| `sample_count` | int | How many non-candidate frames have contributed to the rolling means so far — used to decide whether the baseline has enough evidence yet (see Edge Cases below). |

**Cold-start handling**: A candidate segment encountered before the baseline has accumulated any non-candidate samples (e.g., a replay at the very start of the video) cannot be meaningfully compared against a live-action baseline that doesn't exist yet. In that case, the three baseline-relative signals contribute their neutral midpoint (0.5) rather than a fabricated 0.0 or 1.0 — consistent with `_classify`-style "insufficient evidence, honest neutral value" handling already established in Scene Detection's own classification heuristic, not a new pattern invented here.
