# Feature Specification: Clip Generator

**Feature Branch**: `008-clip-generator`

**Created**: 2026-07-29

**Status**: Draft

**Input**: User description: "Implement Clip Generator (Module 8): given a list of detected events queried from the Event Database (per user selection/template), the source video path, and clip settings (pre-roll/post-roll seconds, default 8s/12s), compute each event's clip window (clip_start_seconds, clip_end_seconds), drop or keep replay-flagged events per a replay-exclusion flag, merge overlapping clip windows to avoid duplicate/overlapping clips, and produce an ordered clip plan (start/end times + source video path per clip) as this module's output. This module does not produce the final stitched video (that's Module 9, Video Stitcher) and performs no OCR, replay detection, or other analysis -- it only operates on already-persisted Event Database rows, consistent with constitution Principle III (Single-Pass Analysis: Phase 2 / `generate` only queries the already-built Event Database). See specs/technical_plan.md's Module 8 section and Database Schema (events table's clip_start_seconds/clip_end_seconds columns, currently NULL until this module runs) for full context."

**Revision note (2026-07-29)**: Refined after initial review to add explicit internal evidence/traceability (`ClipEvidence`), a documented stage-by-stage Processing Model, merge-reason recording, a deterministic `clip_id`, expanded diagnostics, explicit tie-break ordering, and additional clip metadata — all internal/diagnostic additions that strengthen observability without changing the core architecture (see Processing Model and the new Key Entities below).

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Turn Selected Events Into Playable Clip Windows (Priority: P1)

A user who has already run `cvip analyze` and now runs `cvip generate` against a filtered set of match events (e.g., all sixes and wickets in a match) gets, for each of those events, a precise clip window — a start and end time in the source video — with enough lead-in and follow-through footage that the highlight doesn't feel abruptly cut off.

**Why this priority**: This is the entire reason Module 8 exists — without a clip window per event, there is nothing for Module 9 (Video Stitcher) to cut and stitch. Every other concern in this feature (replay exclusion, overlap merging) only matters once basic windowing works.

