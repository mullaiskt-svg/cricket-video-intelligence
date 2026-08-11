# Feature Specification: Anchor Validation for Timeline Alignment

**Feature Branch**: `014-anchor-validation`

**Created**: 2026-08-07

**Status**: Draft

**Input**: User description: "Anchor Validation for Timeline Alignment (specs/013-match-metadata-validation follow-on). A correctness fix to Stage 2 (Timeline Alignment) of the already-implemented, merged Structured Match Metadata Validation layer, discovered via real-world validation against the Wild Wanderers vs Phoenix Firehawks match. The current alignment process commits to the nearest available scoreboard reading for a metadata event's video timestamp without independently checking whether that reading is trustworthy, which produces confidently-wrong timestamps (not just missed events) when the underlying broadcast OCR is unreliable — 6 of 33 recovered events on this match were placed out of chronological order, including one event anchored 35 minutes away from its true position. The fix must introduce an explicit validation step that only accepts an anchor when independent evidence (OCR quality, score-state consistency, timeline ordering, neighboring anchors) supports it, must classify every result by confidence rather than a single anchored/unanchored flag, must leave events unanchored rather than wrongly anchored when evidence is insufficient, must report rich diagnostics for anything rejected, and must remain fully generic — no logic tied to a specific team, match, over, or broadcaster."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Highlights are never built from a wrong moment in the video (Priority: P1)

A user has analyzed a match, supplied the official ball-by-ball commentary, and run event recovery to fill in what the on-screen scoreboard reading missed. When they generate highlights, every recovered clip must show the event the commentary actually describes. Today, some recovered clips show unrelated singles, wides, or dead balls because the event was anchored to the wrong point in the video — a direct consequence of trusting a scoreboard reading that looked plausible in isolation but wasn't actually corroborated by anything.

**Why this priority**: This is the core trust problem. A highlight reel with a handful of correct clips is useful; a highlight reel where some clips are confidently wrong is worse than a shorter, all-correct one, because the user cannot tell which clips to trust without watching every one.

**Independent Test**: Run recovery on a match with known-poor broadcast OCR quality and a supplied commentary file. Verify that every event which ends up eligible for highlight generation lands within its expected delivery window in the video, and that events lacking sufficient supporting evidence are withheld rather than recovered at a guessed timestamp.

**Acceptance Scenarios**:

1. **Given** a metadata event whose only supporting scoreboard reading has very low OCR quality and no corroborating signal, **When** alignment runs, **Then** the event is left unanchored and is not eligible for automatic highlight generation.
2. **Given** a metadata event whose candidate timestamp would place it earlier in the video than an already-accepted event from an earlier point in the same innings (with no innings break or other recognized break in play to explain it), **When** alignment runs, **Then** the candidate is rejected rather than accepted.
3. **Given** a metadata event whose candidate scoreboard reading has strong OCR quality and is consistent with the surrounding score progression and timeline order, **When** alignment runs, **Then** the event is anchored and classified as high or medium confidence, and remains eligible for recovery exactly as it is today.

---

### User Story 2 - A rejected or unresolved event comes with a clear, specific reason (Priority: P2)

When a metadata event is not recovered, the user reviewing the validation output needs to understand why, without digging through raw database tables. Today, the only outcome recorded is "no reading found" or a silently-accepted (possibly wrong) timestamp — there is no record of a plausible-looking candidate that was considered and rejected, or why.

**Why this priority**: Without this, users (and future maintainers) cannot distinguish "this match's OCR is genuinely too poor to recover this ball" from "the algorithm made a mistake," which makes both trust-building and debugging impossible. This depends on User Story 1 existing first (there must be a rejection decision to explain).

**Independent Test**: Run validation on a match where at least one metadata event has no sufficiently trustworthy candidate. Confirm the validation report includes, for that event, the best candidate that was considered, its OCR quality, how well it fit the expected score progression, whether it preserved chronological order, and a specific stated reason it was not accepted.

**Acceptance Scenarios**:

1. **Given** a metadata event with a candidate reading that fails the OCR quality bar, **When** validation completes, **Then** the report identifies that candidate and states OCR quality as the reason for rejection.
2. **Given** a metadata event with a candidate reading that would break chronological order, **When** validation completes, **Then** the report states the ordering conflict as the reason, naming the neighboring anchor it conflicts with.
3. **Given** a metadata event with no candidate reading at all within the search range, **When** validation completes, **Then** the report distinguishes "no candidate existed" from "a candidate existed but was rejected."

