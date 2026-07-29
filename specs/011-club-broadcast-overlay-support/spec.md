# Feature Specification: Club Broadcast Overlay Support (Scoreboard OCR Amendment)

**Feature Branch**: `011-club-broadcast-overlay-support`

**Created**: 2026-07-29

**Status**: Draft

**Input**: User description: "Amend Scoreboard OCR (Module 4, specs/005-scoreboard-ocr/) to support the compound-score, no-label overlay format used by CricHeroes-style club-cricket broadcasts, in addition to the originally-assumed generic broadcast layout. This is discovered, not hypothetical: verified against a real 40-minute club match recording, whose scoreboard overlay combines runs-wickets/overs.balls(total-overs) into one compound string (e.g. '0-0/0.0(20)') rather than separate clean '123/4' and '12.3' tokens the current parser's regexes require; has no 'B:'/'BOWLER:' text label preceding the bowler's name (the current parser's bowler-detection rule requires one); and has no asterisk or other text-visible convention marking which batter is on strike (the current parser's striker-detection rule requires a trailing '*') -- this broadcast style instead uses a subtle background-color gradient to indicate the striker, which is not reliably distinguishable from two 10-minutes-apart sample frames and would require real pixel-level color analysis to detect accurately. Given Event Detection (Module 5) derives FOUR/SIX/WICKET events purely from runs/wickets deltas -- not from bowler or striker identity, per its own spec -- and only uses the batter field for a WICKET event's secondary `player` attribution (not for detection itself), this amendment's required scope is narrower than full striker-accuracy: (1) parse the compound runs-wickets/overs.balls(total-overs) score string into the existing runs/wickets/over_number/ball_in_over fields; (2) parse a bowler name without requiring a preceding label, on a best-effort basis; (3) parse a batter (striker) name without requiring an asterisk, on a best-effort basis (e.g., the first-listed name), explicitly documented as a known-limitation heuristic rather than accurate strike detection -- matching this platform's own established pattern of documenting heuristic trade-offs rather than solving every case perfectly. This must not regress the original, already-tested generic-layout parsing path -- both formats need to keep working, selected automatically from the raw OCR text rather than via new caller-supplied configuration."

