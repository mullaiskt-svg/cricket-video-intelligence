# Feature Specification: Robust Innings Transition Detection

**Feature Branch**: `015-innings-transition-detection`

**Created**: 2026-08-08

**Status**: Draft

**Input**: User description: "Robust Innings Transition Detection — a follow-on investigation from specs/014-anchor-validation. That feature's own real-data validation traced a highlight-generation defect (recovered clips showing the wrong team) all the way upstream, past the metadata alignment layer, to a root cause confirmed by directly inspecting video frames: the pipeline's innings-transition detection produced five distinct match segments for a real two-innings match instead of two, because its only signal — a scoreboard reading where runs and wickets simultaneously decreased — misfired twice on noisy OCR frames mid-innings, and the same weak heuristic is implemented three separate times across the codebase with inconsistent guardrails. The real second innings exists in the data but under the wrong segment label, so nothing that later searches for 'innings 2' ever finds it. This feature replaces that single-signal, un-gated heuristic with a robust, generic, multi-signal, structurally-bounded transition model."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - A Match Is Never Split Into More Segments Than It Actually Has (Priority: P1)

A user analyzes a real match end-to-end and later runs any feature that depends on knowing which innings a given moment in the video belongs to (accuracy reporting, event recovery, highlight generation). Today, noisy broadcast footage can cause the system to invent extra, spurious match segments partway through an innings — silently shifting the real second innings into a segment label nothing else ever looks for, so recovered content ends up attributed to the wrong team without any visible error.

**Why this priority**: This is the correctness failure that was actually observed on real data and is the reason this feature exists — a two-innings match must never be represented internally as anything other than the number of innings it actually has, whatever the raw broadcast noise looks like.

**Independent Test**: Run analysis against a match recording known to contain OCR noise that previously caused spurious segment increments (the real match that surfaced this defect). Confirm the resulting number of distinct match segments matches the real number of innings, and that the genuine second-innings start is correctly labeled as segment 2, not some later number.

**Acceptance Scenarios**:

1. **Given** a match broadcast with occasional garbled scoreboard readings that momentarily show an implausible low score mid-innings, **When** the match is analyzed, **Then** the system does not treat that momentary reading as the start of a new segment.
2. **Given** a match that has genuinely finished its first innings and started its second, **When** the corresponding scoreboard reading is reached, **Then** the system correctly recognizes and labels this as the start of segment 2.
3. **Given** a match recording that has already produced one spurious extra segment earlier in processing, **When** a later, genuine innings transition occurs, **Then** it is still labeled as segment 2 (or whatever the correct ordinal is for a real transition), not inflated by the earlier error.

---

### User Story 2 - One Misread Frame Never Compounds Into Multiple Errors (Priority: P2)

Today, the moment a spurious transition is (wrongly) accepted, that same bad reading becomes the reference point used to judge every subsequent reading — so one bad frame can directly cause a second, unrelated bad decision shortly after, compounding a single OCR error into a cascading failure.

**Why this priority**: This is a distinct failure mode from Story 1's root cause (a bad *decision*) — it's about *containing the blast radius* of any bad decision that does occur, whatever future improvements are made to the decision logic itself. Depends on Story 1 existing conceptually, since it's about the same detection process, but is independently valuable: even a much-improved detector will occasionally see a genuinely ambiguous frame, and this story ensures that single ambiguous frame can't cascade.

**Independent Test**: Feed a sequence of readings containing one implausible reading immediately followed by more readings consistent with the innings genuinely continuing unchanged. Confirm the implausible reading is not treated as a new reference point for judging what comes after it.

**Acceptance Scenarios**:

1. **Given** a reading that fails to meet the evidence bar for a genuine transition, **When** the system evaluates the next reading, **Then** it is compared against the last *trusted* reading, not the rejected one.

---

### User Story 3 - A Match Can Never Be Segmented Into More Parts Than Are Structurally Possible (Priority: P3)

Even with a better decision rule, a maintainer wants a hard guarantee: whatever the input noise looks like, the system cannot report more match segments than the format allows. This is a backstop independent of how good the per-transition judgment is.

**Why this priority**: This is defense in depth, not the primary fix — Story 1 (better judgment) should mean this backstop is rarely if ever exercised in practice, but it converts "the detector made a mistake" from a silent data-quality defect into a visible, boundable condition. Lower priority than Stories 1-2 because it only matters once the decision logic has already gone wrong.

**Independent Test**: Feed a sequence of readings engineered to trigger more transition-like patterns than a real match could have. Confirm the system never reports more segments than the configured maximum, and surfaces the fact that additional transition-like evidence was seen but disregarded.

**Acceptance Scenarios**:

1. **Given** a stream of readings that would, under the old single-signal heuristic, produce more segments than the match format allows, **When** processed under the new detection, **Then** the number of reported segments never exceeds the configured maximum.

---

### Edge Cases