---

### User Story 3 - A user can judge, at a glance, whether metadata recovery is worth trusting for a given match (Priority: P3)

Before relying on recovered events for highlight generation, a user wants a summary: how many commentary events were there, how many were confidently recovered, how many were withheld, and how much of the original detection accuracy problem this run actually solved. Today's output reports only recall/precision against the final (possibly wrongly-timestamped) event set, with no visibility into how many recovered events were trustworthy versus guessed.

**Why this priority**: This is the least urgent of the three — it's a reporting convenience that helps the user decide how much manual review to do, whereas Stories 1 and 2 are about correctness and explainability of the results themselves. It depends on both prior stories: it summarizes the accept/reject decisions from Story 1 using the reasoning captured in Story 2.

**Independent Test**: Run validation end-to-end on any match with supplied metadata and confirm the summary reports total metadata events, anchored count broken down by confidence level, unresolved/rejected count, how many ordering conflicts were caught and prevented, and the resulting recall/precision figures.

**Acceptance Scenarios**:

1. **Given** a completed validation run, **When** the user reviews the summary, **Then** they see counts for total metadata events, high-confidence anchors, medium-confidence anchors, low-confidence anchors, and unresolved events, without needing to query the database directly.
2. **Given** a completed validation run where the alignment process caught and rejected one or more chronologically-inconsistent candidates, **When** the user reviews the summary, **Then** the number of such prevented conflicts is reported explicitly.

---

### Edge Cases

- What happens when a metadata event is the very first event of an innings, so there is no earlier accepted anchor in that innings to check ordering against? The ordering check simply has nothing to compare against yet; the event is judged on its other evidence (OCR quality, score-state consistency) alone.
- How does the system handle a legitimate break in play (innings change, super over) where the next event's timestamp is expected to jump backward relative to naive over.ball continuation? These must be recognized as valid exceptions to the ordering check, not treated as violations.
- What happens on a match where broadcast OCR quality is uniformly poor across the entire video (as observed in real validation)? The system should end up with a low anchored rate and a high unresolved rate, correctly reflecting that this match's recovery is largely untrustworthy, rather than forcing a plausible-looking but wrong result.
- What happens when two different metadata events both have plausible candidates pointing at very similar timestamps (e.g., a wicket and a boundary recorded on the same ball)? Existing same-type/same-innings matching behavior is preserved; this feature only changes whether a candidate is accepted or rejected, not how candidates are initially found.
- What happens when a metadata event's true position is beyond the highest over ever observed in the scoreboard readings for its innings? This is already handled today as an out-of-range error and is unaffected by this feature.
- What happens to a match that has no supplied metadata at all? Nothing — this feature only activates when metadata-based recovery is explicitly requested by the user, exactly as today.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The alignment process MUST evaluate more than one piece of evidence — including but not limited to OCR reading quality, score-state consistency, and chronological consistency with other anchors — before accepting a candidate as the timestamp for a metadata event, rather than accepting the nearest or first available candidate.
- **FR-002**: The alignment process MUST NOT accept a candidate whose underlying scoreboard reading has insufficient OCR quality unless other evidence independently corroborates it.
- **FR-003**: When no candidate for a metadata event meets the acceptance bar, the event MUST be left unanchored rather than assigned a low-confidence or unsupported timestamp.
- **FR-004**: Every metadata event processed by alignment MUST be classified into exactly one of: High-confidence anchor, Medium-confidence anchor, Low-confidence anchor, or Unresolved/Unanchored.
- **FR-005**: Only High-confidence and Medium-confidence anchors MUST be automatically eligible for event recovery (and therefore for highlight generation).
- **FR-006**: Low-confidence anchors MUST NOT be automatically recovered; they MUST instead be excluded from automatic recovery and reported for optional user review.
- **FR-007**: The alignment process MUST verify that accepting a candidate anchor preserves increasing timestamps in over.ball order relative to every other anchor already accepted for the same innings.
- **FR-008**: A candidate that would violate chronological order MUST be rejected unless the violation is explained by a recognized break in play (at minimum: innings change, super over). The set of recognized exceptions MUST be evaluated generically (based on match structure), never by referencing a specific match, team, or over number.
- **FR-009**: For every metadata event that ends up rejected or unresolved, the system MUST report: the best candidate that was considered (if any), that candidate's OCR quality, its score-state consistency result, its chronological consistency result, and a specific, human-readable reason it was not accepted.
- **FR-010**: For every validation run, the system MUST report aggregate outcomes: total metadata events processed, total anchored, counts by each confidence tier, total unresolved/rejected, number of chronological-order violations detected, number of chronological-order violations prevented (i.e., caught before being committed), and the resulting recall and precision.
- **FR-011**: All validation rules MUST depend only on OCR quality signals, timeline/chronological consistency, score-state consistency, and metadata consistency. They MUST NOT reference or special-case any specific team name, match identifier, over number, or broadcaster.
- **FR-012**: The anchor validation behavior MUST be applied identically regardless of whether the result is consumed for accuracy reporting or for event recovery — there MUST be exactly one validation implementation shared by both.
- **FR-013**: Given identical inputs (match analysis, metadata file, and configuration), the alignment process — including every validation decision — MUST produce identical results on every run.
- **FR-014**: This feature MUST NOT change the behavior of match analysis or highlight generation when metadata-based validation/recovery is not explicitly invoked by the user.
- **FR-015**: Recovery and enrichment MUST remain explicit, user-triggered actions; this feature MUST NOT cause any event to be recovered or enriched automatically without the user requesting it.
- **FR-016**: A metadata event whose candidate reading has strong OCR quality and is fully consistent with score-state and chronological expectations MUST continue to be classified as a high-confidence anchor and remain eligible for automatic recovery — this feature MUST NOT reduce recovery of genuinely well-supported events.

