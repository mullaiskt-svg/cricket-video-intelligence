# Data Model: Frame Extraction Service

Derived from the Key Entities section of [spec.md](./spec.md). This feature has no persistent storage (plan.md Technical Context) — these are in-memory value objects passed from this service to whichever pipeline module requested frames.

## SamplingMode

The four canonical sampling modes named in spec.md FR-003 and Assumptions.

| Value | Meaning |
|---|---|
| `FULL` | Every native frame is yielded. |
| `FIXED_INTERVAL` | Frames are yielded at a caller-specified rate (e.g., 1 FPS), regardless of the video's native rate. |
| `FRAME_LIST` | Only the frames at a caller-specified, explicit list of frame indices are yielded. |
| `TIMESTAMP_LIST` | Only the frames nearest to a caller-specified, explicit list of timestamps are yielded. |

## ExtractionRequest

A caller's request configuration, passed to `extract_frames()`.

| Field | Type | Notes |
|---|---|---|
| `load_result` | `LoadResult` (from Video Loader) | Required. Must have `status == SUCCESS`; a request against a failed `LoadResult` is rejected before any file access (FR-001, FR-002). |
| `mode` | `SamplingMode` | Required. Exactly one mode per request (FR-003). |
| `rate_fps` | float or `null` | Required when `mode == FIXED_INTERVAL`; ignored otherwise. |
| `frame_indices` | list[int] or `null` | Required when `mode == FRAME_LIST`; ignored otherwise. Sorted and de-duplicated internally regardless of input order (FR-003). |
| `timestamps_seconds` | list[float] or `null` | Required when `mode == TIMESTAMP_LIST`; ignored otherwise. Sorted and de-duplicated internally regardless of input order (FR-003). |
| `resume_from_frame_index` | int or `null` | Optional. If set, extraction starts at this index (inclusive), not frame 0 (FR-008). |
| `resume_from_timestamp_seconds` | float or `null` | Optional. Ignored if `resume_from_frame_index` is also set (FR-008 precedence rule). |

**Validation rules** (enforced before extraction begins):
- Exactly one of `rate_fps` / `frame_indices` / `timestamps_seconds` is populated, matching `mode`.
- If both `resume_from_frame_index` and `resume_from_timestamp_seconds` are set, `resume_from_frame_index` wins (FR-008).
- A resume point (whichever form) outside the video's actual frame/time range is rejected with `RESUME_POINT_OUT_OF_RANGE` before any frames are yielded (FR-009).

## FrameContext

The single, stable payload yielded for every frame (spec.md's "Frame Context" entity) — this, not a bare image, is what every consumer (Scene Detection, Replay Detection, Scoreboard OCR, and future modules) depends on.

| Field | Type | Notes |
|---|---|---|
| `source_video_id` | string | Reuses Video Loader's `MatchVideoSource.file_hash` (research.md) — identifies which video this frame came from. |
| `frame_index` | int | 0-based, in the *original* (native) video, not the sampled sequence (FR-004). |
| `timestamp_seconds` | float | Numeric, sub-second precision, read from the actual decoded frame — never computed from an assumed constant frame rate (FR-004, research.md's seek-based decision). Never a formatted clock string internally. |
| `frame` | array-like image data | The decoded frame's pixel data. |
| `metadata` | dict, default empty | Reserved for future optional fields without breaking existing consumers (FR-004). |

**Ownership/lifetime**: A `FrameContext`'s `frame` data is only guaranteed valid through the current iteration step — `FrameExtractor` (see contracts/) may reuse or invalidate the underlying buffer once the caller advances to the next frame (FR-005). A consumer that needs the pixel data beyond that point must copy it.

## ExtractionProgress

The standardized progress snapshot, queryable at any point during a run (spec.md FR-007).

| Field | Type | Notes |
|---|---|---|
| `processed_frames` | int | Frames yielded so far in this request. |
| `total_frames` | int | Total frames expected for this request, given its mode/range. |
| `processed_seconds` | float | Elapsed video-time processed so far. |
| `total_duration_seconds` | float | Total video-time expected to be processed for this request. |
| `percent_complete` | float (0-100) | Derived from the frame or time counters above (whichever is more precise for the active mode). |

## ExtractionFailureReason

The failure taxonomy for this feature — distinct from Video Loader's own `FailureReason` (a different module's taxonomy, per plan.md's file-naming decision).

| Value | Meaning |
|---|---|
| `SOURCE_NOT_VALIDATED` | The supplied `LoadResult` does not have `status == SUCCESS` (FR-002). |
| `RESUME_POINT_OUT_OF_RANGE` | The requested resume point (frame index or timestamp) is outside the video's actual range (FR-009). |
| `SOURCE_UNAVAILABLE_MID_RUN` | The source video became inaccessible after extraction had already begun (FR-014). |
| `DECODE_FAILURE_MID_RUN` | A frame failed to decode partway through an otherwise-successful run (FR-014). |

## ExtractionDiagnostics

Exactly one per extraction run (FR-010, FR-015), including cancelled runs. Reuses the platform-wide `ExecutionDiagnostics` shape (`src/cvip/common/diagnostics.py`, introduced by Video Loader) rather than defining a new one:

| `ExecutionDiagnostics` field | How this feature populates it |
|---|---|
| `module_name` | `"video.frame_extraction"` |
| `input_summary` | The request's `source_video_id`, `mode`, and rate/list size |
| `output_summary` | Frames yielded, total video-time covered |
| `warnings` | One entry per skipped out-of-range `FRAME_LIST`/`TIMESTAMP_LIST` entry (spec.md Edge Cases) |
| `failure_reason` | An `ExtractionFailureReason` value, or `null` on a normal (including cleanly cancelled) completion |

**State transitions**: None beyond the request/response lifecycle — a `FrameExtractor` is constructed, iterated (optionally cancelled), and on exit (normal, cancelled, or failed) emits exactly one `ExtractionDiagnostics` record. It holds no state across separate `extract_frames()` calls; resume state is the caller's responsibility (research.md).
