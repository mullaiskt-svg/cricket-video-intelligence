# Feature Specification: Scene-Cut-Anchored Clip Windows

**Feature Branch**: `016-scene-cut-clip-windows`

**Created**: 2026-08-08

**Status**: Draft

**Input**: User description: "Scene-Cut-Anchored Clip Windows — a follow-on from specs/014-anchor-validation and specs/015-innings-transition-detection. Both prior features fixed WHICH scoreboard reading gets matched to a metadata event; this feature addresses a third, distinct problem confirmed by direct video-frame inspection: even a correctly-matched reading (right team, right score, right over.ball) can have its timestamp land during a replay or a static scoreboard hold, nowhere near the actual live delivery, because OCR only encodes what the scoreboard displayed, never when within its on-screen duration the live action happened. A fixed pre-roll/post-roll offset from such a timestamp is not reliable. Scene Detection's own visual cut-boundary output is a genuinely independent, non-OCR signal (it detects camera cuts directly from frame content) that can be used to snap a clip's start to the nearest real cut before the event's timestamp instead of an arbitrary fixed offset, without requiring scoreboard legibility at all."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A Clip Starts at a Real Camera Cut, Not an Arbitrary Offset (Priority: P1)

A user generates highlights for a match whose event timestamps are correct (right team, right moment in the match) but imprecise (the exact second within a broadcast hold or replay is not reliably knowable from the scoreboard alone). Today, every clip starts at a fixed number of seconds before the event timestamp — a guess that can land mid-replay or mid-setup instead of at the moment the camera actually cuts to what matters. This story makes the clip start at the nearest genuine camera cut before the event instead, when one is available.

**Why this priority**: This is the concrete, directly-observed defect (a real recovered clip whose window showed replay/setup footage instead of the described event) that this feature exists to fix — the core value.

**Independent Test**: Generate highlights for an event whose timestamp is known to fall shortly after a genuine camera cut, with cut-boundary data supplied. Confirm the resulting clip starts at that cut's timestamp, not at the fixed pre-roll offset.

**Acceptance Scenarios**:

1. **Given** an event timestamp with a real camera cut shortly before it, **When** highlights are generated with cut-boundary data supplied, **Then** the clip starts at that cut's timestamp.
2. **Given** an event timestamp with no camera cut within a reasonable distance before it, **When** highlights are generated, **Then** the clip falls back to today's existing fixed pre-roll behavior for that event.
3. **Given** highlights are generated for a match with no cut-boundary data supplied at all, **When** clips are produced, **Then** every clip is identical to what today's fixed pre-roll/post-roll behavior would produce — this feature changes nothing for a match that doesn't have this new, optional data available.

---

### Edge Cases

- What happens when a camera cut exists before the event but is far earlier than any reasonable clip window (e.g., the last cut was two minutes ago)? It must not be used — the search must be bounded, and the event falls back to the fixed pre-roll offset in this case (Acceptance Scenario 2).
- What happens when the event timestamp itself falls exactly on a detected cut? That cut is a valid candidate (a distance of zero still counts as "at or before").
- What happens when the same source video has some events with cut-boundary data available nearby and others without? Each event is handled independently — some clips may be cut-snapped, others fixed-offset, within the same generation run.
- What happens with a video that has an unusually high density of cuts (e.g., rapid camera switching)? The nearest-before cut is still used; this feature does not need to reason about cut density, only proximity to each individual event.
- What happens if the supplied cut-boundary data is empty or malformed? Treated the same as no data supplied at all (Acceptance Scenario 3) — never a hard failure of the whole generation run.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST accept an optional set of known camera cut timestamps for the source video, alongside its existing inputs.
- **FR-002**: When cut-boundary data is supplied, the system MUST, for each event, look for a camera cut at or before the event's own timestamp, within a bounded search distance.
- **FR-003**: When a qualifying camera cut is found for an event, the system MUST use that cut's timestamp as the clip's start instead of the existing fixed pre-roll offset.
- **FR-004**: When no qualifying camera cut is found for an event (none within the bounded search distance, or no cut-boundary data supplied at all), the system MUST fall back to today's existing fixed pre-roll offset for that event's clip start — never fail the event or the run because of missing or insufficient cut data.
- **FR-005**: The bounded search distance (how far before an event's timestamp to look for a candidate cut) MUST be configurable, not hardcoded.
- **FR-006**: This feature MUST NOT change clip end/post-roll computation — only clip start.
- **FR-007**: This feature MUST NOT change any existing behavior (clip boundaries, merging, replay filtering, or output) for a generation run that supplies no cut-boundary data.
- **FR-008**: This feature MUST NOT change the command-line interface or externally visible behavior of running a full match analysis — it only affects how highlight clip windows are computed.
- **FR-009**: For every clip whose start was determined by a camera cut rather than the fixed offset, the system MUST record this distinctly (which mechanism produced the clip start) so it can be inspected/explained after the fact, consistent with this platform's existing practice of never leaving an automated decision unexplained.
- **FR-010**: Given the same events, video, and cut-boundary data, clip window computation MUST produce identical results on every run.
- **FR-011**: The feature MUST depend only on already-available signals (event timestamps, camera cut timestamps) — it MUST NOT require any new data extraction (such as team names or on-screen text) to function.

### Key Entities *(include if feature involves data)*

- **Camera Cut**: A single timestamp in the source video where the visual content changes significantly (a camera angle change, a cut into or out of a replay, etc.) — supplied to this feature as an already-detected, ordered list, not something this feature detects itself.
- **Clip Start Decision**: The recorded outcome, per event, of whether its clip start came from a matched camera cut or the fallback fixed offset — including which cut (if any) was used and how far before the event it was.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: For the real match whose investigation motivated this feature, the specific previously-identified defective clip (an event verified to land during a replay/hold) starts at or after the nearest real camera cut before it, once cut-boundary data is supplied — confirmed by inspecting the resulting clip's start point against the video.
- **SC-002**: A generation run supplying no cut-boundary data produces byte-for-byte identical clip windows to the pre-existing fixed-offset behavior — zero regression for any match without this new, optional data.
- **SC-003**: Every clip in a generation run's output can be traced to a specific reason its start was chosen (cut-matched vs. fixed-offset fallback), readable without inspecting raw logs.
- **SC-004**: Re-running clip generation against the same inputs always produces identical results.

## Assumptions

- Cut-boundary data is supplied by the caller (however it was obtained — a fresh Scene Detection run, a persisted store, or any other mechanism) — this feature consumes a list of timestamps, it does not itself decide how that list is produced, stored, or kept up to date. That decision belongs to whatever composes this feature into the broader pipeline, and is explicitly out of scope for this spec.
- The bounded search distance's specific default value is a calibration detail to be resolved during planning against real data, following this platform's established practice of documenting such calibrations with their real-data rationale rather than treating them as arbitrary constants.
- This feature addresses clip START precision only (the concrete evidence gathered — an event landing mid-replay — is a "clip starts too late/in the wrong place" problem). Whether clip END/post-roll would benefit from equivalent treatment is not addressed by this feature and may be considered separately if evidence supports it.
