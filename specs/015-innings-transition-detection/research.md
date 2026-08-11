# Research: Robust Innings Transition Detection

## Decision 1: One shared, stateful decision service, not three independent copies

**Decision**: `src/cvip/video/innings_transition.py` exposes a single class, `InningsTracker`,
instantiated once per match/analysis run and driven by calling `.observe(reading)` once per
reading in chronological order. All three existing call sites are rewritten to construct one
`InningsTracker` and delegate to it, rather than re-deriving the decision inline.

**Rationale**: The bug that motivated this feature is directly a consequence of three
independently-drifting implementations of "the same" heuristic — one has a guard the others
lack, and that guard itself has a documented gap. A single shared implementation makes this bug
class structurally impossible going forward (there is no second copy to drift out of sync), and
follows this project's own established precedent for exactly this situation (`specs/013-014`'s
Timeline Alignment: "the ONE reusable component" every consumer shares, never re-derived
independently).

**Alternatives considered**:
- *A pure function called fresh at each call site, no shared state object*: rejected — the
  persistence requirement (FR-002) and protected-baseline requirement (FR-007) both need memory
  across calls (has this candidate value been seen before, what is the current trusted baseline)
  that a stateless pure function would have to have re-threaded through every caller's own loop,
  which is exactly the kind of duplicated bookkeeping that let the three existing copies drift.
- *A free function taking and returning an explicit state value* (`(new_state, decision) =
  advance(state, reading)`): considered as more purely functional and easier to unit-test in
  isolation. Partially adopted — `InningsTracker` is a thin, stateful wrapper around exactly this
  kind of pure `advance()` step internally (see Decision 6), giving both: a simple call-site API
  (`tracker.observe(reading)`) and a pure, trivially-testable core function.

## Decision 2: Shared module location — `src/cvip/video/`

**Decision**: `innings_transition.py` + `innings_transition_models.py` live in `src/cvip/video/`.

**Rationale**: `scoreboard_ocr.py` (one of the three consumers) already lives there.
`events/detection.py` (a second consumer) already imports OCR-stage types (`ScoreboardSample`,
`ScoreboardOcrResult`) FROM `video/` — the import direction this feature's new dependency would
add (`events/` importing from `video/`) already exists and is established, not new coupling.
`orchestrator.py` (the third consumer) is the composition root and already imports freely from
both packages. This directly satisfies CLAUDE.md's own stated rationale for why Modules 1-4a live
together in `video/` in the first place: avoiding awkward cross-package imports between
tightly-coupled pipeline stages — this module is exactly that kind of tightly-coupled,
frame-analysis-adjacent concern (it consumes the direct output of Scoreboard OCR/OCR Timeline
Smoother, one step removed from frame consumption).

**Alternatives considered**:
- *`src/cvip/common/`* (alongside `diagnostics.py`): rejected — `common/` is documented as
  "cross-cutting infrastructure shared by every module" (CLAUDE.md); this is a domain-specific
  cricket-scoring concept (innings), not generic infrastructure like structured logging.
- *`src/cvip/events/`*: rejected — would reverse the existing import direction (`video/`
  currently never imports from `events/`), and `scoreboard_ocr.py`'s own consumption of this
  module would then need to import "downstream," which is the awkward cross-package coupling
  CLAUDE.md's package-layout section specifically warns against.

## Decision 3: Structural typing for the reading input, not a shared dataclass import

**Decision**: `InningsTracker.observe()` accepts anything exposing `runs`, `wickets`,
`over_number`, `ball_in_over`, `timestamp_seconds`, and an optional confidence value (`ocr_confidence`
if present, else `parse_confidence`, else `None`) by attribute — not a hard dependency on
`ScoreboardSample` or `ScoreState` specifically.

**Rationale**: The three call sites feed genuinely different shapes: `scoreboard_ocr.py` and
`orchestrator.py` both operate on raw, per-second `ScoreboardSample` objects (Optional fields);
`events/detection.py` operates on the cleaned/collapsed `ScoreState` (non-Optional fields, each
one already representing a run of one-or-more identical raw samples, with its own
`average_ocr_confidence`). Requiring a hard shared type would force one of the three to build an
adapter object anyway. This follows this project's own established structural-typing precedent
(`specs/010-event-database/research.md` Decision 8, most recently reused by
`specs/014-anchor-validation/research.md` Decision 5 for this exact kind of situation — adapting
a proven concept to a new module's own input shape rather than hard-importing across module
boundaries).

**Alternatives considered**:
- *A single shared `TransitionReading` dataclass all three call sites must construct*: rejected
  as an unnecessary extra adapter step at every call site for no behavioral benefit over
  structural typing, which this codebase already relies on extensively for exactly this kind of
  cross-module value-passing.

## Decision 4: Persistence requirement is expressed as "N qualifying observations in a row," granularity-agnostic

