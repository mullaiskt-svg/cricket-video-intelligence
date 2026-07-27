# Feature Specification: Video Loader

**Feature Branch**: `001-video-loader`

**Created**: 2026-07-27

**Status**: Draft

**Input**: User description: "Video Loader module: load a cricket match video file (MP4/MKV, 3-4 hours, 720p/1080p, no audio), read and expose its metadata (FPS, resolution, duration, codec), and validate the file is readable before any downstream processing (scene detection, OCR, event detection) begins. Must run entirely offline, CPU-only, on the target hardware (Intel Core i3-1115G4, 8GB RAM). Should fail fast with a clear error if the video can't be opened or metadata can't be read, rather than passing bad state downstream."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Load a valid match video and confirm it's ready for analysis (Priority: P1)

An analyst points the platform at a recorded cricket match file. The system opens the file, reads its metadata (duration, resolution, frame rate, codec), and confirms the video is valid and ready before any analysis work starts.

**Why this priority**: This is the entry point for the entire pipeline (per the constitution's Single-Pass Analysis Principle). No scene detection, replay detection, OCR, or event detection can begin until a video has been loaded and confirmed valid. Without this, nothing else in the product works.

**Independent Test**: Can be fully tested by pointing the system at a known-good 3-4 hour MP4 or MKV match recording and confirming it reports correct duration, resolution, frame rate, and codec, with no analysis modules invoked.

**Acceptance Scenarios**:

1. **Given** a valid MP4 match recording on local disk, **When** the analyst loads it, **Then** the system reports its duration, resolution, frame rate, and codec accurately and marks it ready for analysis.
2. **Given** a valid MKV match recording on local disk, **When** the analyst loads it, **Then** the system reports the same metadata fields accurately and marks it ready for analysis.
3. **Given** a valid match recording of typical broadcast length (3-4 hours), **When** the analyst loads it, **Then** metadata is available well before enough time has passed to matter to the analyst (see SC-001), without reading through the entire video.

---

### User Story 2 - Reject an unreadable or corrupted video immediately (Priority: P2)

An analyst attempts to load a file that is corrupted, truncated, in an unsupported format, or otherwise cannot be decoded. The system stops immediately and reports a specific, understandable reason, instead of allowing the pipeline to continue with bad or missing data.

**Why this priority**: This directly implements the constitution's Fail Fast, Never Silently principle. Letting a bad video pass through would waste the single analysis pass and could produce corrupted or misleading downstream results (scene lists, OCR readings, events) that are expensive to detect and re-run.

**Independent Test**: Can be fully tested by attempting to load a deliberately corrupted file, a zero-byte file, a file in an unsupported container format, and a nonexistent file path, and confirming each produces a distinct, specific error with no downstream module invoked.

**Acceptance Scenarios**:

1. **Given** a corrupted or truncated video file, **When** the analyst attempts to load it, **Then** the system rejects it with an error identifying that the file could not be decoded, and no further processing occurs.
2. **Given** a file path that does not exist, **When** the analyst attempts to load it, **Then** the system rejects it with an error identifying that the file was not found.
3. **Given** a file in an unsupported container format, **When** the analyst attempts to load it, **Then** the system rejects it with an error identifying that the format is unsupported.
4. **Given** any rejected file, **When** the rejection occurs, **Then** the event is logged with enough detail to diagnose the cause without re-running the load attempt.
5. **Given** a video file that is locked or otherwise inaccessible because another process holds it open, **When** the analyst attempts to load it, **Then** the system rejects it with an error identifying that the file is locked/inaccessible, distinct from a missing-file or corrupted-file error.

---

### User Story 3 - Confirm the platform works fully offline on target hardware (Priority: P3)

An analyst runs the video loading step on the target offline machine (no network access, CPU-only, 8GB RAM class hardware) and confirms it works without requiring any network access or specialized hardware.

**Why this priority**: This validates the constitution's Offline-First and Performance principles at the earliest possible point in the pipeline, before investment goes into later modules that depend on this one. It's lower priority than P1/P2 because it's a property to verify rather than new behavior to build.

**Independent Test**: Can be fully tested by disconnecting the machine from the network, running the load step against a valid match file on the target-class hardware, and confirming it completes successfully using only local resources.

**Acceptance Scenarios**:

1. **Given** no network connectivity, **When** the analyst loads a valid match video, **Then** the system completes the load and metadata read successfully with no network calls attempted.
2. **Given** target-class hardware (CPU-only, 8GB RAM), **When** the analyst loads a valid match video, **Then** the load completes without requiring GPU acceleration and within the resource budget described in Success Criteria.

### Edge Cases

- What happens when the video file exists but is still being copied/written to disk (partial file)? — Resolved as a `CORRUPTED_OR_UNDECODABLE` rejection (FR-004): a partial file will either fail to open cleanly or fail the first-frame decode check, both of which map to this reason.
- Resolved: when the video's container reports metadata that conflicts with its actual decoded content (e.g., header says 1080p but frames decode at a different resolution), the decoded frame's actual properties are authoritative — see FR-012.
- What happens when a video unexpectedly contains an audio track, even though inputs are not expected to have one? — Resolved: see Assumptions (audio presence does not invalidate a file).
- What happens when the video resolution is outside the expected 720p/1080p range (e.g., 480p or 4K)? — Resolved: see Assumptions (loaded and reported like any other resolution).
- What happens when the video is much shorter than a typical match (e.g., a few seconds) or longer than 4 hours? — Resolved: see FR-008 (durations from short clips up to at least 4 hours are supported).
- Resolved: when the file is locked or in use by another process and can't be opened for reading, the system rejects it distinctly from a missing or corrupted file — see FR-004, FR-005, and Acceptance Scenario 5 under User Story 2.
- What happens when the analyst provides a path to a directory instead of a file, or to a non-video file with a video-like extension? — Resolved: see Assumptions (container format is determined by file extension; a directory is treated the same as a missing file, and a non-video file with a matching extension passes the format check but fails decoding).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST accept cricket match video files in MP4 and MKV containers as input.
- **FR-002**: System MUST read and expose, for any accepted video, its duration, frame rate, resolution (width x height), frame count, and codec.
- **FR-003**: System MUST validate that a video file can actually be opened and decoded before it is marked ready for downstream analysis.
- **FR-004**: System MUST reject, immediately and without partial processing, any file that cannot be opened (including because it is locked or otherwise inaccessible to the process), cannot be decoded, does not exist, or is not a supported container format.
- **FR-005**: System MUST report a specific, human-readable reason for every rejection (e.g., file not found, unsupported format, corrupted/undecodable content, locked/inaccessible) rather than a generic failure.
- **FR-006**: System MUST NOT allow scene detection, replay detection, OCR, or event detection to begin for a video that has not been successfully loaded and validated. (Verification that consumer modules honor this is deferred until the first such module exists — see Assumptions.)
- **FR-007**: System MUST log the outcome of every load attempt (success with metadata, or failure with reason).
- **FR-008**: System MUST support match recordings ranging from short test clips up to at least 4 hours in duration.
- **FR-009**: System MUST perform loading and metadata extraction using only local resources, with no network or cloud calls.
- **FR-010**: System MUST perform loading and metadata extraction using CPU only, with no dependency on GPU hardware.
- **FR-011**: System MUST extract metadata without requiring a full read/decode of the entire video's content, so that loading a multi-hour match does not itself consume a large share of the overall processing time budget.
- **FR-012**: When a video's container header metadata conflicts with the properties of its actually decoded frames (e.g., header resolution differs from decoded frame dimensions), the system MUST treat the decoded frame's properties as authoritative and report those, not the header's claim.
- **FR-013**: System MUST emit a standardized execution diagnostics record for every load attempt (success or failure), containing at minimum: module name, start time, end time, execution duration, peak memory usage, a summary of the input, a summary of the output (or failure reason), and any warnings — as structured, machine-parseable log output. This is the Video Loader's implementation of the project-wide Module Observability & Diagnostics standard (see `specs/technical_plan.md`).
- **FR-014**: System MUST compute and expose a content hash of the video file on successful load, so that a later attempt to analyze the same file can be recognized as such (in support of constitution Principle III, Single-Pass Analysis) without needing to compare full file contents. Computing the hash MUST NOT require reading the entire file when doing so would meaningfully risk the SC-001 time budget (see Assumptions for the sampling approach used).

### Key Entities

- **Match Video Source**: The cricket broadcast recording being analyzed. Key attributes: file location, duration, resolution, frame rate, codec, and container format.
- **Load Result**: The outcome of a single load attempt against a Match Video Source. Key attributes: success/failure status, extracted metadata (when successful), failure reason (when unsuccessful), and timestamp. Downstream modules (scene detection, replay detection, OCR, event detection) depend on a successful Load Result before they may run.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For a 3-4 hour match recording, metadata (duration, resolution, frame rate, codec) is available within 10 seconds of starting the load.
- **SC-002**: 100% of corrupted, missing, or unsupported-format files are rejected with a specific, actionable reason rather than being passed to downstream analysis.
- **SC-003**: 0% of loaded-but-invalid videos reach scene detection, replay detection, OCR, or event detection — every downstream module only ever receives a video that has already passed validation.
- **SC-004**: The load and metadata-read step completes using local, offline resources on target-class hardware (CPU-only, 8GB RAM class machine) in 100% of test runs, with no network access attempted.
- **SC-005**: Loading and validating a video consumes a small, fixed share of the overall 6GB memory budget (no more than 200MB), regardless of the video's duration.
- **SC-006**: Every load attempt (success or failure) produces a structured diagnostics record (module name, timing, peak memory, input/output summary) usable for cross-module performance reporting, without requiring a separate instrumentation pass.

## Assumptions

- Match videos are already fully saved to local disk before loading begins; the system is not required to handle live-streamed or actively-being-recorded input.
- A single video file represents one complete, continuous match session for this feature; splitting or merging multi-file matches (e.g., separate innings recordings) is out of scope for v1.
- Videos are not expected to contain audio, but the presence of an audio track does not by itself make a file invalid — audio is simply not used by any downstream module.
- Resolutions outside 720p/1080p (e.g., 480p, 4K) are loaded and reported like any other resolution rather than rejected outright; downstream modules are responsible for deciding whether a given resolution is usable.
- Input files are not encrypted or DRM-protected.
- "Codec" refers to the video codec used to encode the file's picture data (e.g., H.264, H.265), not the audio codec.
- Container format (MP4 vs. MKV vs. unsupported) is determined by file extension as a fast, deterministic first check; a directory path is treated identically to a non-existent file (`FILE_NOT_FOUND`); a non-video file renamed to carry a supported extension passes this first check but fails the subsequent decode step (`CORRUPTED_OR_UNDECODABLE`).
- FR-006 and SC-003 (no invalid video reaches downstream modules) describe a contract this feature guarantees on its own output (`LoadResult`), but end-to-end verification that a consumer honors the contract is necessarily deferred until the first consumer module (Scene Detection) is implemented; that is tracked as follow-up work in that future feature, not in this one.
- The FR-014 content hash is computed from a fixed-size sample of the file (the first 1 MiB, the last 1 MiB, and the exact file size) rather than the full file content — a full hash of a multi-gigabyte, multi-hour recording risks the SC-001 10-second budget on typical disk speeds, while a sampled digest is sufficient to recognize "this is very likely the same file I already analyzed," which is the only use FR-014 requires.
