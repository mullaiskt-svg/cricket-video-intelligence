# Feature Specification: Video Stitcher

**Feature Branch**: `009-video-stitcher`

**Created**: 2026-07-29

**Status**: Draft

**Input**: User description: "Implement Video Stitcher (Module 9): given the ordered ClipPlan produced by Module 8 (Clip Generator) -- a sequence of PlannedClips, each with clip_start_seconds/clip_end_seconds, all sharing one source_video_path -- and a caller-specified output file path, extract each clip's time range from the source video and concatenate them, in order, into a single final MP4 highlight video. Use FFmpeg with a stream-copy strategy (no re-encoding, per config/default.yaml's output.avoid_reencode and specs/technical_plan.md's Module 9 section: 'Strategy: Copy codec (no re-encoding)'), preserving the source video's original resolution and codec. This is the final Phase 2 deliverable described in specs/technical_plan.md ('MP4 Output Highlight Video') and specs/cli.md's `generate` command ('Final MP4 highlight video' output) -- the actual watchable video downstream of everything built so far. This module performs no OCR, replay detection, scene detection, or Event Database querying of any kind (constitution Principle III; Phase 2 only stitches from an already-computed ClipPlan) -- it is a pure FFmpeg-invocation stage. It must fail fast with a specific reason if FFmpeg is unavailable, if the source video file is missing/unreadable, or if a stitch operation fails partway through, matching every prior module's fail-fast precedent."

**Revision note (2026-07-29)**: Refined after initial review to add explicit internal evidence/traceability (`StitchEvidence`), a documented stage-by-stage Processing Model (including a new, distinct Output Validation stage), source-clip/source-event traceability on the public `Stitch Result`, expanded diagnostics, clarified determinism guarantees, an explicit temporary-file lifecycle covering both success and failure paths, and an explicit Version 1 scope boundary -- all internal/diagnostic or clarifying additions that strengthen observability and robustness without changing the core architecture (see Processing Model, Key Entities, and Scope & Extensibility below).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Get a Single Playable Highlight Video (Priority: P1)

A user who has run `cvip generate` against a filtered set of match events, and now has a computed clip plan, gets back one finished MP4 file that plays start-to-finish, showing each planned clip's footage in order -- this is the tangible output the entire platform exists to produce.

**Why this priority**: Nothing built so far (Modules 1-8) produces anything a user can actually watch. This is the deliverable everything upstream has been building toward.

**Independent Test**: Feed a `ClipPlan` with several ordered, non-overlapping `PlannedClip`s (from a real or synthetic source video) and an output file path. Run Video Stitcher and confirm the output file exists, is a valid playable MP4, and its content is each planned clip's footage, in the plan's own order, with no clip skipped or duplicated.

**Acceptance Scenarios**:

1. **Given** a `ClipPlan` with three ordered `PlannedClip`s and a valid source video, **When** Video Stitcher runs, **Then** the output path contains one valid MP4 file whose playable content is the three clips' footage, in order.
2. **Given** a `ClipPlan` with a single `PlannedClip`, **When** Video Stitcher runs, **Then** the output file's duration equals that one clip's `clip_end_seconds - clip_start_seconds` (within the tolerance noted in Assumptions).
3. **Given** the same `ClipPlan` and output path from a prior successful run, **When** Video Stitcher runs again without an explicit overwrite request, **Then** it fails fast rather than silently overwriting the existing file (Edge Cases).

---

### User Story 2 - Highlight Video Retains Original Broadcast Quality (Priority: P2)

A user watching their generated highlight reel sees the same picture and audio quality as the original broadcast -- no visible re-encoding artifacts, no resolution downgrade, no unexpected re-compression -- because the platform never re-encodes footage it doesn't have to.

**Why this priority**: Directly implements `config/default.yaml`'s `output.avoid_reencode` setting and `specs/technical_plan.md`'s explicit "Strategy: Copy codec (no re-encoding)" decision for this module. It's a quality guarantee, not a blocking correctness concern -- User Story 1's core value (a playable video) still holds even if this weren't true, but the platform's whole value proposition of fast, high-fidelity highlight generation depends on it.

**Independent Test**: Stitch a `ClipPlan` against a source video with known resolution/frame rate/codec. Inspect the output file's own stream parameters and confirm they exactly match the source's, with no transcoding step in between.

**Acceptance Scenarios**:

1. **Given** a source video at a known resolution, frame rate, and codec, **When** Video Stitcher produces the output file, **Then** the output's resolution, frame rate, and codec exactly match the source's.
2. **Given** the same inputs, **When** Video Stitcher runs, **Then** no re-encoding step occurs (verified by the underlying FFmpeg invocation using a stream-copy strategy, not a transcode).

---

### User Story 3 - Fail Clearly Instead of Producing a Broken Video (Priority: P3)

A user whose FFmpeg installation is missing, whose source video has moved or become unreadable, whose stitch operation fails partway through, or whose FFmpeg process reports success without actually producing a usable file gets a clear, specific error message -- never a silently truncated, corrupted, missing, or zero-byte "highlight video" that looks like it worked.

**Why this priority**: An operational-reliability concern rather than a blocking one for the happy path (User Story 1), but critical for trust -- a broken output file that looks superficially valid is worse than an outright failure, since a user might not notice until they try to watch it.

**Independent Test**: Force each failure condition in turn (FFmpeg unavailable, source video missing, empty clip plan, a simulated mid-stitch failure, a simulated post-completion invalid-output case) and confirm each yields a specific, distinguishable failure reason with no partial or misleading file left at the output path.

**Acceptance Scenarios**:

1. **Given** FFmpeg is not available on the system, **When** Video Stitcher runs, **Then** it fails fast with a specific reason identifying the missing dependency, and no output file is created.
2. **Given** the source video file referenced by the `ClipPlan` is missing or unreadable, **When** Video Stitcher runs, **Then** it fails fast with a specific reason, and no output file is created.
3. **Given** a `ClipPlan` with zero clips, **When** Video Stitcher runs, **Then** it fails fast with a specific reason rather than producing an empty or zero-duration output file.
4. **Given** a stitch operation that fails partway through (e.g., a mid-run extraction error), **When** Video Stitcher runs, **Then** it fails fast with a specific reason, and any partial/temporary output artifact is removed rather than left at the caller-specified output path.
5. **Given** the underlying FFmpeg process reports a successful exit but the resulting output file is missing, empty, or fails to open, **When** Video Stitcher's Output Validation stage runs, **Then** it treats this as a stitch failure -- not a success -- fails fast with a specific reason, and removes the invalid output file.

---

### Edge Cases

