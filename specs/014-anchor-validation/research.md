# Research: Anchor Validation for Timeline Alignment

No `[NEEDS CLARIFICATION]` markers remained in spec.md, but the following design decisions were
made explicit here since they shape data-model.md and the contracts.

## Decision 1: Where Anchor Validation lives

**Decision**: A new file-set, `src/cvip/metadata/anchor_validation.py` +
`anchor_validation_models.py`, invoked internally by `alignment.py`'s `align()`. Not a new
pipeline stage, not directly callable from `orchestrator.py`/`cli.py`.

**Rationale**: 013's contract (`metadata_pipeline_contract.md`) already establishes Timeline
Alignment as "the ONE reusable component" Accuracy Analysis and Recovery both consume — adding
validation as an internal sub-step of that same component preserves that invariant automatically
(there is only ever one call path into validated results). The project's own precedent for
splitting one *concern* across multiple files without creating a new pipeline stage already
exists in `src/cvip/video/` (`scoreboard_ocr.py` + `scoreboard_parsers.py` +
`scoreboard_preprocessing.py`), so this is consistent with established practice rather than a new
pattern.

**Alternatives considered**:
- *Inline everything into `alignment.py`*: rejected — the file would grow to cover search,
  ranking, and multi-signal scoring, and existing per-module file-set conventions in this package
  favor splitting by concern once a module gains this much internal logic.
- *A new Stage between 2 and 3 in the pipeline contract*: rejected — Stage 3 (Accuracy Analysis)
  and Stage 4/5 (Recovery) both already consume `MatchAlignmentEvidence` as a black box; inserting
  a visible new stage would mean touching both call sites' contracts for no benefit, since the
  validation decision is entirely encapsulated in what `MatchAlignmentEvidence` already contains.

## Decision 2: Two-pass structure inside Stage 2

**Decision**: Split today's single-shot `_search_reading()` into two passes:
- **2a. Candidate ranking** (`alignment.py`, replacing `_search_reading`): for one metadata
  event, return *every* reading found within the existing tiered search (exact validated → exact
  any → radius-widened validated → radius-widened any), not just the first hit — ranked by tier,
  then by proximity, then by the reading's own `ocr_confidence` descending.
- **2b. Anchor validation** (`anchor_validation.py`, new): process metadata events **grouped by
  innings, sorted by `(over_number, ball_in_over)`** — not necessarily the input order — walking
  forward while maintaining the running set of already-accepted anchors for that innings. For
  each event, try its ranked candidates in order; accept the first one that clears every
  hard-reject check (§Decision 3); classify the accepted candidate's confidence tier; if none
  clear, the event is `UNRESOLVED` and the best-tried candidate plus every signal verdict is kept
  for diagnostics (spec FR-009).

**Rationale**: FR-007 requires checking a candidate against "every other anchor already accepted
for the same innings," which is meaningless without a defined processing order — over.ball order
is the only order that makes "already accepted" a coherent, deterministic concept regardless of
what order the metadata provider happened to list events in. Sorting by a fixed key
`(over_number, ball_in_over)`, with ties broken by stable input order, keeps this deterministic
(FR-013) without depending on dict/set iteration order.

**Alternatives considered**:
- *Validate in whatever order `ground_truth` arrives*: rejected — makes the ordering check
  order-dependent on upstream provider behavior, which is exactly the kind of hidden
  non-determinism 013's FR-018 was written to rule out.
- *Global two-directional pass (check both forward and backward neighbors before accepting
  anything)*: considered for the "neighbouring anchor consistency" signal, and partially adopted
  — see Decision 5. A full backward-looking re-validation pass (re-checking already-accepted
  anchors after a later acceptance) was rejected as unnecessary complexity: forward-only
  processing in over.ball order means every "already accepted" anchor a later event checks
  against is, by construction, chronologically earlier in the match — exactly the relationship
  FR-007 cares about.

## Decision 3: Signal set and hard-reject vs. soft-downgrade

**Decision**: Four independent signals are computed per candidate:

