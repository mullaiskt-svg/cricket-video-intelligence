# Feature Specification: Event Detection

**Feature Branch**: `007-event-detection`

**Created**: 2026-07-28

**Status**: Draft

**Input**: User description: "Implement Event Detection (Module 5): identify cricket match events (fours, sixes, wickets, team milestones) by diffing consecutive readings from the OCR Timeline Smoother's cleaned scoreboard timeline, cross-referencing Replay Detection's replay timeline, and persist them to the Event Database with a confidence score and importance ranking for downstream Clip Generation. Scope is bounded by `specs/technical_plan.md`'s canonical MVP event set: `FOUR`, `SIX`, `WICKET` (generic, no subtype), `TEAM_MILESTONE` — dismissal subtypes, fielding events, and individual batter milestones (`FIFTY`/`CENTURY`) remain explicitly out of scope pending data sources this platform does not yet have."

## Clarifications

### Session 2026-07-29

- Q: A `WICKET` event's `player` field — dismissed batter, bowler, or both? → A: Dismissed batter only. The events table has one `player` column, and highlight filtering by player is most naturally batter-centric for a wicket moment; bowler-based wicket tallies would need a separate join, out of scope for this column.
- Q: What run-total interval triggers a `TEAM_MILESTONE` event? → A: Every 50 runs (50, 100, 150, 200...), configurable via a new `config/default.yaml` value (`events.team_milestone_interval`, default 50). Matches conventional broadcast milestone cadence.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Automatic Scoring Event Detection (Priority: P1)

A user who has run `cvip analyze` on a full match broadcast gets, without any manual video scrubbing, a complete list of every four, six, and wicket that occurred, each tagged with the exact time, over, and ball it happened on.

**Why this priority**: This is the core value proposition of the whole platform — automatic highlight generation is impossible without first knowing *where the highlights are*. Every downstream module (Ranking, Clip Generator, Video Stitcher) depends entirely on this module's output existing and being correct.