**Decision**: The state machine tracks a rolling count of consecutive readings that look like part
of a new segment (pass the magnitude+over/ball-reset checks) since the last *trusted* reading, not
readings since the beginning of time. A transition is only accepted once this count reaches
`InningsTransitionConfig.min_consecutive_confirmations`. Any reading that does NOT look like part
of a new segment resets the count to zero (it doesn't just fail to increment it) — a single
recovery reading in between two suspicious ones means the suspicious run never happened.

**Rationale**: Directly closes the real incident's mechanism — neither of the two false
transitions (t=3208s, t=4048s) was followed by multiple consecutive corroborating low-score
readings; each was an isolated single-frame misread surrounded by readings consistent with the
innings continuing normally. A genuine transition, by contrast, is followed by many consecutive
seconds of low-score readings (the new innings actually starting), so a small confirmation window
cleanly separates the two cases without needing perfect single-frame accuracy.

**Granularity note**: because call sites feed genuinely different-granularity streams (raw
per-second samples vs. already-collapsed states, each representing a run of samples), the
configured `min_consecutive_confirmations` is a caller-supplied value, not a single global
constant — `orchestrator.py`/`scoreboard_ocr.py` (raw per-second) use a value calibrated in
"seconds of noise a single misread run could plausibly last" terms; `events/detection.py`
(collapsed states) uses a smaller value since each state already represents sustained agreement
across its own `sample_count`. Documented per-caller in data-model.md's Configuration Additions.

**Alternatives considered**:
- *A single global confirmation count for all callers*: rejected once the granularity mismatch
  was identified — a count calibrated for raw per-second noise would be far too strict applied to
  the already-collapsed state stream (each state already implies persistence within itself).

## Decision 5: Plausibility-of-reset check — reuse the concept from `state_transition.py`, not the function

**Decision**: A new function, `_is_plausible_innings_reset(candidate, trusted_baseline)`, judges
whether a claimed decrease looks like a genuine innings reset (dropping toward near-zero runs and
near-zero wickets, both together) rather than a random misread that happens to land below the
previous reading. Adapted from, not calling, `state_transition.py`'s `is_anomalous_transition()`.

**Rationale**: `is_anomalous_transition()` bounds how large an INCREASE is plausible given balls
elapsed — the inverse shape of what this feature needs (judging whether a DECREASE is plausible as
a genuine reset). Its types (`ScoreState`, ball-elapsed-based ceilings) belong to a different
pipeline stage and don't directly transfer; per Decision 3's structural-typing choice, this
feature adapts the *concept* (a magnitude/shape ceiling, not a flat single-number cutoff) to its
own reset-shaped judgment: a genuine reset requires BOTH runs and wickets to land very close to
zero (not merely "lower than before"), which is what distinguishes a real innings start from an
OCR misread that coincidentally reads a lower-but-still-substantial value.

**Alternatives considered**:
- *Import and call `is_anomalous_transition()` directly*: rejected for the same reason
  `specs/014-anchor-validation/research.md` Decision 5 already rejected the equivalent — different
  pipeline stage, different upstream shape, would create the "awkward cross-package coupling"
  CLAUDE.md's package-layout section warns against.
- *Keep the existing flat `_NEW_INNINGS_MAX_RUNS = 20` ceiling only, no wickets-near-zero
  requirement*: rejected — this is exactly the guard that already exists in the buggy code and
  demonstrably did not catch the real incident (`runs=5`/`runs=7`, both well under 20). A
  wickets-near-zero co-requirement (not just runs) closes this specific gap: a real innings start
  has both values near zero simultaneously, not just one.

## Decision 6: Over/ball reset — now a required corroborating signal, reversing a prior rejected decision

**Decision**: A transition candidate must also show `over_number`/`ball_in_over` resetting near
the start of an over (not just runs/wickets dropping) to be accepted.

**Rationale**: `specs/007-event-detection/research.md` Decision 5 explicitly rejected this exact
check, reasoning "over_number decreasing is already implied by a genuine innings transition and
doesn't need independent checking." Real data disproves this: both false transitions in the real
incident were never cross-checked against over/ball at all, and both would have failed this check
had it existed (a genuine reset shows over≈0, ball≈0; a random mid-innings misread's over/ball
field, even if also garbled, has no reason to independently also land near zero at the same
moment). This is now one of the two required components of the magnitude/shape check in Decision
5 above, not a separate optional signal.

**Alternatives considered**: None — this is a direct, evidence-driven reversal of a specific
prior decision, not a menu of options; the real data settles it.

## Decision 7: Confidence weighting — governs how strong persistence must be, not a separate gate

**Decision**: `InningsTransitionConfig` includes a confidence threshold; a candidate reading whose
own confidence value is below it requires MORE consecutive confirmations
(`min_consecutive_confirmations` scaled up) before being accepted than a high-confidence one
requiring the configured baseline count.

**Rationale**: Directly implements spec FR-005 ("a lower-quality signal MUST require stronger
corroboration than a high-quality one") without adding confidence as a hard pass/fail gate, which
would risk rejecting a genuine transition outright just because the exact frame it first appeared
on happened to be a poor-quality frame (the OCR Timeline Smoother's own reason for existing:
individual frame quality is noisy, but sustained agreement is trustworthy even when individual
frames aren't).

**Alternatives considered**: A hard confidence floor (reject any candidate below a threshold
outright) was considered and rejected — this project's own real match data (from
`specs/014-anchor-validation`'s investigation) already showed raw OCR confidence values cluster
low across an entire broadcast regardless of correctness; a hard floor here risks exactly the
same "reject everything, including genuine cases" failure `specs/014`'s own OCR-quality threshold
correction (research.md Decision 4's self-caught correction) already had to fix once.

## Decision 8: Protected baseline

**Decision**: `InningsTracker`'s internal trusted baseline only ever updates on an ACCEPTED
transition (or the tracker's own cold-start first reading) — a rejected candidate, at any stage
of the confirmation-counting process, never becomes the reference point future readings are
compared against.

**Rationale**: Directly closes the real incident's cascade mechanism — `orchestrator.py`'s
current `_tag_readings_with_innings` updates `last_runs`/`last_wickets` unconditionally on every
sample with non-null runs/wickets, including the sample that just (wrongly) fired a transition,
which is exactly how t=3208s's bad reading became the baseline that made t=4048s's bad reading
also look like a further decrease. This mirrors `events/detection.py`'s own existing "last
accepted baseline" walk (already correct in that copy) and `state_transition.py`'s own module
docstring, which documents the identical failure shape from a real prior incident in a different
part of this pipeline.

## Decision 9: Hard max-segments bound as a structural backstop

**Decision**: `InningsTransitionConfig.max_segments` (default 2) is enforced inside
`InningsTracker` itself — once the current segment count equals `max_segments`, no further
candidate can ever be accepted, regardless of how much evidence it accumulates. Such a candidate
is recorded with outcome `REJECTED_MAX_SEGMENTS_REACHED`, not silently dropped (spec SC-006).

**Rationale**: Directly implements spec FR-006/User Story 3 — a backstop independent of how good
the per-transition judgment is. Even a well-calibrated heuristic will occasionally see a
genuinely ambiguous stretch of match; the bound converts that into a bounded, visible outcome
rather than an unbounded one.

**Alternatives considered**: Enforcing the bound only at the call-site level (e.g., orchestrator
clamping the final count after the fact) was rejected — that would allow the *decision process
itself* to keep firing transitions internally (still confusing later analysis/diagnostics) and
only mask the symptom at the last moment, rather than making "no further transitions possible"
a real, load-bearing state the tracker is actually in.

## Decision 10: Decision/evidence record shape — reuse the pattern `specs/014-anchor-validation` established

**Decision**: Every `.observe()` call returns an `InningsTransitionDecision`
(`innings_transition_models.py`) carrying a discrete `InningsDecisionOutcome` enum (not a
continuous score), the current segment number, and a human-readable `reason` string built from
the individual signal verdicts — directly mirroring `AnchorValidationSignals`/`AnchorConfidenceTier`'s
already-proven shape from the immediately preceding feature.

**Rationale**: This pattern is now proven, consistent, and exactly satisfies spec FR-012/SC-005
("a specific, human-readable explanation... without needing to re-derive it from raw logs").
Reusing an established, working pattern from the immediately preceding feature in this same
codebase is lower-risk than inventing a new one, and keeps the platform's diagnostics
conventions consistent.

## Decision 11: Configuration

**Decision**: New `innings_transition` block in `config/default.yaml`:

```yaml
innings_transition:
  max_segments: 2
  max_runs_for_new_segment: 20       # unchanged value, reused from the existing guard
  max_wickets_for_new_segment: 2     # NEW -- the wickets-near-zero co-requirement (Decision 5)
  min_consecutive_confirmations_raw: 5      # for raw per-second sample callers
  min_consecutive_confirmations_collapsed: 2  # for already-collapsed ScoreState callers
  low_confidence_threshold: 0.5
  low_confidence_confirmation_multiplier: 2.0
```

**Rationale**: `max_runs_for_new_segment: 20` is carried over unchanged from the existing,
already-validated-against-a-real-incident (PLATINUM CUP FINAL) constant — no evidence it needs
changing. `max_wickets_for_new_segment: 2` is new, calibrated so a genuine reset (0 or 1 wickets
at the very start of an innings) qualifies while a mid-innings reading that happens to have a
low-but-nonzero wicket count doesn't. The two different confirmation counts implement Decision
4's granularity-agnostic design. All values documented with real-data rationale, in this file's
established "reasoned calibration, revisit if wrong" style, matching every other calibrated
constant in `config/default.yaml`.