### Key Entities *(include if feature involves data)*

- **Candidate Anchor**: A scoreboard reading being considered as the possible video-timestamp source for one metadata event, before validation has judged it.
- **Anchor Validation Result**: The outcome of judging a candidate anchor — its confidence classification (High/Medium/Low/Unresolved), which evidence signals supported or contradicted it, and (when not accepted) the specific reason.
- **Ordering Conflict**: A detected case where accepting a candidate anchor would break the expected relationship between over.ball order and timestamp order, absent a recognized break in play.
- **Validation Run Summary**: The aggregate report produced for a single validation run — counts of events by outcome and confidence tier, ordering conflicts detected/prevented, and resulting recall/precision.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On a match with unreliable broadcast OCR, none of the events made eligible for automatic highlight generation are placed at a point in the video inconsistent with their true chronological order — eliminating the "confidently wrong" clip problem observed in real validation (6 of 33 recovered events out of order before this feature).
- **SC-002**: 100% of events eligible for automatic highlight generation preserve over.ball-to-timestamp chronological ordering, except where a recognized break in play explains the exception.
- **SC-003**: For every metadata event not recovered, a user reviewing the validation report can identify a specific, human-readable reason without inspecting raw data — zero unexplained gaps.
- **SC-004**: A user can determine, from the validation report alone, how many metadata events were confidently recovered versus withheld, broken down by confidence tier, without needing any additional investigation.
- **SC-005**: Re-running validation against unchanged inputs (same match analysis, same metadata file, same configuration) produces identical anchoring and classification results every time.
- **SC-006**: On a match with strong, reliable broadcast OCR, the set of events recoverable at high confidence does not shrink compared to before this feature — correctness validation does not come at the cost of losing already-trustworthy recoveries.

## Assumptions

- The existing OCR-quality configuration (`ocr.min_confidence`) establishes the general reliability bar the platform already considers meaningful for scoreboard readings; the exact thresholds separating High/Medium/Low confidence tiers are calibration details to be determined during planning against real match data, consistent with how other perceptual thresholds in this pipeline (e.g., scene-detection sensitivity) were calibrated — not a business decision requiring separate sign-off.
- "Recognized break in play" for the ordering check is limited, at launch, to innings changes and super overs — the two structural cases already anticipated by the existing match model. Additional cricket-specific exceptions (e.g., rain delays affecting over numbering) are out of scope unless they are shown to produce false ordering-violation rejections in practice.
- This feature modifies only the shared Timeline Alignment stage of the existing Structured Match Metadata Validation layer; it does not introduce a new user-facing command or change the existing `cvip validate` invocation surface, though the reported output will be richer.
- Score-state consistency checks operate on whatever runs/wickets data is actually present on a scoreboard reading; readings that lack this data are judged on the remaining signals (OCR quality, chronological consistency) rather than being penalized for a missing field.
