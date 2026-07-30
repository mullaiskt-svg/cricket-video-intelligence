# Feature Specification: Scene Detection

**Feature Branch**: `003-scene-detection`

**Created**: 2026-07-27

**Status**: Draft

**Input**: User description: "Scene Detection: analyzes a validated cricket match video and produces an ordered list of scene boundaries (timestamps marking where the broadcast cuts from one continuous camera shot to another), consumed downstream by Replay Detection (Module 3) and eventually Event Detection. Must detect scene changes, camera transitions (e.g., wide shot to close-up, camera-to-camera cuts), and replay-style transitions (wipes, logo stings, or other editorial transition effects broadcasters use to bracket a replay) as a distinct, flaggable category of boundary -- Replay Detection's own transition_weight signal (config/default.yaml) consumes this flag, it does not redetect transitions itself. Technology: PySceneDetect (scenedetect==0.6.1), which performs its own internal content-aware shot-boundary analysis; reconcile this against the Frame Extraction Service (Module 1a) which every other CV module is required to consume frames through -- if PySceneDetect cannot be fed frames from that service and insists on opening the video file itself, that must be a deliberate, documented exception to the \"always use the Frame Extraction Service\" rule, not a silent bypass. Sensitivity is configurable via config/default.yaml's existing video.scene_threshold (currently 27.0), not hardcoded. Output: an ordered list of scene boundaries, each with a timestamp in seconds and a boundary-type classification (ordinary cut vs. replay-transition), that Replay Detection and later modules can query without re-running scene detection themselves -- persisted or held in memory for the duration of a single `cvip analyze` run, whichever this platform's existing patterns (Video Loader's LoadResult, Frame Extraction Service's FrameExtractor) suggest is more consistent. Must run fully offline, CPU-only, single-pass over the video (no re-decoding already-processed segments), within the platform's ~10-20 minute budget for this module (specs/technical_plan.md's Performance Targets table) and its overall <6GB memory / 40-minute end-to-end budget for a 3-4 hour match on the target hardware (Intel Core i3-1115G4, 8GB RAM). Must emit the platform's standardized one-record-per-run execution diagnostics (reusing cvip.common.diagnostics, as Video Loader and Frame Extraction Service already do), including at minimum how many scene boundaries were found and how many were classified as replay-transitions. Failure handling must follow the same fail-fast, specific-reason philosophy as Video Loader and Frame Extraction Service -- no silent fallback to \"no scenes detected\" on an internal error."

## Clarifications

### Session 2026-07-27

- Q: Should the Frame Extraction Service integration exception (if PySceneDetect must open the file itself) be scoped narrowly? → A: Yes — any such exception is documented during planning, applies only to Scene Detection, and must never become a precedent for other modules to bypass the Frame Extraction Service.
- Q: Should a boundary's replay-style classification be a binary label, a continuous confidence score, or both? → A: Both — `boundary_type` remains a stable two-value enum (`ORDINARY_CUT` / `REPLAY_TRANSITION`) for simple consumption, plus an optional `confidence` score (0.0-1.0) Replay Detection can use as an additional weighting signal alongside its other four weighted signals.
- Q: Do individual boundaries need a stable identifier? → A: Yes — `boundary_id`, unique within a single detection run, for downstream referencing, diagnostics, and debugging.
- Q: Should the Scene Detection Result carry richer run-level metadata beyond the boundary list itself? → A: Yes — `source_video_id`, `total_boundaries`, `replay_transition_count`, `processing_duration`, and `configuration_version`, making the result self-describing and auditable without cross-referencing the diagnostics record.
- Q: What ordering/uniqueness guarantees does the boundary list carry? → A: Strictly ascending by timestamp; timestamps are unique within a run; duplicate boundaries are never emitted.
- Q: How are boundary timestamps represented? → A: Double-precision floating-point seconds from the start of the video — consistent with the Frame Extraction Service's own timestamp representation.
- Q: Does Scene Detection need cooperative cancellation, matching the Frame Extraction Service's pattern? → A: Yes — clean termination, resource release, exactly one diagnostics record even on a cancelled run, and enough state for the Pipeline Orchestrator to resume the overall workflow afterward.
- Q: Should the single-pass guarantee be stated more explicitly? → A: Yes — exactly one forward traversal of the video, no backward seeking, no re-decoding of any previously processed segment.
- Q: Should success criteria and diagnostics be made more measurable/specific? → A: Yes — SC-004 reworded to a measurable, testable bound; new SC-008 added for run-to-run determinism; the diagnostics record's field list is now fixed and enumerated rather than "at least."
- Q: Should the module's exact responsibility boundary versus Replay Detection be documented explicitly? → A: Yes — Scene Detection detects, classifies, scores, and publishes boundaries; it never determines whether a bracketed segment is an actual replay — that determination remains Replay Detection's exclusive responsibility, combining this module's output with its other independently-weighted signals.
- Q: Should `confidence` be mandatory on every boundary, or optional? → A: Mandatory — every reported boundary always carries a confidence score (0.0-1.0); a value of 1.0 means maximally confident, not "definitely a replay." This keeps the field deterministic and self-contained so Replay Detection (and diagnostics/analytics/visualization) never has to special-case a missing value or invent its own fallback default.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Segment a match video into scene boundaries (Priority: P1)

