# Feature Specification: Frame Extraction Service

**Feature Branch**: `002-frame-extraction-service`

**Created**: 2026-07-27

**Status**: Draft

**Input**: User description: "Frame Extraction Service: a shared platform abstraction for reading frames from a validated cricket match video, replacing direct OpenCV access across the pipeline. Takes a successful LoadResult from the Video Loader feature as input (never a raw file path). Must support: configurable sampling rate per caller (every frame, a fixed rate like 1 FPS, or a custom frame-index/timestamp list) rather than a hardcoded rate; every yielded frame carries its 0-based frame index in the original video and its timestamp in seconds from match start; streaming/generator-based iteration so the whole video is never held in memory at once (must fit the platform's <6GB memory budget even for a 3-4 hour match); deterministic output (same video + same sampling config always yields the identical sequence of frame index/timestamp pairs); progress reporting (frames processed vs total, or elapsed vs total duration) so a CLI progress bar or the pipeline orchestrator can show extraction progress during a multi-hour run; resume support, letting extraction start from an arbitrary frame index or timestamp instead of always from the beginning, so an interrupted multi-hour analysis run can resume without redoing already-processed frames; and standardized execution diagnostics (one structured record per extraction run, not per frame, reusing the project's existing shared diagnostics emitter). Downstream consumers of this service include Scene Detection, Replay Detection, Scoreboard OCR, and (in the future) Fielding Detection and other computer-vision modules -- none of them should open the video file directly. Must run fully offline, CPU-only, on the target hardware (Intel Core i3-1115G4, 8GB RAM), consistent with the rest of the platform."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Request frames from a validated video at a chosen rate (Priority: P1)

A pipeline module (e.g., Scoreboard OCR) needs to read frames from an already-validated match video, at whatever rate suits its own purpose, without implementing its own video-decoding logic. It requests frames from the service and receives each one tagged with its position in the original video and its timestamp.

**Why this priority**: This is the entire reason the service exists — one shared way to read frames, replacing every downstream module independently wrapping video-decoding logic. Without this, nothing else about the service (progress, resume, diagnostics) has anything to operate on.

**Independent Test**: Can be fully tested by requesting "every frame" and, separately, a fixed rate (e.g., 1 frame per second) from a known-good short validated video, and confirming the returned frames match the video's known content, each carrying the correct frame index and timestamp.

**Acceptance Scenarios**:

1. **Given** a successfully validated match video, **When** a caller requests frames at a fixed rate (e.g., 1 per second), **Then** the service yields frames at that rate, each with its correct 0-based frame index and timestamp in seconds from the start of the video.
2. **Given** a successfully validated match video, **When** a caller requests every frame, **Then** the service yields every frame in sequence, each correctly indexed and timestamped.
3. **Given** a successfully validated match video, **When** a caller requests frames at a specific list of frame indices, **Then** the service yields exactly those frames, in ascending order, regardless of the order the indices were supplied in.
4. **Given** a successfully validated match video, **When** a caller requests frames at a specific list of timestamps, **Then** the service yields, for each requested timestamp, the single decoded frame whose own timestamp is closest to it — never an interpolated blend of two frames, and never a synthesized frame that doesn't exist in the source video.
5. **Given** a video that has not been successfully validated (i.e., no successful `LoadResult`), **When** a caller attempts to request frames, **Then** the service refuses and does not attempt to read the file.

---

### User Story 2 - Extraction stays within the memory budget regardless of match length (Priority: P2)

An operator runs frame extraction against a full 3-4 hour match recording. Regardless of the match's length, the extraction process does not consume more than a small, bounded amount of memory — it never loads the whole video, or a large fraction of it, into memory at once.

