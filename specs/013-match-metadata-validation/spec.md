# Feature Specification: Structured Match Metadata Validation Layer

**Feature Branch**: `013-match-metadata-validation`

**Created**: 2026-08-05

**Status**: Draft

**Input**: User description: "Structured Match Metadata Validation layer (docs/PRD.md Section 17 'Future Enhancements', next available spec number 013). An optional, decoupled post-hoc stage that consumes externally-supplied, locally-provided ball-by-ball match metadata (commentary and/or scorecard) and aligns it against Event Detection's own OCR-derived output, for two purposes: (1) report real detection accuracy (recall/precision by event type), and (2) recover clips for real events the OCR-only pipeline missed entirely. Also considers whether this data source can unblock dismissal-subtype/fielder-attribution event detail that technical_plan.md's 'Event Taxonomy & Detectability' section currently blocks for lack of a data source."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Report Detection Accuracy Against Real Match Metadata (Priority: P1)

A user who has analyzed a match and has independent access to what actually happened in it (official ball-by-ball commentary, a scorecard export, etc.) wants to know how well the pipeline actually performed on their footage — which real fours, sixes, and wickets were detected, which were missed, and whether anything was detected that didn't really happen. This is a pure read-side check: it never changes the analyzed match's stored data.

**Why this priority**: This is the foundation every other story depends on — you cannot decide what to recover (Story 2) or enrich (Story 3) without first knowing what's missing. It is also immediately useful on its own: this exact comparison has already been done by hand for two real matches in this project's history, and formalizing it turns a one-off investigation technique into something any user can run against their own footage.

**Independent Test**: Given a completed match's analysis and a matching metadata file, run the accuracy report and confirm it produces a recall/precision breakdown without altering anything about the stored match.

**Acceptance Scenarios**:

1. **Given** a completed match's analysis and a matching metadata file, **When** the user runs the accuracy report, **Then** the system shows true positives, false negatives, false positives, and recall/precision for each event type (FOUR/SIX/WICKET).
2. **Given** a metadata event whose position in the match has no scoreboard reading anywhere near it, **When** the report runs, **Then** that miss is shown separately from a miss where a reading existed nearby but no event was still detected there — collapsing these two into one "missed" bucket has repeatedly hidden the real cause during this project's own investigations and must not happen here.
3. **Given** a metadata file that doesn't match the analyzed match (e.g., referencing overs beyond the match's real length), **When** the user runs the report, **Then** the system fails with a clear, specific error rather than producing a comparison that looks valid but isn't.

---

### User Story 2 - Recover Clips for Events the Pipeline Missed (Priority: P2)