A pipeline run needs to know where the broadcast cuts from one continuous camera shot to the next across an entire match, so that downstream modules (Replay Detection, and eventually Event Detection) can reason about the video in terms of discrete shots rather than a raw, undifferentiated stream of frames.

**Why this priority**: This is the entire reason the feature exists. Without a boundary list, Replay Detection has nothing to check for a "wipe" transition pattern against, and no later module can align findings to shot structure.

**Independent Test**: Can be fully tested by running scene detection against a short validated video with a known, hand-verified set of cut points and confirming the returned boundaries' timestamps match those known cut points, in order.

**Acceptance Scenarios**:

1. **Given** a successfully validated match video, **When** scene detection runs, **Then** it produces an ordered (by timestamp, strictly ascending) list of scene boundaries covering the whole video, with no duplicate timestamps.
2. **Given** a validated video containing multiple camera-angle changes (e.g., wide shot to close-up, bowler-end to batter-end), **When** scene detection runs, **Then** each such change is reported as a boundary.
3. **Given** a validated video that is a single continuous shot with no cuts, **When** scene detection runs, **Then** it produces an empty boundary list rather than failing or fabricating a boundary.
4. **Given** a video that has not been successfully validated (no successful `LoadResult`), **When** scene detection is requested, **Then** it refuses and does not attempt to read the file.

---

### User Story 2 - Flag replay-style transitions distinctly from ordinary cuts (Priority: P2)

Replay Detection needs to know which boundaries look like an editorial replay transition (a wipe, logo sting, or similar effect broadcasters use to bracket a replay) versus an ordinary hard cut between camera angles, so it can use that as one weighted signal (`transition_weight` in `config/default.yaml`) without re-analyzing the video for transition effects itself.

**Why this priority**: This is what makes Scene Detection's output directly useful to Replay Detection rather than a generic cut list Replay Detection would have to reprocess. It builds on User Story 1's boundary list rather than being useful on its own.

**Independent Test**: Can be fully tested by running scene detection against a validated video containing both an ordinary hard cut and a known replay-style transition, and confirming the two boundaries receive different classifications, each with a confidence score.

**Acceptance Scenarios**:

1. **Given** a boundary that is an ordinary hard cut between two camera angles, **When** scene detection classifies it, **Then** it is reported with `boundary_type = ORDINARY_CUT`.
2. **Given** a boundary that carries the visual signature of an editorial replay transition (e.g., a wipe or logo sting effect), **When** scene detection classifies it, **Then** it is reported with `boundary_type = REPLAY_TRANSITION`, distinct from an ordinary cut.
3. **Given** any classified boundary, **When** scene detection reports it, **Then** it always includes a `confidence` score (0.0-1.0) reflecting how strongly the visual signal supported that classification — never absent — for Replay Detection to weight alongside its other signals.
4. **Given** a boundary whose classification is uncertain, **When** scene detection reports it, **Then** it is still included in the boundary list with its best-effort classification and a correspondingly lower confidence score, and never causes the whole run to fail over one ambiguous boundary.

---

### User Story 3 - Complete within budget, and support clean cancellation, for a full match (Priority: P3)

An operator runs scene detection as part of analyzing a full 3-4 hour match. It completes within the module's allotted share of the overall analysis budget, does not consume unbounded memory as the video gets longer, and can be cleanly stopped mid-run if the overall pipeline run is cancelled.