**Why this priority**: This is a hard platform constraint (the constitution's <6GB overall memory budget), and it must hold for a full-length match before any real consumer module (Scene Detection, Scoreboard OCR) can be safely built on top of this service. It's P2 rather than P1 because it's a property of User Story 1's behavior under real-world scale, not a new capability.

**Independent Test**: Can be fully tested by measuring peak memory while extracting frames from a short video and comparing it to peak memory while extracting from a multi-hour video at the same rate — the two should be comparable, not scale with video length.

**Acceptance Scenarios**:

1. **Given** a 3-4 hour match video, **When** frames are extracted at any supported rate, **Then** peak memory attributable to the extraction stays at or under 150MB (SC-002), a budget that does not grow with the video's duration.
2. **Given** extraction is in progress, **When** the caller has not yet consumed a given frame, **Then** the service does not pre-decode and buffer large numbers of future frames in memory ahead of the caller.

---

### User Story 3 - Observe progress, cancel, and resume an interrupted extraction (Priority: P3)

An operator running a multi-hour `cvip analyze` watches extraction progress rather than waiting with no feedback, can stop it cleanly if needed, and if the process is interrupted partway through, a later attempt resumes from where it left off instead of redoing already-completed work.

**Why this priority**: Valuable for a resource-constrained, multi-hour offline workflow, and required for the platform's "resume interrupted processing" capability — but it's an operational-resilience layer on top of User Stories 1-2, not something an initial consumer module strictly needs on day one.

**Independent Test**: Can be fully tested by starting an extraction, observing reported progress partway through, requesting cancellation and confirming it stops cleanly, then starting a new extraction request with a specified resume point and confirming it picks up from that point rather than frame zero.

**Acceptance Scenarios**:

1. **Given** an extraction in progress, **When** the caller checks progress partway through, **Then** the service reports how much of the requested range has been processed (e.g., frames done vs. total, or elapsed vs. total duration).
2. **Given** a caller specifies a starting frame index partway through the video, **When** extraction begins, **Then** the service starts yielding frames from that index (inclusive) rather than from the beginning; frame indices before it are never yielded.
3. **Given** a caller specifies a resume point beyond the video's actual length, **When** extraction is requested, **Then** the service rejects the request with a specific, actionable reason rather than silently returning nothing or crashing.
4. **Given** a caller specifies both a frame index and a timestamp as the resume point in the same request, **When** extraction begins, **Then** the frame index is used and the timestamp is ignored, so the outcome is always deterministic rather than dependent on which value "wins."
5. **Given** an extraction in progress, **When** the caller requests cancellation, **Then** the service stops yielding further frames, releases any resources it holds, still emits its one diagnostics record summarizing the partial run, and leaves enough state that a later request can resume from the last frame actually delivered to the caller.

### Edge Cases

- What happens when the requested resume point (frame index or timestamp) is beyond the video's actual length? — Resolved: rejected immediately with a specific reason (FR-009), not silently truncated.
- What happens when both a frame index and a timestamp are supplied for the same resume request? — Resolved: frame index takes precedence, timestamp is ignored (FR-008, US3 Acceptance Scenario 4).
- Resuming exactly at the last frame the caller previously received — does that frame get yielded again? — Resolved: no. Resuming "from frame index N" means N is the first frame yielded going forward (inclusive); a caller that already received frame N should resume from N+1 to avoid reprocessing it.
- What happens when a custom frame-index or timestamp list contains out-of-range, unsorted, or duplicate values? — Resolved: the service sorts the list internally regardless of input order and de-duplicates repeated entries (each matching frame is yielded once); an out-of-range entry is skipped and recorded as a warning on that run's diagnostics record, rather than failing the entire request over one bad entry.
- What happens when the underlying video file becomes unavailable partway through an extraction (e.g., deleted, or a locked/inaccessible state, after Video Loader already validated it)? — Resolved: the extraction fails fast with a specific reason (FR-014), same as any other unrecoverable mid-run condition.
- What happens when a decodable frame turns out to be corrupted partway through an otherwise-good video? — Resolved: also covered by FR-014's fail-fast requirement; a single corrupted frame stops the extraction with a specific reason rather than silently skipping it or returning bad data.
- What happens when a requested fixed sampling rate is higher than the video's native frame rate? — Resolved: see Assumptions (native rate is a ceiling; every available frame is yielded, none are fabricated).
- What happens with a Variable Frame Rate (VFR) source video, where frames aren't evenly spaced in time? — Resolved: see Assumptions (timestamps come from the video's actual per-frame timing, not a constant-rate calculation, so VFR sources are handled without special-casing).
- What happens when the video's own frame-rate metadata is zero or otherwise invalid? — Resolved: cannot occur for a video this service accepts — Video Loader already rejects such files before producing a successful `LoadResult` (FR-001, FR-002).
- What happens when two callers request extraction from the same validated video at the same time (e.g., Scene Detection and Scoreboard OCR running concurrently)? — Resolved: see Assumptions (each request is independent for this feature's scope; true shared-decode concurrency is a planning-level optimization, not a behavioral requirement here).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST accept a successful `LoadResult` (from the Video Loader feature) as its input and MUST NOT accept a raw file path directly, nor attempt its own file validation.
- **FR-002**: System MUST NOT yield any frames for a `LoadResult` that does not indicate a successful, validated video.
- **FR-003**: System MUST allow the caller to choose exactly one of four sampling modes per request: (a) every frame, (b) a fixed rate (e.g., frames per second), (c) an explicit list of frame indices, or (d) an explicit list of timestamps. These four modes are the complete, canonical set for this feature — not an open-ended or freeform configuration space.
  - For mode (c) and (d), the service MUST treat the supplied list as a set regardless of input order: it MUST sort it internally, MUST de-duplicate repeated entries so each matching frame is yielded only once, and MUST skip (rather than fail the whole request over) any out-of-range entry, recording each skip as a warning on that run's diagnostics record.
  - For mode (d) specifically, the service MUST yield the single decoded frame whose timestamp is closest to each requested timestamp. It MUST NOT interpolate between two frames and MUST NOT synthesize a frame that does not exist in the source video.
- **FR-004**: System MUST provide, for every yielded frame, a single stable payload containing: an identifier for the source video, the frame's 0-based index in the original video, its timestamp, and the decoded frame data itself — extensible with additional optional metadata later without breaking existing consumers. Timestamps MUST be expressed as a numeric, sub-second-precision offset in seconds from the start of the video — never as a formatted clock string (e.g., `HH:MM:SS`) internally; any clock-style formatting happens only when a consumer displays or exports data, consistent with the rest of the platform's data model.
- **FR-005**: System MUST expose frame extraction as a streaming/iterable interface and MUST NOT require holding the entire video, or a large fraction of it, in memory at once. Correspondingly, the service MAY invalidate or reuse the underlying buffer of a previously-yielded frame once the caller advances past it — the service is not required to keep every previously-yielded frame simultaneously valid. A consumer that needs a frame's data beyond the point where it advances to the next one is responsible for copying it first.
- **FR-006**: System MUST produce the identical sequence of frame index/timestamp pairs for the same video and the same sampling configuration on every run (deterministic output).
- **FR-007**: System MUST expose current extraction progress at any point during a run, not only at completion, consisting of: frames processed so far, total frames expected for the request, elapsed time, total expected duration, and a percent-complete figure derived from those.
- **FR-008**: System MUST allow a caller to start extraction from a specified frame index or timestamp, rather than always starting from the beginning of the video; resuming from a given frame index MUST include that index as the first frame yielded (inclusive), not start after it. If a request supplies both a frame index and a timestamp as the resume point, the frame index MUST take precedence and the timestamp MUST be ignored, so the outcome is always deterministic.
- **FR-009**: System MUST reject, immediately and with a specific reason, a requested resume point that falls outside the video's actual range, rather than silently returning an empty or incorrect result.
- **FR-010**: System MUST emit exactly one standardized execution diagnostics record per extraction run, covering the entire requested range, not one per individual frame.
- **FR-011**: System MUST perform all extraction using only local resources, with no network or cloud calls.
- **FR-012**: System MUST perform extraction using CPU only, with no dependency on GPU hardware.
- **FR-013**: System MUST support being used by multiple independent pipeline modules (e.g., Scene Detection, Replay Detection, Scoreboard OCR), each requesting its own sampling mode, without any of them needing to implement their own video-reading logic.
- **FR-014**: System MUST fail fast with a specific, actionable reason whenever extraction cannot proceed correctly (e.g., the source video becomes inaccessible mid-run), rather than silently returning incomplete or incorrect frames.
- **FR-015**: System MUST support cooperative cancellation of an active extraction request. On cancellation, the system MUST stop yielding further frames, MUST release any resources it holds, MUST still emit exactly one diagnostics record summarizing the partial run (per FR-010), and MUST leave enough state that the Pipeline Orchestrator can later resume from the last frame actually delivered before cancellation (per FR-008).

### Key Entities

- **Frame Context**: The single, stable payload the service yields for each frame — this, not a bare image, is what every downstream module (Scene Detection, Replay Detection, Scoreboard OCR, and future consumers) actually consumes. Key attributes: a source-video identifier (so a consumer handling frames from multiple requests can tell which video a given frame came from), frame index (0-based, in the original video), timestamp (seconds from video start, numeric, sub-second precision), the decoded frame's image data, and room for additional optional metadata to be added later without breaking existing consumers. Ownership/lifetime: a consumer may retain a given `Frame Context` only through the current iteration step by default — the service may reuse or invalidate its underlying image buffer once the caller advances to the next frame (FR-005); a consumer needing the data for longer must copy it.
- **Extraction Request**: A caller's request configuration. Key attributes: the validated video (`LoadResult`) to read from, the chosen sampling mode (exactly one of: every frame, fixed rate, frame-index list, or timestamp list — FR-003), and an optional starting point (frame index or timestamp, frame index taking precedence if both are given) for resuming.
- **Extraction Progress**: The current state of an in-flight extraction, on the same standardized shape for every request. Key attributes: frames processed so far, total frames expected for the request, elapsed time, total expected duration, and a derived percent-complete figure.
- **Extraction Diagnostics**: The standardized per-run record summarizing one complete (or cancelled) extraction request, consistent with the platform's existing Module Observability & Diagnostics standard.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A consuming pipeline module can obtain frames in any of the four sampling modes (every frame, fixed rate, frame-index list, timestamp list) without writing any of its own video-decoding logic.
- **SC-002**: Peak memory attributable to a single extraction request stays at or under 150MB, regardless of the video's duration — a 3-4 hour match consumes no more than a short (a few minutes) clip at the same sampling rate, since the budget covers one decoded frame plus a small fixed overhead, not a fraction of the video.
- **SC-003**: Given the same video and the same sampling configuration, repeated extraction runs produce identical frame index/timestamp sequences 100% of the time.
- **SC-004**: An extraction resumed from a specified point never re-yields frames prior to that point.
- **SC-005**: Extraction progress can be observed at any point during a multi-hour run, not only after it completes.
- **SC-006**: Every extraction run produces exactly one diagnostics record, regardless of whether it processed 10 frames or 100,000.
- **SC-007**: Extraction completes using only local, offline resources on target-class hardware (CPU-only, 8GB RAM class machine) in 100% of test runs.
- **SC-008**: Repeated extraction runs against the same video and the same configuration complete within a consistent time range of one another under the same conditions — no run takes dramatically longer than another, so performance is predictable across runs, not just correct on average.

## Assumptions

- Concurrent extraction requests against the same underlying video (from different callers, e.g., Scene Detection and Scoreboard OCR running at the same time) are not required to be thread-safe or to share a single decode pass for this feature's initial scope; each request may be treated independently. Whether/how a shared decode pass is implemented internally to avoid double-decoding cost is an implementation decision for the planning phase (see `specs/technical_plan.md`'s "Frame Extraction Service" open questions), not a behavioral requirement of this spec.
- The frame-index-list and timestamp-list sampling modes are provided for completeness and future extensibility (e.g., targeted re-examination of specific match segments); the initial consumers (Scene Detection, Replay Detection, Scoreboard OCR) are expected to primarily use the "every frame" or "fixed rate" modes. The four modes named in FR-003 are expected to be formalized as a canonical enumeration during `/speckit-plan`/`/speckit-tasks` — this spec fixes the set of four and their behavior, not their literal representation.
- Resume support operates at frame-index granularity; the caller (e.g., the Pipeline Orchestrator) is responsible for tracking and supplying which point to resume from — this service does not persist its own resume checkpoints across process restarts.
- This service inherits Video Loader's input constraints by depending on its `LoadResult` (MP4/MKV containers, video already fully saved to local disk, not a live stream).
- A sampling rate requested higher than the video's native frame rate is satisfied by yielding every available frame (the video's native rate is a ceiling), not by fabricating frames.
- Frame timestamps are read from the video's actual per-frame timing data, not computed by assuming a constant frame rate — this means Variable Frame Rate (VFR) source videos are supported without special-casing, since each frame's own timestamp is authoritative regardless of how evenly frames are spaced in time.
- The service is optimized for forward sequential traversal, matching how every current consumer (Scene Detection, Replay Detection, Scoreboard OCR) walks through a match in order. Random/arbitrary seeking to a far-away frame — beyond the single documented resume-start-point use case (FR-008) — is not a scenario this feature is required to make performant; a caller with a genuine need for fast arbitrary seeking would be a new requirement, not an assumed capability of this one.
