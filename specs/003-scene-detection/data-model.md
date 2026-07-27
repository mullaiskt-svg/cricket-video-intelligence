# Data Model: Scene Detection

Derived from the Key Entities section of [spec.md](./spec.md). This feature has no persistent storage (plan.md Technical Context) — these are in-memory value objects passed from this service to whichever pipeline module requested detection (Replay Detection, within the same `cvip analyze` run).

## BoundaryType

The two canonical classification values named in spec.md FR-007.

| Value | Meaning |
|---|---|
| `ORDINARY_CUT` | A hard cut between camera angles — a wide shot to close-up, camera-to-camera switch, or any shot boundary without an editorial transition effect. |
| `REPLAY_TRANSITION` | A boundary carrying the visual signature of an editorial transition effect (a wipe, dissolve, or logo sting) broadcasters use to bracket a replay. |

## SceneDetectionRequest

A caller's request configuration, passed to `detect_scenes()`.

| Field | Type | Notes |
|---|---|---|
| `load_result` | `LoadResult` (from Video Loader) | Required. Must have `status == SUCCESS`; a request against a failed `LoadResult` is rejected before any file access (FR-001, FR-002). |
| `scene_threshold` | float | Required. The sensitivity threshold applied to decide what counts as a cut (FR-012). Supplied by the caller — this feature does not read `config/default.yaml` itself (research.md). |

**Note**: unlike the Frame Extraction Service, this feature does not itself support resuming mid-detection from a checkpoint — spec.md's FR-019 only requires clean cancellation (stop, release resources, emit diagnostics) and leaving the *Pipeline Orchestrator* able to resume the overall `cvip analyze` workflow afterward (e.g., by re-running this feature from the start later). No `resume_from_frame_index`-style field exists on this request; introducing one would be scope beyond what spec.md requires.

**Validation rules** (enforced before detection begins):
- `load_result.status == SUCCESS`, otherwise rejected with `SOURCE_NOT_VALIDATED` before any frame is read (FR-001, FR-002).
- `scene_threshold` must be a finite, non-negative number; the value itself is applied as given, never second-guessed (FR-012, spec.md Edge Cases on extreme threshold values).

## SceneBoundary

A single detected cut point (spec.md's "Scene Boundary" entity).

| Field | Type | Notes |
|---|---|---|
| `boundary_id` | int | 0-based sequential integer, unique within this detection run, assigned in ascending-timestamp order (FR-009, research.md). |
| `timestamp_seconds` | float | Double-precision, seconds from the start of the video; read from the underlying frame's actual decoded timestamp, never a constant-frame-rate calculation (FR-010). |
| `boundary_type` | `BoundaryType` | Exactly one of `ORDINARY_CUT` / `REPLAY_TRANSITION` (FR-007). |
| `confidence` | float (0.0-1.0) | Always present — the classifier's certainty in the assigned `boundary_type`, not a measure of whether the boundary itself exists (FR-008). A value of 1.0 means maximally confident in the classification, whichever one was assigned. |

**Ordering/uniqueness**: The full list of `SceneBoundary` values within one `SceneDetectionResult` is strictly ordered by ascending `timestamp_seconds`, contains no two boundaries with the same timestamp, and contains no duplicate boundaries (FR-006). No tie-breaking rule is needed between independently-produced boundaries at the same timestamp, since `boundary_type` and `confidence` are decided together as one classification step per detected cut (spec.md Assumptions).

## SceneDetectionResult

The complete, ordered output of one detection run for one video (spec.md's "Scene Detection Result" entity).

| Field | Type | Notes |
|---|---|---|
| `source_video_id` | string | Reuses Video Loader's `MatchVideoSource.file_hash`, consistent with the Frame Extraction Service's `FrameContext.source_video_id` (FR-014). |
| `boundaries` | list[`SceneBoundary`] | The ordered boundary list (FR-005, FR-006). Empty list is a valid outcome. |
| `total_boundaries` | int | `len(boundaries)` (FR-014). |
| `replay_transition_count` | int | Count of boundaries with `boundary_type == REPLAY_TRANSITION` (FR-014). |
| `processing_duration` | float | Wall-clock seconds the detection run took (FR-014). |
| `configuration_version` | int | The `config_version` value in effect when this run executed, for auditability (FR-014). |

## SceneDetectionFailureReason

The failure taxonomy for this feature — distinct from Video Loader's and the Frame Extraction Service's own failure taxonomies (a different module's, per plan.md's file-naming decision).

| Value | Meaning |
|---|---|
| `SOURCE_NOT_VALIDATED` | The supplied `LoadResult` does not have `status == SUCCESS` (FR-002). |
| `SOURCE_UNAVAILABLE_MID_RUN` | The source video became inaccessible after detection had already begun (FR-018). |
| `DECODE_FAILURE_MID_RUN` | A frame failed to decode partway through an otherwise-successful run (FR-018). |

## SceneDetectionDiagnostics

Exactly one per detection run (FR-015), including cancelled runs. Reuses the platform-wide `ExecutionDiagnostics` shape (`src/cvip/common/diagnostics.py`, introduced by Video Loader) rather than defining a new one:

| `ExecutionDiagnostics` field | How this feature populates it |
|---|---|
| `module_name` | `"video.scene_detection"` |
| `input_summary` | The request's `source_video_id` and `scene_threshold` |
| `output_summary` | Total frames analyzed, total boundaries detected, replay-transition count, peak memory usage |
| `warnings` | Reserved for future use (e.g., a resume point coinciding exactly with an existing boundary) — no warning conditions are currently defined for this feature |
| `failure_reason` | A `SceneDetectionFailureReason` value, or `null` on a normal (including cleanly cancelled) completion |

**State transitions**: None beyond the request/response lifecycle — a detection run is constructed, executed (optionally cancelled), and on exit (normal, cancelled, or failed) emits exactly one `SceneDetectionDiagnostics` record. It holds no state across separate `detect_scenes()` calls; resume state is the caller's responsibility, consistent with the Frame Extraction Service (research.md).