**Why this priority**: A hard platform constraint that must hold before this module can be trusted as a building block for Replay Detection and Event Detection — but it is a property of User Stories 1-2 operating at real-world scale and within the platform's operational-resilience model, not a new detection capability of its own.

**Independent Test**: Can be fully tested by running scene detection against a full-length (3-4 hour) validated video and confirming both elapsed time and peak memory stay within the documented budget; separately, by starting a run and requesting cancellation partway through and confirming it stops cleanly.

**Acceptance Scenarios**:

1. **Given** a 3-4 hour match video, **When** scene detection runs, **Then** it completes within its allotted ~10-20 minute share of the overall analysis budget (`specs/technical_plan.md` Performance Targets).
2. **Given** a 3-4 hour match video, **When** scene detection runs, **Then** peak memory attributable to the run does not scale with the video's length in a way that would threaten the platform's overall <6GB budget.
3. **Given** a match video, **When** scene detection runs, **Then** the video is decoded once, start to finish, in a single forward pass — no segment is re-decoded and no backward seeking occurs.
4. **Given** scene detection is in progress, **When** the Pipeline Orchestrator requests cancellation, **Then** detection stops cleanly, releases any resources it holds, still emits its one diagnostics record summarizing the partial run, and leaves the Orchestrator able to resume the overall workflow appropriately afterward.

### Out of Scope

- Determining whether a bracketed segment is an actual replay. Scene Detection detects, classifies (`ORDINARY_CUT` / `REPLAY_TRANSITION`), scores (confidence), and publishes an ordered boundary list — nothing more. Replay Detection (Module 3) remains the sole owner of combining this signal with its other independently-weighted signals (logo detection, scoreboard absence, motion profile, camera angle) to decide whether a segment is genuinely a replay. This feature MUST NOT evolve into a replay-analysis engine in its own right.
- Persisting results beyond a single `cvip analyze` run, or exposing a query interface across separate runs (see Assumptions).
- Validating or tuning the configured sensitivity threshold's suitability for a given broadcast style.

### Edge Cases

