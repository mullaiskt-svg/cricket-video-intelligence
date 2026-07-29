# Contract: Video Stitcher

This module exposes one entry point to the rest of the CVIP pipeline. It is an internal Python library contract (no network/CLI surface), consistent with constitution Principle V (clear input/output contract, independently testable).

## `stitch_video(request: StitchRequest) -> VideoStitcherRunner`

**Input**: a `StitchRequest` (see [data-model.md](../data-model.md)), wrapping Module 8's `ClipPlan` and a caller-specified output file path. This call never queries the Event Database, applies filtering, re-invokes Clip Generator or any earlier module, performs OCR/replay/scene detection, or touches anything beyond the source video referenced by the `ClipPlan` and the output path itself (FR-011, FR-012, FR-013).

**Output**: a `VideoStitcherRunner` -- a context-manager object exposing `.run() -> StitchResult` (which performs the full six-stage Processing Model pass, spec.md, and returns the result).

**Preconditions**: All validated lazily inside `.run()`, in this order -- the `ClipPlan` is present and non-empty (`EMPTY_CLIP_PLAN`, FR-006); no file already exists at `output_path` (`OUTPUT_ALREADY_EXISTS`, FR-007); `ffmpeg` is resolvable on the system (`MISSING_FFMPEG`, FR-008); the source video referenced by the `ClipPlan` exists and is readable (`SOURCE_VIDEO_UNAVAILABLE`, FR-009). On the first violation encountered, `.run()` immediately raises `VideoStitchingError` with the matching reason (see Error taxonomy) and still emits exactly one diagnostics record -- no FFmpeg process is spawned for any of these rejection cases.

**Usage**:
```
with stitch_video(request) as runner:
    result = runner.run()
# on exit (normal or exception): exactly one
# VideoStitchingDiagnostics record emitted, and all temporary
# artifacts removed regardless of outcome (FR-015)
```

**Postconditions**:
- Every clip in `request.clip_plan.clips` is extracted from the source video and concatenated, in the `ClipPlan`'s own order, into one continuous output file (FR-002).
- Extraction and concatenation use stream-copy only -- no video or audio stream is ever re-encoded (FR-003), and the output's resolution, frame rate, and codec exactly match the source's own (FR-004).
- The output is a single MP4 container file at `request.output_path` (FR-005).
- Before `.run()` returns a `StitchResult`, the output file has been independently verified to exist, be non-empty, and have an openable container with a readable duration (FR-011) -- a `.run()` call that returns normally is *never* returning an unverified result.
- `result.source_clip_ids` and `result.source_event_ids` trace the output back to the `PlannedClip`s and events that produced it (FR-017).
- Every temporary extraction/concatenation artifact created during the run is removed before `.run()`'s enclosing `with` block exits, whether the run succeeded or failed (FR-015) -- verifiable via the internal `StitchEvidence.cleanup_actions` (FR-018).
- Regardless of how the run ends (completed normally or failed at any stage), exactly one `VideoStitchingDiagnostics` record is emitted (FR-016).
- No network calls are made under any circumstance, no GPU is required or used (FR-011's Constitution Principle I/II framing).
- This feature never accesses or is aware of the DB `events`/`matches` tables -- it produces a `StitchResult` and a file on disk only; persistence of any kind remains the Pipeline Orchestrator's responsibility (FR-019).

## Error taxonomy (`VideoStitchingFailureReason` values)

| Value | Meaning | Example trigger |
|---|---|---|
| `EMPTY_CLIP_PLAN` (FR-006) | `request.clip_plan.clips` is empty | Caller passes a `ClipPlan` where every event was replay-excluded upstream |
| `OUTPUT_ALREADY_EXISTS` (FR-007) | A file already exists at `request.output_path` | Re-running `generate` against the same output path without deleting the prior result |
| `MISSING_FFMPEG` (FR-008) | `ffmpeg` is not resolvable on the system | `ffmpeg` not installed or not on `PATH` (`docs/DEPENDENCIES.md`) |
| `SOURCE_VIDEO_UNAVAILABLE` (FR-009) | The source video is missing or unreadable at generation time | The analyzed match file was moved or deleted after `cvip analyze` ran |
| `STITCH_OPERATION_FAILED` (FR-010, FR-011) | A segment extraction, the concatenation step, or Output Validation failed | A corrupt mid-file region causes `ffmpeg` to exit non-zero during extraction; or `ffmpeg` exits 0 but the resulting file is empty/unopenable |

`StitchEvidence` (see [data-model.md](../data-model.md)) is a separate, internal per-run record -- it never causes a run to fail; it only explains how the output (or the failed attempt) was produced.

## Consumer obligation

The Pipeline Orchestrator MUST obtain the stitched result via `stitch_video()` and treat `result.output_path` as the final deliverable -- it MUST NOT re-run or second-guess the stitch (e.g., by independently re-probing the output "just in case"), since FR-011's Output Validation has already done so before `.run()` ever returns. A consumer MAY treat `StitchEvidence` as an internal record with no stable public contract -- no consumer contract depends on it being exposed. A consumer that wishes to persist stitch metadata (e.g., linking a generated highlight file back to the `events` rows it came from) MAY use `result.source_event_ids`/`result.source_clip_ids` for that purpose.
