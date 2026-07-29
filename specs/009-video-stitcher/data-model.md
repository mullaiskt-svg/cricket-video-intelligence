# Data Model: Video Stitcher

Derived from the Key Entities section of [spec.md](./spec.md). This feature has no persistent storage of its own (plan.md Technical Context) — these are in-memory value objects; the Pipeline Orchestrator remains solely responsible for any database interaction (spec.md FR-019). This module's one genuine side effect is the output MP4 file itself, which is not a data-model entity but the actual deliverable at `StitchRequest.output_path`.

## StitchRequest

The input to one Video Stitcher run.

| Field | Type | Notes |
|---|---|---|
| `clip_plan` | `ClipPlan` (Module 8, `cvip.clips.models`) | Required. The already-computed, ordered clip plan (FR-001) — structurally, `clip_plan.clips` is a sequence of `PlannedClip`s, each exposing `clip_id`, `clip_start_seconds`, `clip_end_seconds`, `source_video_path`, `source_event_ids` (research.md treats this by structural shape, matching Clip Generator's own `DetectedEventLike` precedent, not a hard import requirement). |
| `output_path` | str | Required, non-empty. The caller-specified output file path (FR-001). Its parent directory must already exist (spec.md Assumptions) — this module does not create directories. |

**Validation rules** (enforced lazily inside `.run()`, before any FFmpeg process is spawned, mirroring every prior module's own lazy-validation precedent):
- `clip_plan` is present and, if its `.clips` is empty, rejected with `EMPTY_CLIP_PLAN` (FR-006) — not `INVALID_INPUT`, since an empty `ClipPlan` is itself a *valid* Module 8 output (Module 8's own FR-012); it is this module's specific business rule that a zero-clip stitch is meaningless, not a structural malformation.
- `output_path` is present and non-empty — otherwise rejected (folded into the general precondition-check taxonomy; see `VideoStitchingFailureReason`).
- A file already exists at `output_path` — rejected with `OUTPUT_ALREADY_EXISTS` (FR-007).
- `ffmpeg` is not resolvable via `shutil.which` — rejected with `MISSING_FFMPEG` (FR-008, research.md Decision 7).
- `clip_plan.clips[0].source_video_path` does not exist or is not readable — rejected with `SOURCE_VIDEO_UNAVAILABLE` (FR-009). Only the first clip's `source_video_path` needs checking, since Module 8's own contract guarantees every `PlannedClip` in one `ClipPlan` shares the same `source_video_path` (spec.md Scope & Extensibility).

## StitchResult

The public output of one successful Video Stitcher run (spec.md's "Stitch Result" entity, FR-017).

| Field | Type | Notes |
|---|---|---|
| `output_path` | str | The confirmed output file path — identical to `StitchRequest.output_path`, echoed back for caller convenience. |
| `total_duration_seconds` | float | The actual output video's duration, as measured by Output Validation's `ffprobe` call (research.md Decision 5) — not simply the sum of requested clip spans, though the two should closely agree (SC-003's tolerance). |
| `clip_count` | int | `len(clip_plan.clips)`. |
| `source_clip_ids` | tuple[str, ...] | Every stitched `PlannedClip`'s `clip_id`, in stitched (= `ClipPlan`) order (FR-017). |
| `source_event_ids` | tuple[str, ...] | The deduplicated union of every stitched clip's own `source_event_ids`, sorted for determinism (FR-017) — `()` if no contributing `PlannedClip` carries any (e.g., a hand-built `ClipPlan` in a test that doesn't set them). |

## StitchEvidence

An internal record of how the final output video was produced (spec.md's "StitchEvidence" entity, FR-018) — not part of the public `StitchResult`, preserved for diagnostics/explainability/future operational support, matching Event Detection's `EventEvidence` and Clip Generator's `ClipEvidence` precedent. One record per *run* (not per clip, research.md Decision 8), built incrementally across Stages 3-6 via `dataclasses.replace()` (the type is frozen).

| Field | Type | Notes |
|---|---|---|
| `source_clip_ids` | tuple[str, ...] | Same value as `StitchResult.source_clip_ids`, retained here alongside its derivation context. |
| `source_event_ids` | tuple[str, ...] | Same value as `StitchResult.source_event_ids`. |
| `ffmpeg_invocations` | tuple[`FfmpegInvocation`, ...] | One entry per segment extraction, plus one for the final concatenation, plus one for the Output Validation `ffprobe` call — in the order they were actually run. |
| `extracted_segment_paths` | tuple[str, ...] | The temporary segment file paths created in Stage 3, in `ClipPlan` order. |
| `concatenation_order` | tuple[str, ...] | The order `extracted_segment_paths` were listed in the concat demuxer's list file (research.md Decision 4) — expected to equal `extracted_segment_paths` itself, but recorded independently so a future reordering bug is directly observable in evidence rather than inferred. |
| `cleanup_actions` | tuple[`CleanupAction`, ...] | Which temporary artifacts were removed, and on which path (success or failure) — FR-015. |
| `stream_copy_parameters` | `StreamCopyParameters` | The resolution/frame rate/codec carried through unchanged from the source, recorded as evidence of FR-004's guarantee. |

### FfmpegInvocation (nested value object, part of `StitchEvidence`)

| Field | Type | Notes |
|---|---|---|
| `purpose` | str | One of `"extract_segment"`, `"concat"`, `"probe_output"` — which pipeline stage this invocation belongs to. |
| `command` | tuple[str, ...] | The exact argument list passed to `subprocess.run` (research.md Decision 2) — human-readable, directly reproducible from a log line. |
| `exit_code` | int | The process's exit code. |
| `duration_seconds` | float | Wall-clock time for this one invocation — summed across all entries to produce `ffmpeg_execution_seconds` in diagnostics (FR-016). |

### CleanupAction (nested value object, part of `StitchEvidence`)

| Field | Type | Notes |
|---|---|---|
| `path` | str | The temporary artifact removed (a segment file, the concat list file, or the containing temp directory itself). |
| `removed` | bool | Whether removal actually succeeded (`shutil.rmtree(..., ignore_errors=True)`, research.md Decision 6, means this could in principle be `False` on a locked-file edge case; recorded rather than silently assumed). |
| `trigger` | str | `"success"` or `"failure"` -- which of the two cleanup paths (FR-015) performed this removal. |

### StreamCopyParameters (nested value object, part of `StitchEvidence`)

| Field | Type | Notes |
|---|---|---|
| `resolution` | tuple[int, int] | Width, height -- read from the source video, expected identical on the output (FR-004). |
| `frame_rate` | float | Expected identical on the output (FR-004). |
| `codec` | str | Expected identical on the output (FR-004). |

## VideoStitchingFailureReason

The run-level failure taxonomy for this feature (spec.md's "Video Stitching Failure Reason" entity, Key Entities).

| Value | Meaning |
|---|---|
| `MISSING_FFMPEG` | `ffmpeg` is not resolvable on the system (FR-008). |
| `SOURCE_VIDEO_UNAVAILABLE` | The source video referenced by the `ClipPlan` is missing or unreadable (FR-009). |
| `EMPTY_CLIP_PLAN` | The `ClipPlan` contains zero clips (FR-006). |
| `OUTPUT_ALREADY_EXISTS` | A file already exists at the caller-specified output path (FR-007). |
| `STITCH_OPERATION_FAILED` | A segment extraction, the concatenation step, or Output Validation (FR-011) failed (FR-010) -- the one taxonomy value covering every Stage 3/4/5 failure, since all three route through the identical fail-fast-and-clean-up path (Processing Model). |

## VideoStitchingDiagnostics

Exactly one per Video Stitcher run (FR-016), including failed runs. Reuses the platform-wide `ExecutionDiagnostics` shape (`src/cvip/common/diagnostics.py`, research.md Decision 10) rather than defining a new one:

| `ExecutionDiagnostics` field | How this feature populates it |
|---|---|
| `module_name` | `"stitcher.stitcher"` |
| `input_summary` | `clip_plan`'s clip count, `output_path`, and the shared `source_video_path` |
| `output_summary` | `clips_stitched=`, `total_requested_duration_seconds=`, `actual_output_duration_seconds=`, `ffmpeg_execution_seconds=`, `temp_files_created=`, `temp_files_removed=`, `config_version=` (FR-016) |
| `warnings` | Reserved for future use -- no warning conditions are currently defined for this feature |
| `failure_reason` | A `VideoStitchingFailureReason` value, or `null` on a normal completion |