- What happens with a video that has no scene cuts at all (a single continuous shot)? — Resolved: an empty boundary list is a valid, non-error outcome (US1 Acceptance Scenario 3).
- What happens with a video containing an unusually high rate of cuts (e.g., a fast-paced highlights-style broadcast segment)? — Resolved: the module still completes a single forward pass within budget; a high boundary count is a valid outcome, not a failure condition (see Assumptions on the sensitivity threshold's role here).
- What happens when a boundary's classification (ordinary cut vs. replay-transition) is ambiguous? — Resolved: it is still reported with a best-effort classification and a correspondingly lower (but always present) confidence score; classification uncertainty never fails the whole run (US2 Acceptance Scenario 4, per constitution Principle VI's fail-fast requirement applying to unrecoverable errors, not to classification confidence).
- What happens when the underlying video becomes unavailable partway through detection (e.g., deleted or locked after Video Loader already validated it)? — Resolved: the run fails fast with a specific, actionable reason, consistent with Video Loader and the Frame Extraction Service.
- What happens when a frame is undecodable/corrupted partway through an otherwise-good video? — Resolved: covered by the same fail-fast requirement (FR-018) — a single corrupted frame stops the run with a specific reason rather than silently skipping it, consistent with Video Loader and the Frame Extraction Service.
- What happens with a Variable Frame Rate (VFR) source video, where frames aren't evenly spaced in time? — Resolved: boundary timestamps come from each frame's actual decoded timestamp (via the Frame Extraction Service), never from a constant-frame-rate calculation, so VFR sources are handled without special-casing — consistent with the Frame Extraction Service's own VFR handling.
- What happens when the configured sensitivity (`video.scene_threshold`) is set to an extreme value (e.g., so low that nearly every frame looks like a cut, or so high that no cut is ever detected)? — Resolved: the module applies the configured value as given and reports whatever boundaries result; validating whether a configured value is "reasonable" is a configuration-management concern, not this module's responsibility.
- What happens when a caller requests scene boundaries for a video that has not been (or was not successfully) validated by Video Loader? — Resolved: refused immediately, no file access attempted (US1 Acceptance Scenario 4).
- What happens when the same video and configuration are run through scene detection more than once? — Resolved: the identical ordered boundary sequence is produced every time (FR-020, SC-008).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST accept a successful `LoadResult` (from the Video Loader feature) as its input and MUST NOT accept a raw file path directly, nor attempt its own file validation.
- **FR-002**: System MUST NOT produce any scene boundaries for a `LoadResult` that does not indicate a successful, validated video.
- **FR-003**: System MUST source the frames it analyzes through the Frame Extraction Service (Module 1a), consistent with every other computer-vision module on this platform — resolved during `/speckit-plan` (research.md Decision 1): the selected shot-boundary detection library is driven via its per-frame API, fed frames from the Frame Extraction Service, so no exception to this rule is required.
- **FR-004**: System MUST analyze the video in exactly one forward traversal, start to finish: no backward seeking, and no re-decoding of any previously processed segment.
- **FR-005**: System MUST produce a list of scene boundaries covering the full duration of the video. An empty list is a valid outcome for a video with no detected cuts.
- **FR-006**: The boundary list MUST be strictly ordered by ascending timestamp, MUST contain no two boundaries with the same timestamp, and MUST NOT contain duplicate boundaries.
- **FR-007**: System MUST classify each reported boundary as exactly one of two canonical values: `ORDINARY_CUT` or `REPLAY_TRANSITION` (a boundary carrying the visual signature of an editorial transition effect, such as a wipe or logo sting, that broadcasters use to bracket a replay).
- **FR-008**: System MUST report a `confidence` score (0.0-1.0) alongside every boundary's classification — never absent — reflecting how strongly the visual signal supported that classification (1.0 meaning maximally confident in the assigned classification, not "definitely a replay"), for Replay Detection to use as an additional weighting input alongside its other signals without needing its own fallback for a missing value.
- **FR-009**: Each reported boundary MUST carry a stable identifier, unique within its detection run, for downstream referencing and diagnostics.
- **FR-010**: Boundary timestamps MUST be expressed as double-precision floating-point seconds from the start of the video, consistent with the Frame Extraction Service's timestamp representation — never a formatted clock string.
- **FR-011**: System MUST NOT fail the entire detection run because an individual boundary's classification is uncertain — every detected boundary MUST still be reported with its best-effort classification.
- **FR-012**: System MUST apply a configurable sensitivity threshold (`video.scene_threshold` in `config/default.yaml`) to decide what counts as a cut, rather than a hardcoded value.
- **FR-013**: System MUST make the resulting boundary list available to other modules within the same `cvip analyze` run without requiring them to re-run scene detection themselves.
- **FR-014**: The Scene Detection Result MUST include, alongside the boundary list itself: a source-video identifier, the total boundary count, the replay-transition count, the run's processing duration, and the configuration version used — making the result self-describing without requiring cross-reference to the diagnostics record.
- **FR-015**: System MUST emit exactly one standardized execution diagnostics record per detection run, containing: module name, processing duration, total frames analyzed, total boundaries detected, replay-transition count, peak memory usage, the configuration used, and a failure reason (if applicable).
- **FR-016**: System MUST perform detection using only local resources, with no network or cloud calls.
- **FR-017**: System MUST perform detection using CPU only, with no dependency on GPU hardware.
- **FR-018**: System MUST fail fast with a specific, actionable reason whenever detection cannot proceed correctly (e.g., the source video becomes inaccessible mid-run, or a frame cannot be decoded), rather than silently returning an incomplete or empty boundary list as if it were a genuine result.
- **FR-019**: System MUST support cooperative cancellation of an active detection run. On cancellation, the system MUST stop processing further frames, MUST release any resources it holds, MUST still emit exactly one diagnostics record summarizing the partial run (per FR-015), and MUST leave the Pipeline Orchestrator able to resume the overall workflow afterward.
- **FR-020**: System MUST produce the identical ordered boundary sequence (including classifications and confidence scores) for the same video and the same configuration on every run (deterministic output).
- **FR-021**: System MUST NOT determine whether a bracketed segment is an actual replay — that determination is Replay Detection's exclusive responsibility, combining this feature's boundary classifications with its other independently-weighted signals. This feature's responsibility ends at detecting, classifying, scoring, and publishing boundaries.

### Key Entities