**Independent Test**: Feed a synthetic list of `DetectedEvent`-shaped records (no video, no database — plain in-memory objects, matching every pipeline module's own precedent) with known timestamps, a source video path, a known video duration, and pre-roll/post-roll settings. Run Clip Generator and verify each output clip's start/end times equal the event's timestamp minus pre-roll and plus post-roll, respectively.

**Acceptance Scenarios**:

1. **Given** a single event at timestamp 120.0s with 8s pre-roll and 12s post-roll configured, **When** Clip Generator runs, **Then** the output contains one clip with `clip_start_seconds = 112.0` and `clip_end_seconds = 132.0`.
2. **Given** an event at timestamp 3.0s with 8s pre-roll configured (which would compute a negative start), **When** Clip Generator runs, **Then** the output clip's `clip_start_seconds` is clamped to `0.0`, not negative.
3. **Given** an event near the end of a video of known duration, where the computed `clip_end_seconds` would exceed the video's total duration, **When** Clip Generator runs, **Then** the output clip's `clip_end_seconds` is clamped to the video's duration, not beyond it.
4. **Given** an empty input event list, **When** Clip Generator runs, **Then** the output is a valid, empty clip plan — not an error.

---

### User Story 2 - Exclude (or Include) Replay Footage On Request (Priority: P2)

A user generating a highlight reel wants replay footage excluded by default (so a boundary and its slow-motion replay don't appear as two separate highlight moments), but can opt in to including replays when they want the fuller broadcast experience.

**Why this priority**: Directly implements the "user-configurable replay inclusion" mitigation for replay-detection inaccuracy (`docs/RISK_REGISTER.md` R2). It materially changes what ends up in the final video, but the platform still delivers its core value (User Story 1) without it if every event happens to be non-replay.

**Independent Test**: Feed a mix of events where some have `is_replay = true` and others `is_replay = false`. Run Clip Generator once with replay-inclusion off and once with it on; verify replay-flagged events produce no clip window in the first run and a normal clip window in the second.

**Acceptance Scenarios**:

1. **Given** an event with `is_replay = true` and the replay-inclusion flag set to `false` (default), **When** Clip Generator runs, **Then** no clip window is produced for that event.
2. **Given** the same event with the replay-inclusion flag set to `true`, **When** Clip Generator runs, **Then** a clip window is produced for that event exactly as if it were a live event.
3. **Given** a mix of replay and non-replay events with replay-inclusion off, **When** Clip Generator runs, **Then** the output contains clip windows only for the non-replay events, and every non-replay event is still represented.

---

### User Story 3 - No Duplicate or Overlapping Footage in the Final Reel (Priority: P3)

A user watching the generated highlight video never sees the same moment twice and never sees an awkward jump where two adjacent highlights' pre-roll/post-roll windows overlapped and got cut mid-footage — closely spaced events flow together as one continuous clip instead.

**Why this priority**: A quality/polish concern rather than a blocking one — the platform still produces a usable (if occasionally redundant or jumpy) highlight reel without it, but this is what makes the reel feel professionally edited rather than mechanically assembled.

**Independent Test**: Feed a set of events whose computed clip windows deliberately overlap, or sit close enough together (within the configured merge-gap threshold) to warrant merging, alongside events far enough apart that they must stay separate. Verify the output clip plan contains one merged window for the close/overlapping group and separate windows for the distant events, with no two output windows overlapping.

**Acceptance Scenarios**:

1. **Given** two events whose computed clip windows overlap, **When** Clip Generator runs, **Then** the output contains one merged clip window spanning the earliest start to the latest end of the two, tagged with merge reason `OVERLAP`, not two separate overlapping windows.
2. **Given** two events whose computed clip windows do not overlap but are separated by a gap smaller than or equal to the configured merge-gap threshold, **When** Clip Generator runs, **Then** the output contains one merged clip window, tagged with merge reason `GAP_THRESHOLD`, not two separate windows with a tiny gap between them.
3. **Given** two events whose computed clip windows are separated by a gap larger than the configured merge-gap threshold, **When** Clip Generator runs, **Then** the output contains two separate clip windows.
4. **Given** three or more events whose windows chain together (each overlaps or sits within the merge-gap threshold of the next, but the first and last do not directly overlap each other), **When** Clip Generator runs, **Then** the output contains one single merged window spanning the entire chain, whose internal evidence records `CHAIN_MERGE` for the event(s) that joined transitively rather than triggering the chain's first join directly.
5. **Given** two events at the exact same timestamp (e.g., a `FOUR` and a co-occurring `TEAM_MILESTONE` from the same comparison, per `specs/007-event-detection/spec.md` FR-023), **When** Clip Generator runs, **Then** the output contains exactly one clip window for that moment, not a duplicate, and that window's `source_event_ids` lists both contributing events.

---

### Edge Cases

- An event's clip window, after pre-roll/post-roll, would start before 0 or end after the video's total duration — clamped to `[0, video_duration_seconds]`, never out of bounds (Acceptance Scenarios US1-2, US1-3).
- Every input event is excluded by the replay-inclusion flag — the output is a valid, empty clip plan, not an error.
- The input event list is already empty (e.g., a filter matched nothing) — the output is a valid, empty clip plan, not an error (Acceptance Scenario US1-4).
- Two or more events collapse to an identical clip window (same timestamp, or windows that are subsets of one another) — merged into one, never duplicated, with `source_event_ids` listing every contributing event (Acceptance Scenario US3-5).
- A merge-gap threshold of `0` — only genuinely overlapping windows merge; a zero-second gap between two windows still counts as touching and MUST merge (boundary is inclusive, consistent with FR-006's "less than or equal to").
- Two or more clamped windows share an identical `clip_start_seconds` before merging (e.g., same-timestamp events per US3-5) — resolved deterministically by the FR-009 tie-break rule so that merge order, and therefore the resulting `source_event_ids` order and `clip_id`, is stable across runs.
- A chain of three or more windows merges into one clip — the join that directly overlaps or meets the gap threshold is tagged `OVERLAP`/`GAP_THRESHOLD`; a window that joins only transitively through an already-merged neighbor is tagged `CHAIN_MERGE` (Acceptance Scenario US3-4).
- Missing or structurally malformed required input (event list, source video path, video duration, pre-roll/post-roll/merge-gap settings) — fails fast with a specific reason; never silently proceeds with defaults (constitution Principle VI).
- Negative or non-finite pre-roll, post-roll, merge-gap, or video-duration values — rejected as invalid configuration, not silently clamped to zero.

## Requirements *(mandatory)*

### Processing Model

Clip Generator processes the entire input event list through a fixed stage order, each stage's output feeding the next (mirroring the architectural clarity established by Event Detection's own Processing Model, `specs/007-event-detection/spec.md`):

1. **Filtered Events** — the already-filtered, caller-supplied sequence of detected events (FR-001); no filtering by player/team/event-type/importance happens inside this module.
2. **Clip Window Generation** — for *every* input event, unconditionally, compute its raw (unclamped) clip window from `timestamp_seconds`, `pre_roll_seconds`, `post_roll_seconds` (FR-002).
3. **Boundary Clamping** — clamp each raw window to `[0, video_duration_seconds]` (FR-003).
4. **Replay Filtering** — drop every clamped window whose source event has `is_replay = true`, unless the replay-inclusion flag is set (FR-004, FR-005).
5. **Merge Engine** — combine the surviving clamped windows into the final, non-overlapping set, recording which merge reason (`OVERLAP`, `GAP_THRESHOLD`, `CHAIN_MERGE`) applied at each join (FR-006, FR-007).
6. **Ordered Clip Plan** — the fully-assembled, deterministically-ordered output (FR-008, FR-009).

Stages 2-3 (Clip Window Generation, Boundary Clamping) deliberately run for every input event *before* Stage 4 (Replay Filtering), not after — this keeps windowing/clamping uniform (no special-casing which events get windowed) and is what lets the internal `ClipEvidence` record what a replay-excluded event's window *would have been*, satisfying this module's explainability goal (see Key Entities `ClipEvidence` below). A future stage reordering MUST preserve this property rather than short-circuiting replay-excluded events out of Stage 2.

### Functional Requirements

- **FR-001**: System MUST accept, as input, an already-filtered ordered sequence of detected events (each carrying at minimum a stable `event_id` — Module 5's `event_key` — a `timestamp_seconds`, and an `is_replay` flag, the same shape as Module 5's `DetectedEvent`), the source video's file path, the source video's total duration in seconds, a pre-roll duration in seconds, a post-roll duration in seconds, a merge-gap threshold in seconds, and a replay-inclusion flag. This module MUST NOT itself query the Event Database or apply user-selection/template filtering (e.g., `--player`, `--team`, `--min-importance`) — that filtering has already happened by the time this module receives its input (constitution Principle III; PRD Section 6 Phase 2 restriction).
- **FR-002** (Stage: Clip Window Generation): For *every* input event, System MUST compute a raw clip window as `[timestamp_seconds - pre_roll_seconds, timestamp_seconds + post_roll_seconds]` — including events that will later be dropped by Replay Filtering (Acceptance Scenario US1-1; Processing Model).
- **FR-003** (Stage: Boundary Clamping): System MUST clamp every computed clip window's start to no less than `0.0` and its end to no more than the source video's total duration, so no window ever references time outside the actual video (Acceptance Scenarios US1-2, US1-3).
- **FR-004** (Stage: Replay Filtering): When the replay-inclusion flag is `false` (the default — `docs/RISK_REGISTER.md` R2's "user-configurable replay inclusion"), System MUST exclude every event with `is_replay = true` from the Merge Engine stage onward — its clamped window is discarded, and it contributes to no output clip (Acceptance Scenario US2-1).
- **FR-005** (Stage: Replay Filtering): When the replay-inclusion flag is `true`, System MUST carry a replay-flagged event's clamped window into the Merge Engine stage exactly as it would for any other event (Acceptance Scenario US2-2).
- **FR-006** (Stage: Merge Engine): System MUST merge two surviving clamped windows into a single window spanning their combined start-to-end range whenever they overlap (merge reason `OVERLAP`), or whenever the gap between them (the later window's start minus the earlier window's end) is less than or equal to the configured merge-gap threshold (merge reason `GAP_THRESHOLD`) (Acceptance Scenarios US3-1, US3-2, US3-3).
- **FR-007** (Stage: Merge Engine): Merging MUST be transitive across chains of three or more windows — if window A merges with B, and the resulting group would also merge with C, all three MUST collapse into one single output window. A window that joins a chain transitively (not via a direct `OVERLAP`/`GAP_THRESHOLD` relationship to the group's originating pair) MUST have that join recorded with merge reason `CHAIN_MERGE` (Acceptance Scenario US3-4).
- **FR-008**: The output clip plan MUST contain no two windows that overlap or sit within the merge-gap threshold of each other — every pair of adjacent output windows MUST be separated by more than the merge-gap threshold (Acceptance Scenarios US3-1 through US3-4; this is the postcondition FR-006/FR-007 exist to guarantee, and implies output clip start times are always strictly increasing — see FR-009).
- **FR-009**: System MUST produce the output clip plan's windows ordered by ascending `clip_start_seconds`. Whenever two or more clamped windows share an identical `clip_start_seconds` prior to merging (necessarily merging into one clip per FR-006/FR-008, since equal starts imply overlap), System MUST resolve their combination order deterministically: by ascending `clip_end_seconds`, then by each contributing event's original position in the input event sequence (stable insertion order) — so the resulting clip's `source_event_ids` order and `clip_id` (FR-010) are stable across repeated runs (Acceptance Scenario US3-5, Edge Cases).
- **FR-010**: Every output clip MUST carry a deterministic `clip_id`, derived from the sorted, deduplicated set of its contributing `source_event_ids` (FR-009's tie-break makes this reproducible even when multiple events share a timestamp) — identical input MUST always yield an identical `clip_id`, and every `clip_id` MUST be unique within one Clip Plan.
- **FR-011**: Every output clip MUST carry: the source video path supplied in the input; its own `clip_start_seconds`/`clip_end_seconds`; `source_event_ids` (the `event_id` of every contributing event, ordered per FR-009); `event_count` (`= len(source_event_ids)`); `merged` (`true` if `event_count > 1`, i.e. the clip resulted from combining two or more events' windows); and `contains_replay` (`true` if any contributing event has `is_replay = true` — only possible when the replay-inclusion flag is `true`, since otherwise such events never reach the Merge Engine per FR-004).
- **FR-012**: If the input event list is empty, or every event is excluded by FR-004, System MUST return a valid, empty clip plan rather than an error (Acceptance Scenario US1-4, Edge Cases).
- **FR-013**: System MUST NOT perform OCR, replay detection, scene detection, or any other frame/video analysis — it operates purely on already-supplied event data and numeric settings (constitution Principle III; matching Module 5's own no-video-access precedent).
- **FR-014**: System MUST produce deterministic output: running Clip Generator twice against the same input event list and configuration MUST yield an identical, identically-ordered clip plan, including identical `clip_id`, `source_event_ids` order, and merge-reason assignments.
- **FR-015**: System MUST fail fast with a specific, distinguishable failure reason — never silently proceed with a default or a clamped substitute — when a required input is missing or structurally malformed: the event list, source video path, or video duration is absent; or pre-roll, post-roll, merge-gap, or video duration is negative or non-finite (Edge Cases).
- **FR-016**: System MUST preserve, internally, one `ClipEvidence` record per input event (unlike Module 5's `EventEvidence`, which is recorded only for events that produce a `DetectedEvent`, `ClipEvidence` covers every considered event, including replay-excluded ones — this is what FR-002/FR-003's "window every event first" ordering makes possible). Each record captures: the event's `event_id`; its raw (unclamped) window (FR-002); its clamped window (FR-003); whether it was excluded by Replay Filtering and why (FR-004); and, for surviving events, the `clip_id` (FR-010) it ultimately contributed to and the merge reason(s) (`OVERLAP`/`GAP_THRESHOLD`/`CHAIN_MERGE`) that joined it to that clip (empty if its window became a clip verbatim, unmerged). `ClipEvidence` is internal — the public Clip Plan is not required to expose it (Key Entities).
- **FR-017**: System MUST emit exactly one diagnostics record per invocation (the platform's shared `ExecutionDiagnostics` shape, `src/cvip/common/diagnostics.py`), regardless of whether the run completes normally or fails, matching every prior pipeline module's own precedent. Its `output_summary` MUST include, at minimum: `events_received`, `replay_events_excluded`, `clip_windows_generated`, `merge_operations_performed`, `final_clip_count`, `average_clip_duration` (`0.0` when `final_clip_count == 0`, never a division-by-zero failure — matching Module 5's FR-028 precedent), `total_planned_duration`, and `config_version`. Execution duration is already covered by the standard `ExecutionDiagnostics` shape and need not be duplicated in `output_summary` (matching Module 5's FR-028 note).
- **FR-018**: System's internal processing MUST proceed through the fixed stage order defined in Processing Model above for every run — Clip Window Generation and Boundary Clamping (stages 2-3) MUST complete for every input event before Replay Filtering (stage 4) evaluates any event, and Replay Filtering MUST complete before the Merge Engine (stage 5) begins.
- **FR-019**: System MUST NOT populate or modify any database row directly — its output is an in-memory, self-contained clip plan; persisting `clip_start_seconds`/`clip_end_seconds` back onto `events` rows (if desired) remains the Pipeline Orchestrator's responsibility, matching every prior module's own precedent of returning results rather than writing to the database itself.

### Key Entities

- **Clip Generation Request**: The input to one Clip Generator run — the already-filtered event sequence (each event carrying `event_id`, `timestamp_seconds`, `is_replay`), the source video path, the source video's total duration, and the clip settings (`pre_roll_seconds`, `post_roll_seconds`, `merge_gap_seconds` — sourced from `config/default.yaml`'s `events` block, current values there authoritative; see that file's own comment for the real-footage calibration behind them — and the replay-inclusion flag, default `false`).
- **Planned Clip**: One entry in the output clip plan — `clip_id` (deterministic, FR-010), `clip_start_seconds`, `clip_end_seconds` (both clamped within the video's bounds), `source_video_path`, `source_event_ids`, `event_count`, `merged`, and `contains_replay` (FR-011). Represents one continuous span of footage to extract, after all merging.
- **Clip Plan**: The complete, ordered output of one Clip Generator run — a sequence of Planned Clips (ascending by start time, no overlaps, no duplicates) plus a total count. Self-contained, with no reference to any run-internal merge state.
- **ClipEvidence**: An internal record of how each *input event* was handled — not part of the public Clip Plan, preserved for diagnostics/explainability/future tuning (FR-016), matching Module 4a's `SmoothingEvidence` and Module 5's `EventEvidence` precedent. One record per input event (including replay-excluded ones): `event_id`, raw window, clamped window, replay-exclusion decision (and reason), and — for events that survive into a clip — the resulting `clip_id` and the merge reason(s) that joined it there.
- **MergeReason**: The taxonomy of why two windows (or a window and an existing merged group) were combined by the Merge Engine — `OVERLAP` (the windows literally overlapped in time), `GAP_THRESHOLD` (the windows didn't overlap but their gap was `<= merge_gap_seconds`), or `CHAIN_MERGE` (the window joined an already-merged group transitively, not via a direct overlap/gap relationship to the group's originating pair) (FR-006, FR-007).
- **Clip Generation Failure Reason**: The run-level failure taxonomy for this feature — covers missing/malformed input (event list, source video path, or video duration absent) and invalid clip settings (negative or non-finite pre-roll, post-roll, merge-gap, or video duration).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Every output clip window's start/end times exactly equal the configured pre-roll/post-roll offset from its source event's timestamp, clamped to the video's bounds where applicable — verified with zero discrepancies against a hand-computed expected clip plan for a representative event set.
- **SC-002**: No two clips in any output clip plan overlap, and no two adjacent clips are separated by a gap smaller than or equal to the configured merge-gap threshold — verified across event sets specifically constructed to exercise pairwise and chained merging.
- **SC-003**: Every output clip's `clip_start_seconds` is `>= 0.0` and `clip_end_seconds` is `<= video_duration_seconds` for every generated clip plan, with zero out-of-bounds clips across a test set including events near both the start and end of the video.
- **SC-004**: Running Clip Generator twice against the same input produces a byte-identical (same values, same order, same `clip_id`s) clip plan.
- **SC-005**: Replay-flagged events are excluded from 100% of generated clips when the replay-inclusion flag is off, and included in 100% of generated clips when it is on, with zero misclassifications.
- **SC-006**: Computing a clip plan for a full match's worth of detected events (on the order of a few hundred) completes in well under the platform's overall `generate` budget of under 2 minutes (`specs/technical_plan.md` Performance Targets) — this stage is pure in-memory computation with no I/O, so it is expected to be a negligible fraction of that budget, with the remainder spent in Module 9's actual FFmpeg work.
- **SC-007**: Every Planned Clip's `clip_id` is unique within its Clip Plan and identical across repeated runs against the same input (consistent with SC-004) — verified by re-running against an event set containing a merge-produced clip (multiple contributing events) and confirming stable `clip_id` values.
- **SC-008**: The internal `ClipEvidence` trail accounts for every input event exactly once — either linked to the `clip_id` it contributed to, or marked as replay-excluded — with zero input events unaccounted for, verified across event sets mixing merged, unmerged, and replay-excluded events.

## Assumptions

- **Video duration is caller-supplied, not re-derived by this module**: consistent with FR-013 (no video/frame access), the source video's total duration is passed in as part of the Clip Generation Request rather than opened and measured by this module. The caller (ultimately the Pipeline Orchestrator, via the `matches` table's `duration_seconds`, populated by Video Loader at analyze time) is responsible for supplying an accurate value.
- **Filtering by template/player/team/event-type/importance has already happened**: per `specs/cli.md`'s `generate` command surface (`--player`, `--team`, `--event-type`, `--min-importance`, `--start-over`/`--end-over`, etc.), this module receives an already-filtered event list. Applying those filters is a query-construction concern that belongs to whatever queries the Event Database (the Pipeline Orchestrator or a dedicated query layer), not to Clip Generator itself — matching the "clean input/output contract" boundary every prior module has kept.
- **`--max-duration` (a total-highlight-length cap from `specs/cli.md`) is out of scope for this module**: truncating an already-computed clip plan to fit a maximum total duration is a caller-level concern applied after clip generation (or during event pre-filtering), not a Clip Generator responsibility — this module's job is to turn a given event set into correct, non-overlapping clip windows, not to decide how many of them "fit."
- **`event_id`, `timestamp_seconds`, and `is_replay` are the only per-event fields this module reads** — no other Detected Event field (confidence, importance, player, event_type, etc.) affects clip-window computation, merging, or replay exclusion. `event_id` is assumed to be Module 5's `event_key`, already unique and stable per its own contract (`specs/007-event-detection/spec.md` FR-025), which is what makes deterministic `clip_id`/`source_event_ids` derivation (FR-010, FR-011) possible without this module inventing its own identity scheme.
- **Clip settings default to `config/default.yaml`'s `events` block** (`pre_roll_seconds`/`post_roll_seconds`/`merge_gap_seconds`, current values and rationale documented in that file's own comment) when the caller doesn't override them — resolved by the caller before constructing the request, matching every prior module's own precedent for config-derived values (e.g. Event Detection's `ranking`/`team_milestone_interval`). **Post-implementation calibration** (`specs/011-club-broadcast-overlay-support/`'s real-video validation against First8Overs.mp4): the original `8`/`12` defaults were found to badly under-cover the bowler run-up — the on-screen scoreboard graphic only updates once the broadcast returns from its post-event replay, so the detected event timestamp lags the actual live delivery by ~15s, and a fixed 8s pre-roll anchored to that lagged timestamp reaches nowhere near the run-up (observed ~30-35s before the detected timestamp). `pre_roll_seconds` was widened to `35` and `post_roll_seconds` to `15` accordingly — see `config/default.yaml`'s own comment for the full measurement.
- **Expected implementation complexity**: Clip Window Generation and Boundary Clamping (Stages 2-3) are a single `O(n)` pass over the input events. Replay Filtering (Stage 4) is `O(n)`. The Merge Engine (Stage 5) is a single left-to-right sweep over windows ordered by `clip_start_seconds` — `O(n)` if the input event sequence already arrives timestamp-ascending (true whenever the caller passes through Module 5's own output-ordering guarantee, `specs/007-event-detection/data-model.md` `EventDetectionResult.events`) or `O(n log n)` if an explicit sort is needed first. Overall pipeline: `O(n log n)` worst case, `O(n)` in the common case — this is guidance for maintainers, not a functional requirement, and is expected to be a negligible contributor to SC-006's budget regardless.