| Signal | Source | Verdict values |
|---|---|---|
| OCR quality | `scoreboard_readings.ocr_confidence` on the matched reading itself (never the smoother's `parse_confidence` alone — see Decision 4) | `HIGH` / `MEDIUM` / `LOW` / `INSUFFICIENT` |
| Score-state consistency | `runs`/`wickets` on the matched reading vs. the nearest already-accepted anchor in the same innings (see Decision 5 for the reused plausibility concept) | `CONSISTENT` / `UNKNOWN` (fields missing) / `INCONSISTENT` |
| Ordering | candidate's timestamp vs. every already-accepted anchor for the same innings | `PRESERVED` / `VIOLATION` |
| Neighbor pacing | candidate's implied seconds-per-ball rate vs. the innings' own observed pacing from nearby accepted anchors | `WITHIN_EXPECTED` / `SUSPICIOUS` / `UNKNOWN` (not enough neighbors yet) |

**Hard rejects** (candidate is skipped, next-ranked candidate tried instead): OCR quality
`INSUFFICIENT`, score-state `INCONSISTENT`, ordering `VIOLATION`. These three are the signals the
spec singles out as needing to *block* acceptance outright (FR-002, FR-007/FR-008) — a reading
that is genuinely illegible, genuinely contradicts the score, or genuinely breaks chronology
cannot be salvaged by other evidence.

**Soft signal**: Neighbor pacing never hard-rejects on its own (real match pacing legitimately
varies — an over break, a bowling change, a wicket celebration), but downgrades the resulting
confidence tier when `SUSPICIOUS` (Decision 6).

**Rationale**: Directly implements spec FR-001/FR-002 ("evaluate more than one signal... MUST NOT
accept a candidate whose reading has insufficient OCR quality unless other evidence independently
corroborates it"). Framing OCR quality as three-tiered rather than a single pass/fail bar is what
makes "corroboration" meaningful: a `LOW` (not `INSUFFICIENT`) OCR reading *can* still be accepted
if every other signal is strong, landing at a lower confidence tier rather than being rejected
outright — matching the spec's explicit language that corroboration, not a single higher bar, is
the mechanism.

**Alternatives considered**:
- *A single weighted numeric score crossing one threshold*: rejected — the spec explicitly wants
  a rich, per-signal breakdown for diagnostics (FR-009), and a single opaque score would collapse
  exactly the information Story 2 needs. Discrete per-signal verdicts are also trivially
  deterministic and trivially testable in isolation, matching Constitution Principle VII's
  contract-test-first requirement.

## Decision 4: OCR quality thresholds and config

**Decision**: New `metadata.anchor_validation` block in `config/default.yaml`:

```yaml
metadata:
  anchor_validation:
    ocr_confidence_high: 0.70    # reuses ocr.min_confidence -- the bar Scoreboard OCR (Module 4)
                                  # already treats as "reliable" for its own reporting
    ocr_confidence_medium: 0.50
    ocr_confidence_low: 0.35     # floor: below this, a candidate is INSUFFICIENT and
                                  # hard-rejected regardless of any corroborating signal
    neighbor_pacing_tolerance: 3.0   # candidate accepted if its implied seconds/ball is within
                                      # this multiplicative factor of the innings' own observed
                                      # recent pacing; SUSPICIOUS (soft downgrade) otherwise
```

**Rationale**: `ocr.min_confidence: 0.70` is already the project's established "this OCR reading
is reliable" bar, set for Module 4's own diagnostics — reusing it as the `HIGH` threshold means
Anchor Validation's strictest tier means the same thing everywhere in the codebase, rather than
inventing a second, disconnected notion of "confident OCR." `medium`/`low`/`neighbor_pacing_tolerance`
are new, project-specific constants calibrated against the two real matches already validated in
this session (`platinum_final_3rd`, avg OCR confidence 0.49; `ww_vs_pf`, avg 0.34) — chosen so
that `ww_vs_pf`'s known-bad anchors (documented `ocr_confidence` values of 0.27–0.45 in the
concrete evidence gathered for this feature) fall below `ocr_confidence_low` and are hard-rejected,
while `platinum_final_3rd`'s better readings are not systematically excluded. Documented in the
same "reasoned calibration from real samples, revisit if wrong" style as this file's existing
`scene_threshold`/`replay.confidence_threshold` comment blocks — not treated as a permanently
fixed number.

**Alternatives considered**:
- *A single high/low threshold, no medium tier*: rejected — collapses exactly the High/Medium
  distinction FR-004/FR-005 requires (both tiers are auto-recovery-eligible, but the report must
  still distinguish them per FR-010).
- *Per-broadcast-format thresholds* (mirroring `scoreboard_parsers.py`'s per-format
  architecture): rejected as premature — FR-011 requires validation to depend only on generic
  OCR/timeline/score-state/metadata signals, and there is no evidence yet (only two matches
  validated) that different broadcast formats need different confidence bars specifically for
  *validation*, as opposed to *parsing* (which already has per-format handling upstream). Revisit
  if a third match's data suggests otherwise.

**Self-caught correction, found during real-data validation (post-implementation)**: the values
above (0.70/0.50/0.35) were this decision's *original* calibration, reasoned from `ocr.min_confidence`
and the six known-bad anchors' own `ocr_confidence` values alone — without checking what the
*other 27*, correctly-anchored recovered events on that same match looked like. Doing that check
(prompted by a real re-run producing zero recovered events with the original values) found they
shared the same low `ocr_confidence` range as the six bad ones (0.27–0.47) — the two groups are
not separable by this signal at all on this broadcast, and the distribution of even
smoother-validated readings across the whole match has median 0.349, with 89% below 0.50. A fixed
absolute floor calibrated against one better-quality match (`ocr.min_confidence`'s own origin,
a different broadcast entirely) does not transfer. **Revised values**: `ocr_confidence_high:
0.60`, `ocr_confidence_medium: 0.35` (near this match's real median, so a typical validated
reading is only a single soft downgrade, not disqualifying), `ocr_confidence_low: 0.15` (the hard
floor, set below this match's own observed validated-reading minimum of 0.151, so it only
excludes genuinely unreadable/near-blank frames rather than merely below-average ones on an
already-poor broadcast). This is still a two-match calibration, not an exhaustively tuned one —
revisit again once a third match's data is available, same as before.

## Decision 5: Score-state consistency reuses an existing plausibility concept

**Decision**: The score-state consistency signal reuses the *concept* already implemented for
Event Detection's own anomaly rejection (`src/cvip/events/state_transition.py`'s
`is_anomalous_transition` — a "plausible ceiling" on runs/wickets delta per ball advanced) rather
than inventing a new algorithm. `anchor_validation.py` implements its own function operating on
`scoreboard_readings` dict rows and the innings' running accepted-anchor state (a structurally
similar but independently-typed check, since `state_transition.py`'s types
(`ScoreState`/`CleanedScoreboardSample`) belong to a different module and different pipeline
stage) — not a shared import, but the same reasoning: a runs/wickets increase larger than what a
plausible number of balls could produce is evidence the two readings don't belong to the same
part of the match.