- **Scene Boundary**: A single detected cut point. Key attributes: `boundary_id` (stable, unique within its detection run), `timestamp_seconds` (double-precision, from video start), `boundary_type` (`ORDINARY_CUT` or `REPLAY_TRANSITION`), and `confidence` (0.0-1.0, always present — the classifier's certainty in the assigned `boundary_type`, not a measure of whether the boundary itself exists).
- **Scene Detection Result**: The complete, ordered output of one detection run for one video. Key attributes: `source_video_id`, the ordered list of Scene Boundaries, `total_boundaries`, `replay_transition_count`, `processing_duration`, and `configuration_version`.
- **Scene Detection Diagnostics**: The standardized per-run record summarizing one complete (or cancelled) detection run, consistent with the platform's existing Module Observability & Diagnostics standard. Key attributes: module name, processing duration, total frames analyzed, total boundaries detected, replay-transition count, peak memory usage, configuration used, and failure reason (if applicable).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A consuming pipeline module (Replay Detection or later) can obtain a full, ordered scene boundary list for a validated video without implementing any of its own shot-boundary detection logic.
- **SC-002**: Every reported boundary carries exactly one of the two classifications (`ORDINARY_CUT` or `REPLAY_TRANSITION`) — never both, never neither.
- **SC-003**: Scene detection for a 3-4 hour match completes within its allotted ~10-20 minute share of the platform's overall analysis time budget on target-class hardware, in 100% of test runs.
- **SC-004**: Peak memory attributable to a single detection run for a 3-4 hour match does not exceed peak memory for a short (a few minutes) clip processed with the same settings by more than 20% — memory does not scale with video duration. (An absolute ceiling in MB will be finalized during `/speckit-plan` once the selected shot-boundary detection library's actual memory profile is benchmarked, following the same approach used for the Frame Extraction Service's SC-002.)
- **SC-005**: Every detection run produces exactly one diagnostics record, regardless of whether it found zero boundaries or several hundred.
- **SC-006**: Detection completes using only local, offline resources on target-class hardware (CPU-only, 8GB RAM class machine) in 100% of test runs.
- **SC-007**: The video is decoded exactly once per detection run — no segment is re-decoded within a run.
- **SC-008**: Given the same video and the same configuration, repeated detection runs produce identical ordered boundary sequences (including classifications and confidence scores) 100% of the time.
- **SC-009**: Every reported boundary includes a confidence score between 0.0 and 1.0 inclusive — never absent — so a consumer never needs a fallback for a missing value.

## Assumptions

- Scene Detection's output (the Scene Detection Result) is an in-memory, per-run artifact scoped to a single `cvip analyze` run, consistent with Video Loader's `LoadResult` and the Frame Extraction Service's `FrameExtractor` — it is not written to its own persisted database table. `specs/technical_plan.md`'s Database Schema has no `scene_boundaries` table, and nothing about this feature's consumers (Replay Detection, within the same run) requires querying results across separate `cvip analyze` invocations.
- "Scene changes" and "camera transitions" (wide shot to close-up, camera-to-camera cuts) are treated as the same underlying category — `ORDINARY_CUT` — for classification purposes; both are shot boundaries from Scene Detection's perspective, distinguished from a `REPLAY_TRANSITION` by the presence (or absence) of an editorial transition effect, not by what kind of camera change occurred.
- Replay-transition classification (and its accompanying confidence score) is a heuristic, best-effort signal, not a guaranteed-accurate one. Replay Detection (Module 3) already combines this signal with several independently-weighted others (`transition_weight` is one of five weighted signals in `config/default.yaml`), so this feature is not required to achieve a specific accuracy bar on its own — the platform's ≥90% replay-removal accuracy target (constitution Principle IV) is Replay Detection's responsibility to meet using this and its other signals together, not a target this feature must hit in isolation.
- **Resolved during `/speckit-plan`** (research.md Decision 1): the shot-boundary detection library is driven via its per-frame API (e.g., feeding it one frame at a time), fed by frames supplied from the Frame Extraction Service — it does not open the video file itself. No exception to FR-003's "always use the Frame Extraction Service" rule was needed after all.
- The configured sensitivity threshold (`video.scene_threshold`) is assumed to already be a reasonable value for cricket-broadcast content by the time this feature runs; validating or tuning that value is a configuration concern, not part of this feature's behavior.
- **Post-implementation amendment (real-video validation, specs/011-club-broadcast-overlay-support/'s investigation)**: this Assumption was never actually true. `video.scene_threshold` had been carrying PySceneDetect's own generic `ContentDetector` library default (`27.0`) since this feature's original implementation, never validated against real footage. Real-video testing found it produced **zero or near-zero boundaries** across representative samples of an actual club-cricket recording -- the underlying "how different do two consecutive frames look" score varies enormously within a single match (measured max ~5.7 during calm pre-match footage vs. ~95-97 during active play across three independent samples), and no single fixed `ContentDetector` threshold could be simultaneously correct for both regimes: a value low enough to catch cuts during calm footage produced hundreds of spurious boundaries once play started, while a value that behaved reasonably during play found almost nothing during calm footage.

  **Detector changed**: `ContentDetector` (a single, uniformly-applied cut-score threshold) was replaced with PySceneDetect's `AdaptiveDetector`, which compares each frame's content-difference score against a small rolling window of its own immediate neighbors rather than one global constant. This is a published, community-maintained algorithm from the same library (`scenedetect.com`), not a custom detector -- its own module documentation explicitly recommends it over `ContentDetector` for "situations such as fast camera motions," which matches this platform's actual target content (single-camera club/informal recordings, not multi-camera professional broadcasts).

  **Parameter choice, evaluated against three options in order of complexity** (pure `AdaptiveDetector` defaults; `AdaptiveDetector` with one calibrated constant; `AdaptiveDetector` with automatic per-video calibration): the middle option was selected. `adaptive_threshold` (the scale-invariant ratio a frame must exceed relative to its own neighborhood) was left at PySceneDetect's own published default (`3.0`) -- real-video testing found no evidence it needed overriding. `video.scene_threshold` now maps to `AdaptiveDetector`'s `min_content_val` (a noise floor a frame must also clear before being considered at all, previously `15.0`, PySceneDetect's own default) -- recalibrated to `8.0` after finding `15.0` sat almost exactly at the 99th percentile of this footage's own active-play score distribution, filtering out all but the most extreme 1% of frames. Automatic per-video calibration (the third, most complex option) was evaluated and explicitly deferred: with only one real match video validated, there was no evidence a fixed default fails to generalize, and building calibration logic to solve an undemonstrated problem would be premature complexity inconsistent with this platform's own constitution (simplicity, single-pass, no unjustified new module coupling). The originally-considered calibration signal (Scoreboard OCR's first successful reading, as a proxy for "play has started") was found to be architecturally invalid regardless of preference -- Scene Detection (Module 2) runs before Scoreboard OCR (Module 4) in the pipeline's own fixed sequence, so that data cannot exist yet when Scene Detection runs.

  **Validated against 7 real-footage scenarios** (opening/pre-match, early gameplay, middle overs, death overs, innings transition, a known wicket/replay window, and camera-movement-intensity contrast): produced 0 boundaries on calm pre-match footage and 2-13 well-spaced boundaries across active-play scenarios, using the same unchanged parameters throughout -- no per-scenario retuning. One caveat disclosed, not resolved: the death-overs sample produced a tight cluster of boundaries within a few seconds, plausibly reflecting a genuinely prolonged, visually complex moment rather than over-fragmentation, but not independently confirmed by visual review.

  This remains a **reasoned calibration from one real match, not exhaustively validated across broadcasters or tournaments** -- the same disclosure standard applied to every other real-video-calibrated constant on this platform (see `config/default.yaml`'s own comment for the full rationale). Revisit with real evidence, not assumptions, once 2+ independent match videos are available.
- This feature inherits Video Loader's input constraints by depending on its `LoadResult` (MP4/MKV containers, video already fully saved to local disk, not a live stream).
- Cooperative cancellation (FR-019) follows the same model established by the Frame Extraction Service: the caller (ultimately the Pipeline Orchestrator) decides when to stop; this feature does not poll an external signal itself, and resuming a cancelled run from a checkpoint is the Orchestrator's responsibility, not a persisted capability of this feature.
- FR-006's no-duplicate-timestamp guarantee does not require a tie-breaking rule between two independently-produced boundary events: a detected cut's `boundary_type` and `confidence` are decided together, as a single classification step for that one cut, not by two separate detectors that could disagree about the same frame. Two colliding boundaries at the identical timestamp is therefore not a scenario this feature needs to resolve — it cannot occur by construction.