**Independent Test**: Feed a synthetic cleaned scoreboard timeline (no video, no OCR — plain in-memory objects, matching Module 4a's own precedent) with known runs/wickets deltas at known timestamps. Run Event Detection and verify each FOUR/SIX/WICKET is emitted at the correct timestamp/over/ball, and that no spurious events are emitted for unchanged or gap-filled readings.

**Acceptance Scenarios**:

1. **Given** a cleaned timeline where the team's runs increase by 4 on a single-ball advance with no wicket change, **When** Event Detection runs, **Then** a `FOUR` event is emitted at that reading's timestamp/over/ball.
2. **Given** a cleaned timeline where the team's runs increase by 6 on a single-ball advance with no wicket change, **When** Event Detection runs, **Then** a `SIX` event is emitted at that reading's timestamp/over/ball.
3. **Given** a cleaned timeline where the wickets count increases by 1, **When** Event Detection runs, **Then** a `WICKET` event is emitted at that reading's timestamp/over/ball, and no `FOUR`/`SIX` is also emitted for that same comparison even if runs also changed.
4. **Given** a cleaned timeline with no runs/wickets change between consecutive readings, **When** Event Detection runs, **Then** no event is emitted for that comparison.
5. **Given** a cleaned timeline containing a leading gap (all-`null` core fields, no known-good reading established yet), **When** Event Detection runs, **Then** no event is derived from any comparison involving a `null`-valued reading.

---

### User Story 2 - Team Milestone Detection (Priority: P2)

A user assembling a highlight reel also gets team-total milestone moments (e.g., the team's score crossing 50, 100, 150) alongside individual boundaries and wickets, so the reel can include innings-progression context, not just boundary-by-boundary action.

**Why this priority**: Adds completeness to the highlight set, but the platform already delivers its core value from User Story 1 alone — milestone detection is additive, not blocking.

**Independent Test**: Feed a cleaned timeline where the team's runs cross 50 and then 100 across separate comparisons, and once more where a single gap-filled jump crosses two thresholds at once (e.g., 45 → 106). Verify exactly one `TEAM_MILESTONE` per threshold actually crossed, never a duplicate for a reading that merely stays above an already-crossed threshold.

**Acceptance Scenarios**:

1. **Given** a cleaned timeline where the team's runs cross 50 between two consecutive readings, **When** Event Detection runs, **Then** exactly one `TEAM_MILESTONE` event is emitted at that reading.
2. **Given** a cleaned timeline where a single comparison's runs delta crosses two milestone thresholds at once, **When** Event Detection runs, **Then** one `TEAM_MILESTONE` event is emitted per threshold crossed (not one, not zero).
3. **Given** a cleaned timeline where runs stay above an already-crossed threshold for many subsequent readings, **When** Event Detection runs, **Then** no additional `TEAM_MILESTONE` is emitted for that threshold again.

---

### User Story 3 - Reliable, Queryable Persisted Events (Priority: P3)

A user querying the Event Database (via `cvip inspect-db`, `export-timeline`, or `generate`) can trust and filter every detected event, because each one carries a confidence score reflecting the underlying OCR reliability, an importance score for ranking, and a correct replay flag so replay footage isn't double-counted as a second live event.

**Why this priority**: Operational completeness — this is what makes detected events actually *usable* downstream, but it's a smaller, more mechanical slice of work than the detection logic itself (User Stories 1-2).

**Independent Test**: Feed a synthetic setup with mixed-confidence raw OCR readings bracketing a detected event and a replay segment overlapping one event's timestamp. Verify the emitted event's `confidence` matches the minimum-of-bracketing-raw-confidences rule, `importance` matches the configured ranking for its `event_type`, and `is_replay` is `true` only for the event whose timestamp falls inside the replay segment.

**Acceptance Scenarios**:

1. **Given** two raw OCR readings bracketing a detected delta, one with `ocr_confidence = 0.9` and the other with `parse_confidence = 0.6`, **When** the corresponding event is emitted, **Then** its `confidence` is `0.6` (the minimum across both readings' both confidence fields).
2. **Given** a detected event's timestamp falls within a supplied replay segment, **When** the event is emitted, **Then** its `is_replay` flag is `true`.
3. **Given** a detected event's timestamp falls outside every supplied replay segment, **When** the event is emitted, **Then** its `is_replay` flag is `false`.
4. **Given** a detected `WICKET` event, **When** it is emitted, **Then** its `importance` equals `config/default.yaml`'s `events.ranking.WICKET` value.

---

### Edge Cases

- Runs increase by 4 or 6 but across more than one ball's advance (e.g., a gap swallowed several balls) — MUST NOT be misclassified as a boundary; only a same-ball (single legal delivery) advance qualifies.
- Runs and wickets both change in the same comparison — WICKET detection takes precedence; no FOUR/SIX is also emitted for that comparison (Acceptance Scenario US1-3).
- Over/ball rollover at an over boundary (`ball_in_over` resets from 5 back to 0, `over_number` increments by 1) — a same-ball advance across this boundary MUST still be recognized as valid, not rejected as an "impossible" jump.
- Innings transition (runs and wickets both drop relative to the previous reading) — MUST NOT be misread as a negative FOUR/SIX or a decreasing WICKET; MUST instead reset internally tracked runs/wickets baselines and advance the internally tracked innings counter (see Assumptions).
- A cleaned reading with a `null` core scoring field on either side of a comparison — skipped entirely, no event derived (Acceptance Scenario US1-5).
- Cooperative cancellation mid-run — stops cleanly, still emits exactly one diagnostics record, matching every other pipeline module's established `.cancel()` precedent.
- Missing or malformed required input (cleaned timeline, raw OCR result, or replay timeline absent or structurally invalid) — fails fast with a specific reason; never silently proceeds with partial data (constitution Principle VI).

## Requirements *(mandatory)*

### Processing Model

Each comparison between two consecutive cleaned readings flows through a fixed stage order, keeping detection logic, replay awareness, and ranking concerns cleanly separated (FR-022):

1. **Timeline Comparison** — diff the previous and current cleaned readings (deltas in `runs`, `wickets`, `over_number`/`ball_in_over`); skip entirely per FR-009/FR-010 where applicable.
2. **Event Rule Engine** — apply the precedence-ordered detection rules (FR-023) to decide which event type(s), if any, this comparison produces.
3. **Replay Annotation** — set `is_replay` by checking the event's timestamp against the replay timeline (FR-016).
4. **Confidence Assignment** — derive `confidence` from the bracketing raw OCR readings (FR-014).
5. **Importance Assignment** — attach `importance` from Module 7's ranking config (FR-015).
6. **Detected Event** — the fully-assembled, immutable output unit (Key Entities).

Stages 3-5 are enrichment, not detection: none of them can cause a rule in stage 2 to fire, change its outcome, or be suppressed (FR-027). This ordering exists so a future new event type is added entirely within stage 2, without touching replay/confidence/importance logic at all.

### Functional Requirements

- **FR-001**: System MUST accept the cleaned scoreboard timeline (Module 4a's `OCRTimelineSmootherResult`) as its primary input, and MUST derive all `FOUR`/`SIX`/`WICKET`/`TEAM_MILESTONE` detections purely from diffing consecutive entries in that cleaned sequence — never from Module 4's raw output directly, and never by implementing its own gap-filling or outlier-correction logic (that responsibility belongs entirely to Module 4a, per its own contract).
- **FR-002**: System MUST additionally accept Module 4's raw Scoreboard OCR result (`ScoreboardOcrResult`) as a secondary input, consulted only to look up `ocr_confidence`/`parse_confidence` by timestamp for confidence derivation (FR-014) — never consulted for its values, since Module 4a's cleaned sequence is the sole source of truth for what actually happened at each timestamp.
- **FR-003**: System MUST accept Replay Detection's replay timeline (start/end segments with confidence, Module 3's output) as an input, used exclusively to set each detected event's `is_replay` flag (FR-016).
- **FR-004**: System MUST detect a `FOUR` event when, between two consecutive cleaned readings representing a single legal ball's advance (see FR-006a), the team's `runs` total increases by exactly 4 and `wickets` does not change.
- **FR-005**: System MUST detect a `SIX` event under the same single-ball-advance condition as FR-004, when `runs` increases by exactly 6 and `wickets` does not change.
- **FR-006**: System MUST detect a `WICKET` event when, between two consecutive cleaned readings, `wickets` increases by exactly 1 — regardless of any concurrent `runs` delta in that same comparison.
- **FR-006a**: System MUST recognize a "single legal ball's advance" as either `ball_in_over` incrementing by exactly 1 within the same `over_number`, or `ball_in_over` rolling over from 5 to 0 with `over_number` incrementing by exactly 1 — and MUST NOT treat any larger jump in `ball_in_over`/`over_number` as a single-ball advance (Edge Cases).
- **FR-007**: System MUST NOT emit a `FOUR` or `SIX` event for any comparison where `wickets` also changed — `WICKET` detection takes precedence for that comparison (Edge Cases, Acceptance Scenario US1-3).
- **FR-008**: System MUST detect a `TEAM_MILESTONE` event each time the team's `runs` total crosses a multiple of a configured threshold interval (default: 50, configurable via `config/default.yaml`'s `events.team_milestone_interval`) between two consecutive cleaned readings, emitting one event per distinct threshold crossed if a single comparison's delta crosses more than one (Acceptance Scenario US2-2).
- **FR-009**: System MUST skip any comparison where either of the two cleaned readings involved has a `null` value in any of its four core scoring fields (`runs`, `wickets`, `over_number`, `ball_in_over`) — there is insufficient information to detect an event from that comparison (Edge Cases, Acceptance Scenario US1-5).
- **FR-010**: System MUST detect a likely innings transition using the same heuristic Module 4 already established (both `runs` and `wickets` dropping relative to the immediately preceding non-skipped reading), and for that one comparison MUST NOT derive a `FOUR`/`SIX`/`WICKET`/`TEAM_MILESTONE` event; instead it MUST reset its internally tracked runs/wickets baseline to the new (lower) values and advance its internally tracked innings counter by 1 (Edge Cases, Assumptions).
- **FR-011**: System MUST populate each detected event's `innings` field from its own internally tracked innings counter (FR-010), initialized to 1 at the start of a run.
- **FR-012**: System MUST leave each detected event's `team` field unpopulated (`NULL`) for this MVP — no module in the pipeline currently extracts a team name or abbreviation from any source (Assumptions).
- **FR-013**: System MUST populate each detected `WICKET` event's `player` field with the dismissed batter's name (the cleaned reading's `batter` field immediately before the dismissal). `FOUR`/`SIX`/`TEAM_MILESTONE` events MUST leave `player` unpopulated (`NULL`) — there is no batter-specific data (only team totals) to attribute a boundary or milestone to an individual.
- **FR-014**: System MUST derive each detected event's `confidence` as the minimum of `ocr_confidence` and `parse_confidence` across the two raw (Module 4) readings, looked up by timestamp, that bracket the detected delta — the lower of the two readings' own two confidence fields, and the lower between the two readings (Acceptance Scenario US3-1).
- **FR-015**: System MUST populate each detected event's `importance` using Module 7's configured ranking score for that event's `event_type` (Acceptance Scenario US3-4), accepted as a caller-supplied mapping (from `config/default.yaml`'s `events.ranking`, resolved by the caller) rather than read from the config file directly by this module — consistent with every prior module's own precedent for config-derived values (e.g. Replay Detection's per-signal weights, Scene Detection's `scene_threshold`).
- **FR-016**: System MUST populate each detected event's `is_replay` flag as `true` if the event's `timestamp_seconds` falls within any segment of the supplied replay timeline, and `false` otherwise (Acceptance Scenarios US3-2, US3-3).
- **FR-017**: System MUST NOT access video frames, OpenCV, or any decode/frame-extraction facility directly — this module operates purely on already-extracted scoreboard and replay data as in-memory Python objects, consistent with Module 4a's precedent as the first modules with no video/frame dependency.
- **FR-018**: System MUST support cooperative cancellation mid-run (a `.cancel()` method checked between comparisons), stopping cleanly without emitting partial/inconsistent events beyond what was already fully processed.
- **FR-019**: System MUST emit exactly one diagnostics record per invocation (the platform's shared `ExecutionDiagnostics` shape) regardless of whether the run completes normally, is cancelled, or fails.
- **FR-020**: System MUST fail fast with a specific, distinguishable failure reason — never silently proceed with a default — when a required input is missing or structurally malformed (e.g., the cleaned timeline, the raw OCR result, or the replay timeline is absent or not well-formed).
- **FR-021**: System MUST produce deterministic output: running Event Detection twice against the same inputs and configuration MUST yield an identical sequence of detected events.
- **FR-022**: System's internal processing MUST proceed through the fixed stage order defined in Processing Model above for every comparison, keeping event-type determination (stage 2) fully independent of replay/confidence/importance enrichment (stages 3-5).
- **FR-023**: System MUST apply detection rules in this precedence order, per comparison, for the *mutually exclusive* interpretation of a `runs`/`wickets` delta: (1) innings-transition heuristic (FR-010) — if matched, no `FOUR`/`SIX`/`WICKET` is derived from this comparison at all; (2) `WICKET` (FR-006); (3) `FOUR`/`SIX` (FR-004, FR-005, FR-006a). At most one of `WICKET`/`FOUR`/`SIX` is derived per comparison. `TEAM_MILESTONE` (FR-008) is **not** part of this mutual-exclusivity chain — it is an orthogonal, independent check against the `runs` total and MAY be emitted alongside `WICKET`, `FOUR`, or `SIX` for the same comparison (e.g., a boundary that also brings up the team's fifty yields both a `FOUR` and a `TEAM_MILESTONE`), or on its own with no boundary/wicket present. This precedence model MUST be extended, not silently reinterpreted, when a future event type is added (Scope & Extensibility).
- **FR-024**: System MUST preserve, for every comparison that yields at least one Detected Event, an internal `EventEvidence` record (one per Detected Event produced) capturing: the previous and current cleaned readings, the `runs`/`wickets`/over-ball deltas between them, which raw OCR readings and confidence values were consulted (FR-002, FR-014), the replay-match result (FR-016), which milestone threshold(s) were crossed (if any, FR-008), and which specific rule fired (FR-023) — for diagnostics, explainability, and future tuning, matching Module 4a's `SmoothingEvidence` precedent. `EventEvidence` is internal; the public Event Detection Result is not required to expose it (Key Entities).
- **FR-025**: System MUST assign every Detected Event a deterministic `event_key`, derived from `innings`, `over_number`, `ball_in_over`, `event_type`, and (for `TEAM_MILESTONE` only) the specific milestone value reached (FR-026) — unique within one Event Detection Result and stable across repeated runs against the same input (consistent with FR-021), so downstream consumers can reference or deduplicate a specific event without recomputing detection logic. This is a property of Module 5's in-memory result, not necessarily a new persisted column — it is fully derivable from columns the `events` table already has, plus `milestone_value` (FR-026).
- **FR-026**: For `TEAM_MILESTONE` events specifically, System MUST record the specific milestone value crossed (e.g., 50, 100, 150) as part of the event — not just the generic `TEAM_MILESTONE` type — so downstream consumers can distinguish which threshold was reached without recomputing it from the underlying timeline (Key Entities `milestone_value`).
- **FR-027**: `importance` (FR-015) MUST be treated strictly as ranking metadata: it MUST NOT influence whether an event is detected, suppressed, or otherwise altered. Detection (FR-004 through FR-011, FR-023) is based solely on the scoring-delta rules, entirely independent of Module 7's ranking configuration — consistent with the Processing Model's stage separation.
- **FR-028**: System MUST include, in its diagnostics record's `output_summary` (following Module 4a's `field_name=value` convention), at minimum: comparisons processed, comparisons skipped (FR-009/FR-010), events detected per type (`FOUR`/`SIX`/`WICKET`/`TEAM_MILESTONE` counts), count of events flagged `is_replay = true`, innings transitions detected (FR-010), average `confidence` across all detected events, and the `config_version` used for this run (`config/default.yaml`'s top-level value). `Execution Duration`/`Start Time`/`End Time` are already covered by the standard `ExecutionDiagnostics` shape (technical_plan.md's Module Observability cross-cutting concern) and need not be duplicated here. When a successful run detects zero events (a valid, non-error outcome — e.g. a timeline with no boundaries, wickets, or milestones at all), average `confidence` MUST be reported as `0.0`, never a division-by-zero failure or an omitted field.
- **FR-029**: System MUST validate `team_milestone_interval` before processing any comparison: it MUST be a positive integer (a real `int`, not `bool`, `>= 1`). System MUST reject an invalid value with a specific, distinguishable failure reason distinct from FR-020's input-taxonomy reason (Key Entities `Event Detection Failure Reason`), with no comparison processed, mirroring the OCR Timeline Smoother's own `outlier_window` validation precedent (`specs/006-ocr-timeline-smoother/spec.md` FR-013).

### Key Entities

- **Detected Event**: This module's public output unit — one candidate row for the eventual `events` table. Attributes: `event_type` (`FOUR`/`SIX`/`WICKET`/`TEAM_MILESTONE`), `timestamp_seconds`, `innings`, `over_number`, `ball_in_over`, `player` (populated only for `WICKET`, per FR-013), `team` (`NULL` for MVP, FR-012), `confidence`, `importance`, `is_replay`, `milestone_value` (populated only for `TEAM_MILESTONE`, `NULL` otherwise, per FR-026), `event_key` (deterministic identifier, per FR-025).
- **Event Evidence**: An internal record of how one Detected Event was derived (FR-024) — not part of the public Event Detection Result, preserved for diagnostics/debugging/future tuning, matching Module 4a's `SmoothingEvidence` precedent.
- **Event Detection Request**: Wraps the cleaned scoreboard timeline (Module 4a's result), the raw Scoreboard OCR result (Module 4's result, for confidence lookup), the replay timeline (Module 3's result), and this module's own detection configuration (the team-milestone threshold interval and Module 7's per-event-type ranking mapping, both caller-supplied — see FR-008, FR-015).
- **Event Detection Result**: The complete, ordered, self-contained output of one run — a sequence of Detected Events plus a total count, with no reference to any run-internal tracking state (matching Module 4a's own "self-contained result" precedent).
- **Event Detection Failure Reason**: The run-level failure taxonomy (FR-020, FR-029) — two values: `INVALID_INPUT` (one of the cleaned timeline, raw OCR result, or replay timeline is missing or not structurally well-formed, FR-020) and `INVALID_DETECTION_CONFIGURATION` (`team_milestone_interval` is not a positive integer, FR-029), matching the OCR Timeline Smoother's own two-value taxonomy pattern (`specs/006-ocr-timeline-smoother/spec.md` Key Entities).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Against a hand-annotated reference match (the platform's golden dataset, once it exists per `specs/technical_plan.md`'s "Golden Dataset & Accuracy Verification"), the system detects at least 95% of actual fours, sixes, and wickets correctly (constitution Principle IV).
- **SC-002**: Every detected event carries a `confidence` value between 0.0 and 1.0 — never absent, never fabricated as a fixed default.
- **SC-003**: Every detected event whose timestamp falls within a known replay segment is correctly flagged `is_replay = true`, and every event outside all replay segments is flagged `false`, with zero misclassifications against a test set of known replay boundaries.
- **SC-004**: Processing a full match's cleaned scoreboard timeline (~12,600 samples, a 3.5-hour match at 1 sample/second) completes in under 1 minute, matching `specs/technical_plan.md`'s Performance Targets budget for this module.
- **SC-005**: Running detection twice against the same input and configuration produces a byte-identical sequence of detected events.
- **SC-006**: Zero events are ever derived from a comparison involving a `null`-valued reading — verified by no crash and no fabricated event across a timeline containing leading/trailing/mid-timeline gaps.
- **SC-007**: Every Detected Event's `event_key` is unique within its Event Detection Result, and identical across repeated runs against the same input (consistent with SC-005) — verified by re-running detection against a timeline containing a boundary-and-milestone coincidence (Edge Cases) and confirming both resulting events have distinct, stable keys.

## Scope & Extensibility

This specification defines **Version 1** scope: `FOUR`, `SIX`, `WICKET`, and `TEAM_MILESTONE` are the only event types Module 5 emits. This is not a permanent ceiling on the architecture — it is the current ceiling on *detectable* event types, bounded by what Module 4/4a's data actually captures (see "Event Taxonomy & Detectability" in `specs/technical_plan.md`). The Processing Model's stage separation (Processing Model) and precedence model (FR-023) are deliberately structured so that adding a future event type (once a new data source, e.g. dismissal subtypes or per-batter score, is designed) is a change scoped entirely to the Event Rule Engine stage — it does not require reworking replay annotation, confidence assignment, or importance assignment. Adding a new event type remains out of scope for this spec and requires its own future amendment.

## Assumptions

- **Team name is out of scope for MVP** (`team` left `NULL`, FR-012): no module in the pipeline — not Scoreboard OCR, not the OCR Timeline Smoother — ever extracts a team name or abbreviation from the broadcast. This is the same category of gap Module 4 already documented for `innings` (`specs/005-scoreboard-ocr/spec.md` FR-008), just for a field with no existing heuristic workaround at all. A future module or an out-of-band CLI-supplied team name (at `cvip analyze` invocation time) would be needed if this is ever required — undesigned, not scheduled for MVP.
- **Innings number is derived via heuristic, not true innings-awareness** (FR-010, FR-011): Event Detection reuses the exact runs/wickets-both-drop heuristic Module 4 already established for suppressing its own monotonic validation checks. This inherits the same documented limitation as Module 4's own spec: severe OCR noise that slips past Module 4a's smoothing and coincidentally drops both `runs` and `wickets` mid-innings would be misread as an innings transition. This is an accepted, documented limitation, not a silent gap.
- **A four/six is detected purely from a same-ball runs delta, with no shot-type attribution**: Module 4's OCR never captures whether a boundary came from the bat, a bye, a leg-bye, or an overthrow — only the resulting team runs total. Any single-ball 4 or 6 run delta (FR-004/FR-005/FR-006a) is treated as a boundary event regardless of how it was actually scored, since no data source exists to distinguish these cases.
- **No video/frame access is required for this module** (FR-017): consistent with Module 4a's own precedent as the first modules whose entire input is already-extracted, in-memory data — this module's own `/speckit-plan` is expected to confirm no new external dependencies are needed.
- **Module 5's "cleaned timeline + raw OCR result" two-input design corrects an inconsistency found in `specs/technical_plan.md`**: the original text assumed Module 5 could read `ocr_confidence`/`parse_confidence` directly off the smoothed sequence, but Module 4a's finalized contract (`specs/006-ocr-timeline-smoother/contracts/ocr_timeline_smoother_contract.md`) intentionally carries no confidence fields on its public output. `specs/technical_plan.md` has been updated accordingly (see its Module 5 section) as part of this specification.

## State Transition Detection (post-implementation amendment)

**Background**: a real-match validation against official ball-by-ball commentary and scorecard ground truth (57 known FOUR/SIX/WICKET events) found the initial implementation detected only 3/57 (5.3% recall), and separately produced 220 spurious `TEAM_MILESTONE` events from a single corrupted OCR reading in one run. Both symptoms traced to the same root cause: the Comparison Engine (FR-001, Processing Model) diffed consecutive *array positions* in the 1fps-sampled cleaned timeline, not consecutive *distinct score states*. A ball is bowled roughly every 15-30+ real seconds, so two array positions exactly one second apart almost always describe the *same* delivery. Measured on a real match's cleaned timeline: 99.7% of consecutive-position comparisons showed no change in score at all, versus 0.1% that were a genuine single-ball advance and 0.1% that skipped one or more balls. FR-004 through FR-011's own rules were never the problem — they were being asked the wrong question, at the wrong granularity, almost every time. Separately, one comparison whose OCR misread ("151" read as "1153") still passed FR-006a's same-ball check produced a `runs_delta` large enough to cross 20+ `TEAM_MILESTONE` thresholds in a single comparison — FR-008 had no ceiling on how large a plausible delta could be.

**This is an addition ahead of the Comparison Engine, not a rewrite of it**: FR-004 through FR-011 and FR-023's precedence chain (`_process_comparison()`) are unchanged — they still receive exactly two readings and apply exactly the same rules. What changed is what those two readings *are*: previously the immediately-preceding and current cleaned-timeline array entries; now the most recently *accepted* distinct score state and the next one, with a new discard step in between for implausible transitions.

**The architecture** (`src/cvip/events/state_transition.py`, `state_transition_models.py`):

```
OCR Timeline (one CleanedScoreboardSample per raw sample)
      |
      v
State Transition Detector  (state_transition.py)
      |
      v
Distinct Score States (ScoreState)
      |
      v
Comparison Engine  (detection.py's _process_comparison() -- unchanged)
      |
      v
Detected Events
```

- **`ScoreState`** (`state_transition_models.py`): the same four core fields as `CleanedScoreboardSample` (`runs`, `wickets`, `over_number`, `ball_in_over`, all non-Optional `int`) plus `batter`/`non_striker`/`bowler` from the group's first sample, and provenance fields new to this amendment: `first_seen_timestamp`/`last_seen_timestamp` (the span of raw samples this state was visible across), `sample_count`, and `average_ocr_confidence` (the mean `ocr_confidence` of the raw readings collapsed into this state, looked up via the existing raw-OCR-by-timestamp input). A `.timestamp_seconds` property aliases `first_seen_timestamp`, so it is a drop-in replacement for `CleanedScoreboardSample` everywhere the Comparison Engine and `EventEvidence` already used `.timestamp_seconds`.
- **`is_same_score_state(a, b)`**: the sole definition of "the same delivery's score" — compares the four core fields only. Isolated in its own function (rather than inlined into the grouping loop) so a future amendment (innings-awareness, Super Overs, manual scoreboard corrections) changes one function, not the collapsing algorithm around it.
- **`detect_state_transitions(samples, raw_by_timestamp)`**: a single forward pass that (1) drops any sample with a null core field entirely — it carries no usable state information, so it neither starts nor ends a group, and a transient one-sample gap between two identical readings no longer needlessly splits them into two states (a *stronger* guarantee than the pre-amendment "skip that one comparison" behavior); (2) groups consecutive samples sharing the same state via `is_same_score_state`; (3) flushes each group into one `ScoreState`. A state that later recurs with a non-adjacent, different state in between is **not** retroactively merged with its earlier occurrence — only consecutive runs collapse.
- **Anomaly guardrail — `is_anomalous_transition(previous, current)`**: Event Detection's own second layer of defense, distinct from Scoreboard OCR's `_validate_reading()` (which only ever rejects a *decrease*, never bounds an implausibly large increase). Two independent checks, using the states' own over/ball delta rather than a single flat constant: `wickets_delta > MAX_PLAUSIBLE_WICKETS_PER_TRANSITION` (3 — a hat-trick's practical ceiling, generous even across a multi-ball OCR gap), and `runs_delta` exceeding `balls_advanced * MAX_PLAUSIBLE_RUNS_PER_BALL` (11 runs/ball, a SIX plus a generous extras allowance) — falling back to a single-ball ceiling when the ball advance itself isn't forward-computable (e.g. an over/ball regression, already handled separately by FR-010's innings-transition heuristic or rejected upstream by Scoreboard OCR validation).
- **Last-good-baseline discard** (`detection.py`'s `run()`): when `is_anomalous_transition()` fires, that transition is discarded — no event is derived from it — and, critically, the corrupted state does **not** become the baseline for the next comparison; the next state is instead compared against the last *accepted* good state. This mirrors the same "baseline poisoning" class of bug already fixed independently in Scoreboard OCR's own validation, and is what stops one bad frame from producing dozens of spurious downstream comparisons.

**Documented assumptions** (also in `state_transition.py`'s module docstring): consecutive identical score states represent the same delivery held on screen by the broadcast overlay, not coincidentally-identical distinct events (a genuine innings transition is never mistaken for this, since it always also shows a different over/ball/wickets); the first occurrence of a state best represents "when the event became visible on screen" for clip-window purposes, consistent with `config/default.yaml`'s existing pre_roll/post_roll OCR-lag calibration; 1fps OCR sampling is significantly higher-frequency than the scoreboard's own per-delivery update rate, which is what makes collapsing an information-preserving transform rather than a lossy one; a state change reflects *that* a real event occurred, never *which* one — that determination remains the Comparison Engine's exclusive, unchanged responsibility.

**Diagnostics** (FR-028, revised): `output_summary` now reports `raw_sample_count`, `distinct_state_count`, `state_reduction_pct`, `comparisons_processed`, `anomalous_transitions_discarded`, and `anomalous_transition_examples` (up to 10, human-readable, e.g. `[84-0/17.3@2031s -> 1153-4/17.4@4236s: wickets_delta=4 exceeds plausible ceiling (3)]`) in place of the pre-amendment `comparisons_skipped` field. `comparisons_skipped` is removed, not merely renamed: the null-core check it counted (originally FR-009's `_has_null_core()` guard inside `_process_comparison()`) is now unreachable dead code, since `detect_state_transitions()` already drops every null-core sample before a `ScoreState` is ever constructed, and `ScoreState`'s core fields are non-Optional — the check and its counter were removed together rather than left as always-zero dead weight (constitution: fail fast and keep the diagnostics record honest, not decorative).

**Broadcast-format independence**: `ScoreState`/`CleanedScoreboardSample` carry no parser-identity field, and neither `state_transition.py` nor `detection.py` branch on which Scoreboard OCR parser (`GenericBroadcastParser`/`ClubBroadcastParser`/`SeparateTokenBroadcastParser`, `specs/005-scoreboard-ocr/spec.md`'s Parser Extension Architecture) produced a given reading — format selection happens entirely upstream, before this module's input even exists. This is a structural guarantee, verified by the full regression suite (`pytest`, no format-specific special-casing exists anywhere in this module to regress) rather than a per-format duplicate test suite that would just re-exercise the same generic collapsing/comparison logic three times.

**Extensibility, not yet implemented**: `ScoreState.sample_count`/`average_ocr_confidence` are included now specifically so a future confidence-scoring amendment (weighting a state by how many raw samples/how high-confidence the readings that produced it were, multi-frame voting, temporal-consistency checks) does not require another refactor of the collapsing step itself — only a new consumer of fields already being computed. No such consumer exists yet; this is a documented placement decision, not a partially-built feature.

**Impact measurement** (real second-match data, `third_match_raw_ocr_v2.csv`/`ground_truth_v2/`, before vs. after, config unchanged — `team_milestone_interval=50`, same ranking map):

| Metric | Before (array-position comparison) | After (State Transition Detection) |
|---|---|---|
| Raw OCR samples | 11,434 | 11,434 |
| Cleaned timeline samples | 11,434 | 11,434 |
| Distinct score states | *(concept did not exist)* | 33 (99.7% reduction from raw samples — matches the discovery measurement above) |
| Comparisons processed | ~11,433 (one per array position) | 26 |
| Anomalous transitions discarded | *(no guardrail existed)* | 6 |
| Total events emitted | 223 | 4 |
| `TEAM_MILESTONE` events | 220 (219 spurious, from the single corrupted-reading incident above) | 1 |
| `FOUR`/`SIX`/`WICKET` events | 3 | 3 |
| True positives (vs. 57 ground-truth events) | 3 | 3 |
| Recall | 5.3% | 5.3% |
| False positives (scoring events) | 0 | 0 |
| Precision (scoring events) | 100% (3/3) — but overall output was 98.7% spurious `TEAM_MILESTONE` noise | 100% (3/3), and overall output is now free of the milestone flood |
| Processing time | <20ms | <20ms |

**Wickets-ceiling fix (PR #13 review finding)**: `is_anomalous_transition()`'s wickets check originally used the same flat `MAX_PLAUSIBLE_WICKETS_PER_TRANSITION` (3) ceiling regardless of how many balls separated the two states — unlike the runs check just below it, which was already scaled by `balls_advanced`. This meant a legitimate multi-over OCR gap containing more than 3 real wickets (e.g. `30-1/13.4` -> `112-5/24.3`, a plausible gap on a broadcast with heavy OCR loss) was wrongly discarded as anomalous, and because discarding never advances the baseline, every subsequent state kept comparing against the same stale pre-gap baseline and was rejected too — capable of blacking out the rest of the innings rather than merely missing the wickets inside one gap. Fixed by scaling the wickets ceiling the same way the runs ceiling already is: `balls_advanced * MAX_PLAUSIBLE_WICKETS_PER_BALL` (1 wicket/ball), falling back to the flat hat-trick ceiling only when the ball advance itself isn't forward-computable — same fallback rationale the runs check already documented. Verified by `tests/unit/test_state_transition.py`'s updated wickets-delta tests (a no-ball-advance case still uses the flat ceiling; a multi-ball gap with a legitimate 4-wicket delta is no longer anomalous; a delta exceeding one wicket per ball is still rejected even across a gap). Not yet re-measured against a full real-match run — this closes an architectural gap the previous impact measurement's "6 anomalous transitions discarded" already partly reflects (some of that count was almost certainly this bug, not genuine noise), but a fresh before/after table would need another full OCR pass to attribute correctly.

Recall did **not** improve on this specific match, and that is a real, separate finding rather than a shortfall in this amendment: the Smoother's own diagnostics for this run report `held_forward_unusable_count=9491` of 11,434 raw samples — only 33 genuinely distinct, valid score states exist anywhere in this match's OCR data, against roughly 150+ real deliveries. State Transition Detection correctly compares every state that *does* exist; it cannot manufacture states an upstream OCR extraction never captured. What this amendment demonstrably fixed is the architectural defect it targeted — the granularity mismatch and the unbounded-anomaly flood — verified by both the unit/integration test suite (`tests/unit/test_state_transition.py`, `tests/integration/test_event_detection_e2e.py`'s State Transition Detection integration section) and this real-match re-run: the 220-event `TEAM_MILESTONE` incident is eliminated, and the module's output is now trustworthy rather than dominated by noise. The residual low recall on this particular match is now a cleanly isolated, separate, open problem in upstream OCR extraction quality for this broadcast (consistent with this same video's already-documented heterogeneous-background thresholding difficulty, `specs/005-scoreboard-ocr/spec.md`) — not a Event Detection comparison-logic problem, which is a narrower and more actionable diagnosis than existed before this amendment.