**Rationale**: This concept is already proven correct on real data (it's live in production
Event Detection today) and reusing its reasoning keeps "what counts as an implausible score jump"
consistent across the codebase rather than defining it twice with potentially different
numbers. Matches this project's established structural-typing precedent (`specs/010-event-database/
research.md` Decision 8, also cited by 013's own `data-model.md`) of sharing a *shape*, not a
hard dependency, between modules that operate on the same underlying concept from different
pipeline stages.

**Alternatives considered**:
- *Import and call `state_transition.py`'s function directly*: rejected — its signature is typed
  against `ScoreState`, an Event Detection-internal type built from a different upstream
  (`CleanedScoreboardSample`), not from `scoreboard_readings` rows or `MetadataEvent`s. Coercing
  types across module boundaries for this would create exactly the "awkward cross-package
  coupling" CLAUDE.md's package-layout section warns against.

## Decision 6: Confidence tier classification rule

**Decision**: Deterministic rule table, evaluated only for candidates that already cleared every
hard-reject check:

- **HIGH**: OCR quality `HIGH`, score-state `CONSISTENT` or `UNKNOWN`, neighbor pacing
  `WITHIN_EXPECTED` or `UNKNOWN`.
- **MEDIUM**: clears hard-reject checks but does not qualify for `HIGH` — e.g. OCR quality
  `MEDIUM`, or neighbor pacing `SUSPICIOUS`, or the search tier (existing
  `AlignmentConfidenceTier`) is `NEARBY_BALL_RADIUS_N` rather than an exact-ball match.
  Downgrading a single soft signal at a time from `HIGH` is sufficient to land here.
- **LOW**: clears hard-reject checks only marginally — OCR quality `LOW` *and* at least one other
  signal is also not fully clean (e.g. `SUSPICIOUS` pacing, or a wide-radius search tier). Present
  in the result set (never silently dropped) but excluded from automatic recovery per FR-006.
- **UNRESOLVED**: no candidate cleared the hard-reject checks at all.

**Rationale**: A small, explicit rule table (not a weighted sum) keeps classification trivially
deterministic and trivially unit-testable per rule (Constitution Principle VII), and mirrors how
`AlignmentConfidenceTier` itself is already "a faithful description of which tier the search
succeeded at... not a manufactured continuous score" (existing docstring in
`alignment_models.py`) — this feature's new tier follows the same design philosophy for the
validation *decision* that the existing tier already follows for the *search*.

**Alternatives considered**: A continuous 0–1 confidence score was considered (closer to a
traditional ML-style confidence output) but rejected — spec success criteria (SC-004) require a
user to read tier counts directly off a report, and a continuous score would need an arbitrary
cut line to produce that anyway, so the discrete table is strictly simpler for identical
expressive power at this feature's actual scope.

**Self-caught correction, found during real-data validation (post-implementation)**: the rule
table as first implemented special-cased `ocr == LOW` to cap at `LOW` tier unconditionally,
regardless of every other signal. Re-running the full feature against the real Wild Wanderers vs
Phoenix Firehawks match exposed this as broken: that match's `ocr_confidence` values cluster in
the same 0.27–0.47 range for BOTH its 27 correctly-anchored recovered events and its 6 wrongly-
anchored ones — raw OCR confidence never actually distinguished good anchors from bad ones on
this broadcast; `ordering` did (confirmed: `ordering_violations_prevented=28` on that same run).
The `ocr == LOW` special case made `MEDIUM` tier unreachable for the typical case on this
broadcast (89% of even smoother-validated readings sat below the originally-configured
`ocr_confidence_medium` of 0.50), producing **zero** recovered events — the opposite of "fewer
highlights, but correct." Replaced with uniform downgrade-counting (every soft signal below its
best value — OCR not `HIGH`, search tier not exact-ball, pacing `SUSPICIOUS` — counts as exactly
one downgrade: 0 downgrades → HIGH, 1 → MEDIUM, 2+ → LOW), matching this decision's own original
stated intent ("downgrading a single soft signal at a time from HIGH is sufficient to land at
MEDIUM") without the inconsistent special case. Thresholds themselves were also recalibrated (see
Decision 4's own correction note) since the *floor* was independently miscalibrated on the same
evidence.

## Decision 7: "Recognized break in play" exceptions to ordering

**Decision**: No explicit innings-change or super-over exception logic is implemented at this
time. Anchor validation's ordering check (Decision 3) already runs strictly **within one innings**
(candidates are only ever searched within the same innings per the existing `_build_reading_indices`
partitioning, unchanged by this feature), so a cross-innings ordering "violation" can never occur
in the first place — there is nothing to except. Super overs are not representable in the current
data model at all (013's `MetadataEvent.innings` field is documented as `1` or `2` only).

**Rationale**: The spec's edge case ("how does the system handle a legitimate break in play")
is satisfied by the existing per-innings architecture rather than needing new logic — documenting
this explicitly here avoids a future maintainer re-adding unnecessary exception-handling code for
a case that structurally cannot occur under the current design.

**Alternatives considered**: Building explicit innings-boundary/super-over exception handling now
was rejected as speculative per Constitution's general "simplest solution that meets the bar"
posture (mirrored in this file's own `scene_threshold` comment precedent: "NOT YET DONE,
DELIBERATELY... revisit with real evidence"). Revisit if the data model ever grows a 3rd innings
value or if cross-innings metadata sequencing is ever observed to matter.

## Decision 8: Extending vs. replacing `MatchAlignmentEvidence`

**Decision**: Extend the existing frozen dataclass with three new fields
(`validation_tier`, `validation_signals`, `rejected_candidates`) rather than introducing a
parallel type. `recovery_eligible`'s stored meaning changes (now gated on `validation_tier in
(HIGH, MEDIUM)` in addition to the existing reading/detected-event conditions) but its type and
name are unchanged, so `recovery.py`'s `find_recovery_candidates()` — a pure filter on that one
field — requires no code change at all.

**Rationale**: Directly follows 013's own stated design intent for this type ("the shared
substrate every downstream stage consumes") and this project's general preference for additive
schema changes over parallel types (mirrored in the Event Database's own schema v1→v2 policy:
"additive only, no existing column redefined").

**Alternatives considered**: A wrapping `ValidatedAlignmentEvidence` type around the existing one
was considered and rejected — it would require every consumer (`validation.py`, `recovery.py`) to
be touched to unwrap it, defeating the point of keeping `recovery.py` unchanged.

## Decision 9: Reporting surface

**Decision**: `AccuracyReport` (`validation_models.py`) gains additive fields:
`anchored_high_confidence`, `anchored_medium_confidence`, `anchored_low_confidence`,
`unresolved_count`, `ordering_violations_detected`, `ordering_violations_prevented` — computed by
`analyze_accuracy()` from the now-richer `MatchAlignmentEvidence` sequence, alongside the
existing recall/precision fields (all unchanged in meaning). The existing `metadata.validate`
diagnostics record (`diagnostics.py`) is extended with the same counts, following its established
per-module diagnostics-record convention (`specs/technical_plan.md`'s "Cross-Cutting Concern:
Module Observability & Diagnostics").

**Rationale**: Directly implements spec FR-010/SC-004, and additive-only fields mean existing
tests/consumers of `AccuracyReport` (e.g. any code asserting on `ground_truth_total`,
`true_positives`, etc.) continue to pass unmodified.

**Alternatives considered**: A separate `AlignmentValidationSummary` type returned alongside
`AccuracyReport` from a new function was considered; folding the counts directly into
`AccuracyReport` was chosen instead because `cvip validate` already has exactly one report object
it prints/writes today, and spec User Story 3 wants "the summary" as a single artifact, not two
the user must correlate themselves.