A user who ran the accuracy report (Story 1) and found real events the video-only pipeline missed wants those moments actually available in their highlight video, not just counted in a statistic. For each confirmed-missing event, the system locates the moment in the video (using the match's own already-captured scoreboard readings near that point in the match) and, only when the user explicitly asks it to, adds it to the match's event record so it becomes available for highlight generation exactly like any other detected event.

**Why this priority**: Only meaningful once Story 1 exists — you need to know what's missing before you can recover it. It's also a materially bigger commitment than Story 1: it writes into a match's stored analysis rather than just reading it, so it comes second by design.

**Independent Test**: Given a metadata event already confirmed missing by Story 1, and a nearby scoreboard reading for that same point in the match, run recovery and confirm exactly one new event is added, timestamped near the real moment, with nothing existing duplicated or altered.

**Acceptance Scenarios**:

1. **Given** a real event confirmed missing by Story 1's report, **When** the user runs recovery, **Then** a new event appears in the match's stored analysis, clearly marked as sourced from metadata rather than detected from video.
2. **Given** a metadata event with no nearby scoreboard reading at all (no way to place it in the video), **When** recovery runs, **Then** that event is reported as unrecoverable, never silently skipped or given a guessed timestamp.
3. **Given** a match whose analysis is already complete, **When** recovery adds events, **Then** the match's completion status and every previously-detected event are left exactly as they were — recovery only ever adds.
4. **Given** recovery has already been run once for a match and metadata file, **When** the user runs it again, **Then** no duplicate events are created.

---

### User Story 3 - Enrich Wicket Events With Dismissal Detail (Priority: P3)

A user building a "wickets" highlight reel wants to know how each batter got out (bowled, caught, LBW, run out, stumped) and, for a catch, which fielder took it — detail the video's own on-screen scoreboard never shows (it only tracks a wicket count), but that commentary routinely states in plain text ("c Dileep KP b Sai Kiran", "run out (Mohan)"). When metadata is supplied, the system reads this detail and attaches it to the matching wicket event.

**Why this priority**: The highest-value story here — it directly unblocks detail this platform has explicitly deferred for lack of any data source (see `specs/technical_plan.md`'s "Event Taxonomy & Detectability"). It's last because it depends on Stories 1-2's metadata-to-event alignment being trustworthy first, and because it may prove to need larger changes to how a wicket event is stored than the other two stories do.

**Independent Test**: Given a wicket event already in the match's record and a metadata description that states how the dismissal happened, run enrichment and confirm the dismissal detail is attached without changing the event's timestamp, confidence, or existence.

**Acceptance Scenarios**:

1. **Given** a wicket event and a metadata description stating a fielder caught the batter, **When** enrichment runs, **Then** the event's stored detail reflects a caught dismissal and names the fielder.
2. **Given** a metadata description whose dismissal detail isn't stated in a recognizable way, **When** enrichment runs, **Then** the event is left without dismissal detail rather than a guessed one.

---

### Edge Cases

- Metadata references a point in the match that couldn't exist (e.g., an over number beyond the match's actual length) — must be rejected/flagged, not searched for indefinitely.
- Metadata covers only one innings of a two-innings match — the other innings is simply not reported/recovered/enriched, not treated as an error.
- A metadata description is ambiguous about what happened (e.g., a near-miss that isn't actually a boundary) — must never be miscounted as a FOUR/SIX/WICKET.
- The match's analysis is still in progress or failed (not complete) — accuracy reporting, recovery, and enrichment must all refuse; there is no stable set of detected events to compare against yet.
- Two metadata entries legitimately share the same position in the match (e.g., a delivery re-bowled after a no-ball) — must be treated as two distinct entries, never silently merged into one.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST accept a locally-supplied match metadata file (ball-by-ball, one entry per delivery with its position in the match and a free-text description of what happened) as a strictly optional input.
- **FR-002**: System MUST NOT fetch match metadata over a network under any circumstance — locally-supplied files only.
- **FR-003**: Every existing capability that does not involve metadata MUST behave identically whether or not metadata is ever supplied — this feature must never become a required input.
- **FR-004**: System MUST derive a ground-truth list of FOUR/SIX/WICKET events from supplied metadata based on its description text.
- **FR-005**: System MUST estimate each ground-truth event's position in the video by searching the match's own already-captured scoreboard readings for the same point in the match, preferring a fully-validated reading and widening the search only as needed.
- **FR-006**: System MUST report, per event type, how many ground-truth events were detected (true positives), missed (false negatives), and how many detected events have no corresponding ground-truth entry (false positives), plus overall recall and precision.
- **FR-007**: System MUST distinguish, for every missed ground-truth event, whether no scoreboard reading exists anywhere near it versus a reading existed nearby but no event was still detected there.
- **FR-008**: System MUST refuse to run accuracy reporting, recovery, or enrichment against a match whose analysis is not complete, with a clear error.
- **FR-009**: System MUST refuse to run accuracy reporting, recovery, or enrichment when supplied metadata cannot be parsed into the expected shape, with a clear error identifying the problem, rather than proceeding with a partial or meaningless comparison.
- **FR-010**: For a ground-truth event confirmed missing, System MUST let the user explicitly trigger recovery, which adds it to the match's stored events only when its position in the video was successfully estimated (FR-005).
- **FR-011**: System MUST mark every recovered event as sourced from metadata, distinguishable from a video-detected event wherever events are shown or exported.
- **FR-012**: System MUST NOT create a duplicate event for the same ground-truth entry if recovery is run more than once against the same match and metadata.
- **FR-013**: System MUST leave every previously-detected event, and the match's own completion status, unchanged when recovery runs.
- **FR-014**: When a ground-truth event's description states a dismissal type (bowled/caught/LBW/run out/stumped/hit wicket) and/or a fielder, System MUST attempt to attach that detail to the matching wicket event, leaving it unset when the description isn't confidently readable rather than guessing.
- **FR-015**: System MUST reject metadata referencing a position in the match outside the analyzed video's own known range, rather than searching indefinitely.
- **FR-016**: System MUST treat two ground-truth events at the same position in the match as distinct entries, never deduplicating them.
- **FR-017**: System MUST retain a record of every recovery or enrichment operation sufficient to answer, without relying on anything outside the match's own stored analysis: what was added or changed, when, from which metadata source, and to which match.
- **FR-018**: Given the same completed match analysis, the same metadata file, and the same configuration, System MUST produce identical accuracy report, recovery, and enrichment results every time it is run.

### Key Entities

- **Match Metadata Source**: a locally-supplied file describing what actually happened in the match, delivery by delivery — each entry has a position in the match (over and ball) and a free-text description. Supplied by the user; never fetched by the system.
- **Ground-Truth Event**: a FOUR, SIX, or WICKET event derived from the Match Metadata Source, with an estimated position in the video (once alignment succeeds) and, for a wicket, an optional dismissal type and fielder if the description states them.
- **Accuracy Report**: the comparison between Ground-Truth Events and the match's already-detected events — true positives, false negatives (split by whether a nearby reading existed), false positives, and recall/precision by event type.
- **Recovered Event**: an event added to a match's stored analysis from a Ground-Truth Event that had no corresponding detected event, marked as metadata-sourced and retaining a record of when and from which metadata source it was added (FR-017).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user with a completed match analysis and a matching metadata file gets a full accuracy report (recall/precision by event type, with the no-signal/signal-but-missed distinction) without any change to the match's stored analysis.
- **SC-002**: Run against a match this project has already independently validated by hand, the accuracy report reproduces that same known recall figure within a small margin, confirming it matches proven results rather than a fresh, unverified calculation.
- **SC-003**: A user can recover at least one real, previously-undetected event into a completed match's highlight generation without re-running any part of the original video analysis.
- **SC-004**: Recovered events are clearly distinguishable from originally-detected events everywhere events are shown or exported.
- **SC-005**: Running recovery twice against the same match and metadata produces the same event count both times.
- **SC-006**: A user generating a wickets highlight reel with metadata supplied sees dismissal type and fielder detail for wickets where the metadata stated them, and no fabricated detail for wickets where it didn't.

## Assumptions

- Match metadata is supplied as ball-by-ball commentary (a position in the match plus a free-text description per delivery), not a bare final scorecard of totals only — a scorecard alone has no per-delivery detail to align timestamps against. A user with only a final scorecard cannot use this feature's accuracy reporting or recovery.
- The metadata's own stated positions in the match (over, ball, innings) are trusted as correct — this feature does not attempt to detect or correct errors within the supplied metadata itself.
- Recovery and enrichment are explicit, user-triggered actions on an already-analyzed match, never an automatic side effect of the normal analysis run — a user who never supplies metadata never has their stored analysis touched by this feature.
- Dismissal-type/fielder extraction (Story 3) depends on the metadata's descriptions following commentary phrasing this project has already seen work ("c FIELDER b BOWLER", "run out (FIELDER)", "b BOWLER" for bowled, "lbw" for LBW). A description that doesn't follow any recognizable pattern is left unenriched.
- This feature accepts metadata in the simple ball-by-ball JSON shape already proven in this project's own investigation tooling. Natively parsing other real-world formats (e.g. a specific scoring app's own export format) is not required for this feature — a user with such a format converts it to the accepted shape first.
- Story 3 may turn out to need larger changes to how a wicket event is stored than Stories 1-2 do (to hold dismissal type and fielder at all). This spec establishes why it matters and what it requires; whether it ships together with Stories 1-2 or becomes its own follow-up is a planning-time decision, not fixed here.