- The caller-specified output path already has a file at it -- Video Stitcher fails fast rather than silently overwriting it (Acceptance Scenario US1-3).
- The `ClipPlan` contains zero clips (a valid, non-error outcome from Module 8, per its own FR-012) -- Video Stitcher treats this as its own failure case, since a zero-clip "highlight video" isn't a meaningful deliverable (Acceptance Scenario US3-3).
- A single-clip `ClipPlan` -- still a valid stitch, output duration equals that one clip's span (Acceptance Scenario US1-2).
- The source video referenced by every `PlannedClip.source_video_path` no longer exists at generation time (moved, deleted, or the path was only ever synthetic/test data) -- fails fast with a specific reason (Acceptance Scenario US3-2).
- FFmpeg is installed but a specific stitch/concatenation invocation fails partway through (e.g., an unexpected mid-file decode error on the source) -- fails fast, cleans up any partial output (Acceptance Scenario US3-4).
- FFmpeg exits successfully but the produced file is missing, zero-byte, or otherwise fails to open -- Output Validation catches this before success is ever reported, treating it as a stitch failure like any other (Acceptance Scenario US3-5).
- A `PlannedClip`'s time range extends beyond the source video's actual duration (shouldn't happen if Module 8's boundary clamping ran correctly against an accurate `video_duration_seconds`, but this module doesn't re-validate that upstream guarantee) -- out of scope for this module to detect independently; see Assumptions.
- Because this module uses stream-copy (no re-encode), an individual clip's actual extracted start may snap to the nearest preceding keyframe rather than the exact `clip_start_seconds` -- not treated as a failure, but a documented, inherent limitation (Assumptions).

## Requirements *(mandatory)*

### Processing Model

Video Stitcher processes one `ClipPlan` through a fixed stage order, each stage's output feeding the next (mirroring the architectural clarity established by Event Detection's and Clip Generator's own Processing Models, `specs/007-event-detection/spec.md`, `specs/008-clip-generator/spec.md`):

1. **ClipPlan Input** -- the caller-supplied `ClipPlan` and output file path (FR-001).
2. **Validation** -- structural/precondition checks: the `ClipPlan` is non-empty, no file already exists at the output path, FFmpeg is available, and the source video is readable (FR-006 through FR-009).
3. **FFmpeg Segment Extraction** -- extract each `PlannedClip`'s `[clip_start_seconds, clip_end_seconds]` range from the source video into a temporary segment file via stream-copy (FR-002, FR-003).
4. **Concatenation** -- concatenate the extracted segments, in the `ClipPlan`'s own order, into the final output file (FR-002).
5. **Output Validation** -- before reporting success, verify the produced output file exists, is non-empty, and its container opens successfully; a failure at this stage is treated exactly like a Stage 3/4 failure (FR-010, FR-011).
6. **Stitch Result** -- the fully-assembled result (source-clip/source-event traceability, FR-017), diagnostics emitted (FR-016), and temporary artifacts cleaned up (FR-015).

A failure at any stage short-circuits the remaining stages and routes through the same fail-fast, cleanup-then-report path (FR-010) -- there is only one failure path in this pipeline, not one per stage.

### Functional Requirements

- **FR-001** (Stage: ClipPlan Input): System MUST accept, as input, an ordered `ClipPlan` (Module 8's output -- a sequence of `PlannedClip`s, each carrying `clip_start_seconds`, `clip_end_seconds`, a `clip_id`, `source_event_ids`, and a shared `source_video_path`) and a caller-specified output file path.
- **FR-002** (Stages: FFmpeg Segment Extraction, Concatenation): System MUST extract each `PlannedClip`'s `[clip_start_seconds, clip_end_seconds]` time range from the source video and concatenate all extracted ranges, in the `ClipPlan`'s own order, into one continuous output video.
- **FR-003** (Stage: FFmpeg Segment Extraction): System MUST use a stream-copy (no re-encode) extraction and concatenation strategy, per `config/default.yaml`'s `output.avoid_reencode` and `specs/technical_plan.md`'s Module 9 "Strategy: Copy codec (no re-encoding)" decision -- video and audio streams MUST NOT be re-encoded at any point.
- **FR-004**: The output file's resolution, frame rate, and codec MUST exactly match the source video's own (Acceptance Scenario US2-1) -- the output MUST NOT be down-sampled, transcoded, or otherwise altered from the source's own encoding.
- **FR-005**: System MUST produce the final output as a single MP4 container file at the caller-specified output path (`config/default.yaml`'s `output.container`, currently `mp4`).
- **FR-006** (Stage: Validation): If the `ClipPlan` contains zero clips, System MUST fail fast with a specific, distinguishable failure reason -- MUST NOT silently produce an empty or zero-duration output file (Edge Cases, Acceptance Scenario US3-3).
- **FR-007** (Stage: Validation): If a file already exists at the caller-specified output path, System MUST fail fast with a specific, distinguishable failure reason rather than silently overwriting it (Edge Cases, Acceptance Scenario US1-3).
- **FR-008** (Stage: Validation): System MUST fail fast with a specific, distinguishable failure reason if FFmpeg is not available on the system, matching `cvip doctor`'s own dependency check (`docs/DEPENDENCIES.md`) (Acceptance Scenario US3-1).
- **FR-009** (Stage: Validation): System MUST fail fast with a specific, distinguishable failure reason if the source video file referenced by the `ClipPlan` is missing or unreadable at generation time (Acceptance Scenario US3-2).
- **FR-010** (Stages: FFmpeg Segment Extraction, Concatenation, Output Validation): System MUST fail fast with a specific, distinguishable failure reason if any individual clip extraction, the final concatenation step, or Output Validation (FR-011) fails, and MUST clean up (remove) any partial or temporary output artifact rather than leaving it at the caller-specified output path (Acceptance Scenarios US3-4, US3-5).
- **FR-011** (Stage: Output Validation): After the Concatenation stage reports success, System MUST verify, before reporting success to the caller: the output file exists at the caller-specified path; the output file is non-empty; and the output file's container can be opened/read successfully (e.g., via a lightweight probe). Any of these checks failing MUST be treated as a stitch failure under FR-010 -- System MUST NOT report success for an output it has not independently verified (Acceptance Scenario US3-5, Edge Cases).
- **FR-012**: System MUST NOT perform OCR, replay detection, scene detection, or any Event Database query of any kind -- it operates purely on the already-computed `ClipPlan` and the source video file (constitution Principle III; PRD Section 6 Phase 2 restriction).
- **FR-013**: System MUST NOT re-run or re-invoke Clip Generator, Event Detection, or any earlier pipeline module -- its only inputs are the `ClipPlan` and the output path (FR-001).
- **FR-014**: System's deterministic-output guarantee applies specifically to: (a) clip ordering in the output -- the same `ClipPlan` always produces clips in the same order; (b) output stream parameters -- resolution, frame rate, and codec always identical to the source's own (FR-004); and (c) output duration -- identical within the keyframe-snapping tolerance (Assumptions) across repeated runs against the same input. Byte-for-byte identical output *files* are explicitly **not** guaranteed, since container-level metadata (e.g., creation timestamps, muxer version strings) may legitimately differ between otherwise-identical runs even under stream-copy (Success Criteria SC-006).
- **FR-015**: System MUST remove all temporary extraction/concatenation artifacts (Stage 3/4's intermediate segment files) after a run completes, whether it succeeds or fails -- FR-010 already covers the failure path; this extends the same no-accumulation guarantee to successful runs, so temporary artifacts never accumulate on the filesystem across repeated use (a future debug-retention override is plausible future scope, not part of this module's v1 contract -- see Assumptions).
- **FR-016**: System MUST emit exactly one diagnostics record per invocation (the platform's shared `ExecutionDiagnostics` shape, `src/cvip/common/diagnostics.py`), regardless of whether the run completes normally or fails, matching every prior pipeline module's own precedent. Its `output_summary` MUST include, at minimum: `clips_stitched`, `total_requested_duration_seconds` (the sum of every `PlannedClip`'s own span), `actual_output_duration_seconds`, `ffmpeg_execution_seconds`, `temp_files_created`, `temp_files_removed`, and `config_version`. Execution/processing duration is already covered by the standard `ExecutionDiagnostics` shape and need not be duplicated in `output_summary` (matching Event Detection's and Clip Generator's own precedent).
- **FR-017** (Stage: Stitch Result): The public `Stitch Result` MUST carry `source_clip_ids` (every stitched `PlannedClip`'s `clip_id`, in stitched order) and `source_event_ids` (the deduplicated union of every stitched clip's own `source_event_ids`, when available through the `ClipPlan`) in addition to the output path, total stitched duration, and clip count -- preserving the relationship between the final video and the events/clips that produced it.
- **FR-018**: System MUST preserve, internally, one `StitchEvidence` record per run (Key Entities) -- not part of the public `Stitch Result`, but preserved for diagnostics/explainability/future operational support, matching Event Detection's `EventEvidence` and Clip Generator's `ClipEvidence` precedent.
- **FR-019**: System MUST NOT populate or modify any database row directly -- its result (`Stitch Result`, FR-017) is returned to the caller, not written to the database; matching every prior module's own precedent of returning results rather than writing to the database itself.

### Key Entities

- **Stitch Request**: The input to one Video Stitcher run -- the `ClipPlan` to stitch (Module 8's output) and the caller-specified output file path.
- **Stitch Result**: The output of one successful Video Stitcher run -- the confirmed output file path, the total stitched duration, the number of clips stitched, `source_clip_ids`, and `source_event_ids` (FR-017).
- **StitchEvidence**: An internal record of how the final output video was produced (FR-018) -- not part of the public `Stitch Result`, preserved for diagnostics/explainability/future operational support, matching Event Detection's `EventEvidence` and Clip Generator's `ClipEvidence` precedent. One record per run, capturing: `source_clip_ids` and `source_event_ids` (same values as `Stitch Result`, retained here alongside their derivation context); the FFmpeg command/invocation details for each segment extraction and the final concatenation step; the extracted temporary segment file paths; the concatenation order; the cleanup actions performed (which temporary artifacts were removed, and when -- success or failure path); and the stream-copy parameters (resolution/frame rate/codec) carried through unchanged from the source, recorded as evidence of FR-004's guarantee.
- **Video Stitching Failure Reason**: The run-level failure taxonomy for this feature -- covers a missing FFmpeg installation, a missing/unreadable source video, an empty `ClipPlan`, an output path that already has a file at it, and a mid-stitch operation failure (including a post-completion Output Validation failure, FR-011).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Every successfully generated highlight video plays back start-to-finish without corruption or playback errors, verified against a representative `ClipPlan` for each of: a single clip, several ordered non-overlapping clips, and a plan containing a merged (multi-event) clip from Module 8.
- **SC-002**: The generated output's resolution, frame rate, and codec exactly match the source video's own, with zero re-encoding detected, across every generated highlight video.
- **SC-003**: Total output duration equals the sum of each `PlannedClip`'s `(clip_end_seconds - clip_start_seconds)`, within the keyframe-snapping tolerance noted in Assumptions -- never missing or duplicating a planned segment.
- **SC-004**: A missing FFmpeg installation, a missing source video, an empty `ClipPlan`, and an output-path collision each produce a specific, distinguishable failure reason with zero partial or misleading output file left behind, verified across all four cases.
- **SC-005**: Stitching a representative full-match highlight `ClipPlan` (on the order of a few dozen clips) completes well within the platform's under-2-minute `generate` budget (`specs/technical_plan.md` Performance Targets), since stream-copy avoids the cost of re-encoding.
- **SC-006**: Running the same `ClipPlan` through Video Stitcher twice (against a fresh output path each time) produces two output files with identical duration and identical stream parameters (resolution, frame rate, codec) -- per FR-014, without requiring byte-for-byte file identity.
- **SC-007**: No `Stitch Result` is ever reported for an output file that fails Output Validation (FR-011) -- verified by constructing a scenario where the underlying FFmpeg process reports a successful exit but produces a missing, empty, or unopenable file, and confirming Video Stitcher still reports a stitch failure, not success.
- **SC-008**: Zero temporary extraction/concatenation artifacts remain on the filesystem after any run completes, whether it succeeds or fails -- verified across both outcomes via the internal `StitchEvidence` trail's cleanup-actions record (FR-015, FR-018).

## Scope & Extensibility

This specification defines **Version 1** scope: Video Stitcher stitches clips from **exactly one source video per run**. This follows directly from Module 8's own contract (`specs/008-clip-generator/contracts/clip_generator_contract.md`), which guarantees every `PlannedClip` in a `ClipPlan` shares one `source_video_path` -- this module's Processing Model (Stage 1: ClipPlan Input) is scoped accordingly, and every downstream stage assumes a single source. **Multi-source highlight compilation** -- combining clips from more than one analyzed match or source file into a single output video -- is intentionally deferred to a future enhancement; it would require a distinct amendment to this contract (a new input shape, likely a per-source-video grouping of clips), not an incremental change to the current one. This is not a permanent ceiling on the architecture, only the current v1 boundary.

## Assumptions

- **Stream-copy extraction snaps to the nearest keyframe, not the exact requested timestamp**: because this module never re-encodes (FR-003), each clip's actual extracted start may fall on the nearest preceding keyframe in the source video's own GOP structure, rather than exactly `clip_start_seconds`. This is an inherent trade-off of avoiding re-encoding, matching `specs/technical_plan.md`'s explicit "Strategy: Copy codec (no re-encoding)" choice over frame-accurate re-encoding, and is the reason SC-003 and FR-014 both allow a bounded tolerance rather than requiring exact-second precision.
- **Output path's parent directory must already exist**: this module does not create directories on the caller's behalf -- matching every prior module's "clean input/output contract" boundary, directory creation (if desired) is the Pipeline Orchestrator's or CLI's responsibility.
- **No progress reporting in v1**: unlike the multi-hour `analyze` phase (where Frame Extraction Service reports progress), this module is expected to complete well within the platform's under-2-minute `generate` budget (SC-005) since stream-copy avoids re-encoding cost -- progress reporting is not warranted at this scale and is not part of this module's v1 scope.
- **No `--force`/overwrite flag in v1**: FR-007 makes an existing file at the output path a hard failure with no override; a future CLI-level `--force` flag (mirroring `cvip analyze --force`) is plausible future scope but is not part of this module's v1 contract.
- **No temporary-artifact debug-retention flag in v1**: FR-015 requires temporary artifacts to be removed after every run, success or failure; a future flag to intentionally retain them for debugging (mirroring `cvip analyze --debug-crops`) is plausible future scope but is not part of this module's v1 contract.
- **This module does not independently re-validate that every `PlannedClip`'s time range falls within the source video's actual duration** -- it trusts Module 8's own boundary-clamping guarantee (its FR-003, against an accurate `video_duration_seconds` supplied by the caller); a stale or inaccurate `video_duration_seconds` upstream is an existing-module concern, not something this module re-checks.