- What happens during a genuine innings break (players off the field, no live score changing) or a rain delay (a long gap with no new readings at all)? The system must not force a transition decision purely because time has passed with no data — it remains in its current segment until it sees convincing evidence of a real transition, whenever that arrives.
- What happens if the broadcast never shows a fully clean, high-confidence transition moment (e.g., persistent OCR trouble right at the exact moment the second innings starts)? The system should still be able to recognize the transition from a weaker but still-corroborated set of signals, rather than requiring perfection — see Functional Requirements for the specific evidence combination required.
- What happens on a broadcast format this platform hasn't seen before (different scoreboard layout)? Detection must not depend on which broadcast format is in use.
- What happens if a match is abandoned or ends after only one innings? The system should simply never see qualifying evidence for a second transition and remain correctly in segment 1 for the whole match.
- What happens with match formats that could have more than two innings? The maximum number of segments must be a configurable bound, not a hardcoded assumption of exactly two.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST determine how many match segments (innings) a given match's data represents based on multiple independent pieces of evidence, not a single measurement.
- **FR-002**: The system MUST NOT treat a single momentary reading, however it looks, as sufficient evidence of a genuine transition — a transition MUST be corroborated by the reading persisting across multiple consecutive observations before being accepted.
- **FR-003**: The system MUST evaluate whether an apparent score decrease is of a magnitude and shape consistent with a genuine innings reset, not merely "any decrease," using the same kind of plausibility reasoning already proven elsewhere in this platform for judging whether a score change is realistic.
- **FR-004**: The system MUST treat the match's over/ball position also resetting near the start as a required corroborating signal for a transition, not an assumed-but-unchecked implication of the score resetting.
- **FR-005**: The system MUST weigh the underlying reading quality (how legible/trustworthy the source data was) when deciding how much corroboration is required before accepting a transition — a lower-quality signal MUST require stronger corroboration than a high-quality one.
- **FR-006**: The system MUST enforce a hard, configurable maximum on the number of match segments it will ever report for one match, defaulting to the number of innings normal for this platform's current scope — no combination of noisy input may cause this bound to be exceeded.
- **FR-007**: When the system rejects a candidate transition, it MUST NOT use that rejected reading as the reference point for evaluating subsequent readings — only an accepted, trusted reading may serve as that reference point.
- **FR-008**: The transition-detection decision MUST be made by exactly one shared implementation, consumed identically everywhere in the pipeline that currently needs this decision — no call site may re-derive or independently vary the logic.
- **FR-009**: The system MUST require no signal beyond what is already extracted by the existing scoreboard-reading pipeline (score, wicket count, over/ball position, reading confidence) — it MUST NOT depend on new data extraction (such as team names or on-screen target text) being available.
- **FR-010**: A prolonged gap with no valid readings (e.g., an innings break or rain delay) MUST NOT, on its own, cause a transition to be accepted or rejected — the system MUST simply continue waiting for corroborated evidence whenever it next arrives.
- **FR-011**: The detection logic MUST behave identically regardless of which broadcast/scoreboard layout produced the underlying readings.
- **FR-012**: For every transition decision (accepted or rejected), the system MUST record enough detail to explain, after the fact, why it was accepted or rejected — mirroring this platform's existing convention of never leaving a significant automated decision unexplained.
- **FR-013**: Given the same sequence of readings and the same configuration, the transition decisions MUST be identical on every run.
- **FR-014**: This feature MUST NOT change the externally visible behavior or command-line surface of running a full match analysis — it is an internal correctness fix to how segments are labeled, not a new capability a user invokes directly.

### Key Entities *(include if feature involves data)*

- **Transition Candidate**: One reading that exhibits some evidence of a possible segment transition (a score/wicket decrease), before the full evidence-gathering and decision process judges it.
- **Transition Evidence**: The combined set of signals gathered about one transition candidate — magnitude/shape plausibility, over/ball reset corroboration, persistence across consecutive readings, and reading-quality weighting — used to reach an accept/reject decision.
- **Trusted Segment Baseline**: The most recently *accepted* reference point for the current match segment, used to judge all subsequent transition candidates — explicitly distinct from the most recently *seen* reading, which may have been rejected.
- **Segment Boundary Decision**: The recorded outcome of evaluating one transition candidate — accepted or rejected, plus the evidence and reasoning behind it (Key Entity satisfying FR-012).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On the real match that surfaced this defect, analysis produces exactly two match segments, with the genuine second-innings start correctly labeled as segment 2.
- **SC-002**: On that same match, both previously-observed spurious mid-innings transitions are no longer accepted as segment boundaries.
- **SC-003**: For every match previously analyzed and validated correctly (no known segmentation defect), re-running detection under the new logic produces the same segment count and boundaries as before — this fix does not regress matches that were already working.
- **SC-004**: Re-running detection against the same input data always produces identical segment boundaries.
- **SC-005**: For any transition decision a user or maintainer inspects, a specific, human-readable explanation of why it was accepted or rejected is available without needing to re-derive it from raw logs.
- **SC-006**: The maximum-segments safeguard can be demonstrated to hold even when fed a sequence of readings deliberately engineered to look like many transitions.

## Assumptions

- This platform's current real-world scope is two-innings club cricket matches; the configurable segment-count bound defaults to reflect that, without hardcoding the number "2" into the detection logic itself in a way that would need code changes (not just configuration) to support a different format later.
- The "plausibility of a score change" reasoning already used elsewhere in this platform's event-detection logic is a reasonable and proven foundation to build this feature's own transition-plausibility judgment on, adapted to this feature's own inputs rather than reused as a hard dependency across module boundaries (consistent with this platform's existing precedent of sharing a concept/shape between modules, not a hard import between unrelated pipeline stages).
- Extracting new on-screen signals (team name, target-score text) would likely make transition detection even more robust, but is explicitly out of scope for this feature — it is called out as a valuable follow-on, not folded in silently.
- "Multiple consecutive observations" (FR-002's persistence requirement) and the exact plausibility/magnitude thresholds (FR-003) are calibration details to be resolved during planning against real match data, following this platform's established practice of documenting such calibrations with their real-data rationale rather than treating them as arbitrary constants.