**Relationship to specs/005-scoreboard-ocr/**: This is an amendment, not a replacement. It extends the existing Scoreboard OCR module's structured-parsing stage (specs/005-scoreboard-ocr/spec.md FR-030) with a second, additional parsing path -- every existing requirement, entity, and failure-reason value from the original spec remains in force and unchanged except where this document explicitly says otherwise.

**Post-implementation amendment (real-video validation finding)**: This feature's own quickstart.md Steps 3/5 were run against the real First8Overs.mp4 recording after initial implementation. The result: score/name extraction worked as designed, but Event Detection recovered only 6 events (3 FOUR, 3 WICKET) from an 8-over innings -- implausibly few. Root-cause analysis (timeline dump of every accepted reading's `over_number`/`ball_in_over`/`runs`) found the cause was not this amendment's parsing logic, but `specs/005-scoreboard-ocr/spec.md` FR-030's original design: a reading with no locatable `batter` was rejected *in its entirety*, including an otherwise perfectly valid, monotonic score. Because this amendment's best-effort name heuristic fails more often on real, compressed footage than the original asterisk convention did, two-thirds of all readings were being discarded score-and-all, opening multi-ball gaps in the accepted-reading baseline. Event Detection's FOUR/SIX rule requires a *consecutive* single-ball advance between accepted readings (`specs/007-event-detection/spec.md`) -- so any boundary hit inside one of those gaps was silently dropped, never misclassified, just gone. This is what FR-012 below (and the corresponding code change in `_validate_reading()`) fixes: `batter` no longer gates the score fields. See FR-008, FR-012, and the updated Edge Cases/Success Criteria below for the precise, narrowed scope of this change relative to the original FR-030.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Detect Real Events From a Club-Cricket Broadcast (Priority: P1)

A user analyzing a club-cricket match recorded with a CricHeroes-style overlay gets a real, populated raw scoreboard timeline instead of one where every reading fails validation -- because the platform can now read this overlay's compound score format, not just the originally-assumed one.

**Why this priority**: This is the capability that was entirely missing before this amendment -- without it, this class of broadcast produces zero usable readings, which means Event Detection (Module 5) has nothing to diff and detects zero events, regardless of how good the rest of the pipeline is. Everything downstream of Scoreboard OCR depends on this working.

**Independent Test**: Feed a sampled frame whose raw OCR text contains a compound score string (e.g., `0-0/0.0(20)`, read as runs-wickets/overs.balls(total-overs-in-match)) and confirm `runs`, `wickets`, `over_number`, and `ball_in_over` are all correctly extracted -- where before this amendment none of them would parse at all.

**Acceptance Scenarios**:

1. **Given** a raw OCR reading containing a compound score string in the form `{runs}-{wickets}/{over}.{ball}({total_overs})`, **When** Scoreboard OCR parses it, **Then** `runs`, `wickets`, `over_number`, and `ball_in_over` are populated with the correct values.
2. **Given** a raw OCR reading containing the original spec's separate clean tokens (e.g., `123/4` and `12.3`), **When** Scoreboard OCR parses it, **Then** the result is identical to this amendment's behavior having never been added -- no regression to the already-tested original path (`specs/005-scoreboard-ocr/spec.md` FR-007, FR-012-FR-016).
3. **Given** a full club-cricket match recording using this overlay format, **When** the resulting cleaned timeline is handed to Event Detection unmodified, **Then** Event Detection successfully derives FOUR/SIX/WICKET events from it, the same as it would from the originally-assumed format.

---

### User Story 2 - A Batter Name Populates Even Without an Asterisk Convention (Priority: P2)

A user's readings from this overlay format no longer automatically fail validation just because the broadcast has no text-visible way to mark which batter is on strike.

**Why this priority**: The original spec treats a reading with no batter value as a hard structural-parse failure (`PLAYER_PARSE_FAILED`, `specs/005-scoreboard-ocr/spec.md` FR-030), which zeroes out `parse_confidence` for every single reading of a broadcast lacking the asterisk convention -- effectively disabling the whole timeline even though the runs/wickets/overs data (User Story 1) is now readable. This is a correctness-unblocking fix, not a new detection capability of its own.

**Independent Test**: Feed a raw OCR reading containing two player names with no asterisk or other text-visible striker marking, and confirm a `batter` value (and, when a second name is present, a `non_striker` value) is populated -- explicitly on a best-effort basis, not a verified striker determination.

**Acceptance Scenarios**:

1. **Given** a raw OCR reading containing two player names with no asterisk on either, **When** Scoreboard OCR parses it, **Then** `batter` is populated with one of the two names (best-effort, e.g. the first-listed) rather than being left absent.
2. **Given** the same reading, **When** a second player name is present, **Then** `non_striker` is populated with the other name.
3. **Given** the `batter` value produced under Acceptance Scenario 1, **When** the internal OCR Evidence record for that reading is inspected, **Then** it is explicitly marked as a best-effort attribution, distinguishable from the original format's asterisk-verified attribution.
4. **Given** a raw OCR reading where *no* player name can be located under either the original or this amendment's convention, **When** Scoreboard OCR parses it, **Then** it is still recorded as `PLAYER_PARSE_FAILED`, unchanged from the original spec's own behavior.

---

### User Story 3 - A Bowler Name Populates Without Requiring a Label (Priority: P3)

A user's readings from this overlay format get a `bowler` value even though the broadcast never prefixes the bowler's name with a `B:`/`BOWLER:` label.

**Why this priority**: `bowler` is not consumed by Event Detection at all (it derives events purely from runs/wickets deltas) -- this only completes the raw `scoreboard_readings` record for `cvip inspect-db`/`cvip export-timeline` purposes. Genuinely useful, but the platform's core value (User Story 1) doesn't depend on it.

**Independent Test**: Feed a raw OCR reading containing a player name in the position this overlay format uses for the bowler, with no preceding label, and confirm `bowler` is populated.

**Acceptance Scenarios**:

1. **Given** a raw OCR reading matching this amendment's overlay format, with a player name present where the bowler is shown but no preceding `B:`/`BOWLER:` label, **When** Scoreboard OCR parses it, **Then** `bowler` is populated with that name (best-effort).
2. **Given** a raw OCR reading matching the original spec's format, with a `B:`/`BOWLER:` label present, **When** Scoreboard OCR parses it, **Then** the original label-based extraction still applies, unchanged.

---

### Edge Cases

- A frame's raw OCR text matches *neither* the original spec's format nor this amendment's format (e.g., a third, still-different overlay style, or a severely garbled reading) -- falls through to the existing `PLAYER_PARSE_FAILED` / unparsed-numeric-fields behavior, exactly as it did before this amendment (User Story 2 Acceptance Scenario 4).
- A video whose overlay style changes partway through (e.g., a mid-match broadcast/graphics-operator switch) -- each reading is evaluated independently against both supported formats, so this requires no special handling beyond what already applies to any other per-frame variation.
- The compound score string's "total overs in the match" component (the `(20)` in `0-0/0.0(20)`) has no corresponding field in the existing `Scoreboard Sample` shape -- not captured by this amendment (see Out of Scope).
- **(Superseded by the post-implementation amendment, FR-012)** A reading where the compound score string parses correctly but no player name can be found at all is no longer `PLAYER_PARSE_FAILED` -- the valid score alone is now sufficient to accept the reading and advance the baseline; `batter` is simply absent on the resulting sample, exactly as it would be for any other unlocatable-but-non-essential field. `PLAYER_PARSE_FAILED` now fires only when *neither* a name *nor* any score field could be located at all (nothing usable was extracted from the reading).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST parse a compound score string in the form `{runs}-{wickets}/{over}.{ball}({total_overs})` into the existing `runs`, `wickets`, `over_number`, and `ball_in_over` fields (`specs/005-scoreboard-ocr/spec.md` FR-007), in addition to continuing to support the original spec's separate clean-token format.
- **FR-002**: System MUST NOT regress the original spec's clean-token parsing path (`specs/005-scoreboard-ocr/spec.md` FR-007, FR-012-FR-016) -- a reading in the original format MUST continue to parse identically to its pre-amendment behavior (Acceptance Scenario US1-2).
- **FR-003**: System MUST determine, per reading, which of the two supported score-string conventions applies directly from the raw OCR text itself -- no new caller-supplied configuration selects between them.
- **FR-004**: System MUST extract a `batter` value on a best-effort basis (e.g., the first-listed player name) when no asterisk or other text-visible striker-marking convention is present in the raw OCR text, so a reading is not automatically treated as `PLAYER_PARSE_FAILED` solely because that convention is absent (Acceptance Scenario US2-1).
- **FR-005**: The `batter` value produced under FR-004 MUST be recorded in the OCR Evidence's per-field detail (`specs/005-scoreboard-ocr/spec.md` FR-029) as a best-effort attribution, distinguishable from the original format's asterisk-verified attribution (Acceptance Scenario US2-3).
- **FR-006**: System MUST extract a `non_striker` value (the second-listed player name, when two are present) using the same best-effort convention as FR-004 (Acceptance Scenario US2-2).
- **FR-007**: System MUST extract a `bowler` value without requiring a preceding `B:`/`BOWLER:` text label, on a best-effort basis, when the raw OCR text otherwise matches this amendment's supported overlay format (Acceptance Scenario US3-1).
- **FR-008 (superseded by FR-012)**: ~~A reading where neither the original spec's format nor this amendment's format can locate any player name at all MUST still be treated as `PLAYER_PARSE_FAILED`~~ -- narrowed by FR-012 below: `PLAYER_PARSE_FAILED` now fires only when *neither* a name *nor* any score field is present. A reading with a valid score but no name is no longer `PLAYER_PARSE_FAILED`.
- **FR-009**: System MUST continue to apply the original spec's cricket-rule validation (the monotonic runs/wickets/over/ball checks and the innings-transition heuristic, `specs/005-scoreboard-ocr/spec.md` FR-012-FR-016) identically to readings structurally parsed via this amendment's format -- validation is agnostic to which parsing path produced the reading.
- **FR-010**: This amendment MUST NOT introduce any new `Validation Failure Reason` value -- readings parsed via either format use the existing taxonomy (`specs/005-scoreboard-ocr/spec.md` FR-031) unchanged. (Still true post-FR-012: `PLAYER_PARSE_FAILED`'s trigger condition is narrowed, not replaced with a new value.)
- **FR-011**: This amendment MUST NOT require any new caller-supplied configuration -- the existing Scoreboard OCR Request shape (ROI, preprocessing settings, minimum confidence, `specs/005-scoreboard-ocr/spec.md` Key Entities) is unchanged.
- **FR-012 (post-implementation amendment)**: System MUST NOT reject a reading's `runs`/`wickets`/`over_number`/`ball_in_over` fields solely because `batter` could not be located, for readings produced by *either* parsing path -- superseding `specs/005-scoreboard-ocr/spec.md` FR-030's original blanket batter gate. A reading whose score fields are present and pass the existing monotonic-rule checks (FR-009) MUST be accepted (`parse_confidence > 0`) and MUST advance the accepted-reading baseline, regardless of whether `batter` is populated. `PLAYER_PARSE_FAILED` (`specs/005-scoreboard-ocr/spec.md` FR-031) is retained, narrowed to fire only when a reading has *neither* a locatable name *nor* any score field at all -- i.e., nothing at all could be extracted from it. `batter`/`non_striker`/`bowler` remain `None` on the resulting sample exactly as before when unlocatable; a caller that needs name presence must check those fields directly rather than inferring it from `parse_confidence`. Discovered via this feature's own quickstart.md Steps 3/5 against a real recording (see "Post-implementation amendment" note above) -- without this, real-footage name-extraction failures were opening multi-ball gaps in the accepted-reading timeline that caused Event Detection to silently miss FOUR/SIX events spanning those gaps (SC-006).

### Key Entities

This amendment reuses every public entity from `specs/005-scoreboard-ocr/spec.md` (`Scoreboard Sample`, `OCR Evidence`, `Validation Failure Reason`, `Scoreboard OCR Request`/`Result`/`Diagnostics`/`Failure Reason`) verbatim -- no new public entity is introduced. One existing entity gains an internal detail:

- **OCR Evidence** (extended): its per-field parser output (`specs/005-scoreboard-ocr/spec.md` FR-029) now additionally distinguishes, for the `batter`/`non_striker` fields specifically, whether the value was determined via the original format's asterisk-verified convention or this amendment's best-effort convention (FR-005) -- an addition to the existing entity's internal detail, not a new public field on `Scoreboard Sample` itself.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A representative sample of readings from a video using this amendment's overlay format produces the same "zero hard failures, every frame yields exactly one sample" outcome the original spec already guarantees (`specs/005-scoreboard-ocr/spec.md` SC-003) -- replacing what was, before this amendment, a 100% `PLAYER_PARSE_FAILED` / entirely-unparsed-score outcome for this class of broadcast.
- **SC-002**: `runs`, `wickets`, `over_number`, and `ball_in_over` parse correctly from the compound score-string format across a representative sample of readings, verified against hand-checked expected values.
- **SC-003**: A representative video using the original clean-token format produces byte-for-byte identical parsing results before and after this amendment, verified by re-running the original spec's own existing test suite unchanged -- zero regression.
- **SC-004**: Given a batch of readings from this amendment's overlay format, a non-empty `batter` value is present in the resulting Scoreboard Samples wherever the raw OCR text contains at least one player name -- eliminating the automatic `PLAYER_PARSE_FAILED` this amendment fixes.
- **SC-005**: Event Detection (Module 5), run unmodified against a cleaned timeline derived from this amendment's parsing path, successfully detects FOUR/SIX/WICKET events from a representative club-cricket match recording -- verified end-to-end, not just at the OCR layer.
- **SC-006 (post-implementation amendment)**: A reading with a valid, monotonic score but no locatable `batter` MUST NOT open a gap in the accepted-reading baseline -- verified by feeding two consecutive readings (the first name-less-but-score-valid, the second bearing a name) through `_validate_reading()` and confirming the second reading's monotonic checks compare against the first reading's score, not against an older, stale baseline. This is the concrete mechanism behind closing the ball-by-ball gaps that caused FOUR/SIX events to go undetected on real footage (see "Post-implementation amendment" note above).

## Out of Scope

- **Improving raw OCR character-recognition accuracy or preprocessing tuning** for this or any other specific overlay's visual style (background gradients, font choices, graphic-adjacent text). A distinct concern from structured-field parsing -- the existing `ocr_confidence`/`parse_confidence` mechanism already tolerates an individually noisy reading without failing the run (`specs/005-scoreboard-ocr/spec.md` FR-011).
- **Accurate (non-best-effort) striker/non-striker determination** via pixel-level color analysis of the overlay. Explicitly deferred -- this amendment documents the same class of heuristic trade-off the original spec's own innings-transition heuristic already established as this platform's precedent (accept a documented limitation rather than solve every case).
- **Capturing the compound score string's "total overs in the match" component** (e.g., the `(20)` in `0-0/0.0(20)`) as a new field. Not part of the existing `Scoreboard Sample` shape; not required by Event Detection; deferred as a distinct future capability if ever needed.
- **Supporting overlay formats beyond the two now covered** (the original spec's format, and this amendment's). A future amendment's concern if/when a third distinct format is encountered.

## Assumptions

- **The two supported formats are distinguishable from each other by raw text shape alone** (e.g., the presence of a hyphen-and-parenthesized-total-overs pattern versus a clean `runs/wickets` token) -- the exact detection heuristic (e.g., try-both-patterns-per-reading versus format-lock-once-detected) is an implementation decision for `/speckit-plan`, the same way the original spec left "the specific bar for well-formed" to its own planning phase.
- **"First-listed player name" (FR-004) assumes the raw OCR text's left-to-right, top-to-bottom token order roughly preserves the overlay's own visual layout** -- consistent with the behavior observed in the real sample frames this amendment's discovery was based on, but not independently re-verified against every possible club-broadcast template.
- **This amendment is based on evidence from one real club-cricket broadcast recording**; other CricHeroes-style or similarly-templated overlays are expected, but not guaranteed, to share enough structural similarity for the same patterns to apply.
- **This amendment does not change the original spec's performance, determinism, offline/CPU-only, or diagnostics guarantees** (`specs/005-scoreboard-ocr/spec.md` FR-019 through FR-028) -- it only adds a second successful path through the existing structured-parsing stage (FR-030), so those guarantees extend to this amendment's format without needing to be independently restated.
