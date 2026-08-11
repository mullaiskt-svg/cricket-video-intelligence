# Contract: Innings Transition Detection (`src/cvip/video/innings_transition.py`)

The ONE shared implementation `video/scoreboard_ocr.py`, `events/detection.py`, and
`orchestrator.py` all consume identically (research.md Decision 1). Nothing outside this module
implements or re-derives the transition decision.

## `InningsTracker.observe(reading) -> InningsTransitionDecision`

**Behavior**:

1. Extract `runs`, `wickets`, `over_number`, `ball_in_over`, a confidence value, from `reading`
   structurally (research.md Decision 3). If `runs` or `wickets` is `None`, return
   `NOT_A_CANDIDATE` immediately (mirrors every existing copy's own null-guard behavior) — this
   also does not affect the consecutive-confirmation count (a genuinely missing reading is not
   evidence against a transition in progress).
2. On cold start (no trusted baseline yet), record this reading as the trusted baseline and
   return `NOT_A_CANDIDATE` (nothing to compare against yet).
3. If `runs >= baseline.runs` or `wickets >= baseline.wickets` (not a decrease at all): reset the
   consecutive-confirmation count to zero, ADVANCE the trusted baseline to this reading (normal
   ongoing play — the baseline must track the match's actual current state, not stay frozen at
   whatever the last reading near a transition candidate was, otherwise a genuine transition much
   later would be judged against a stale, possibly-irrelevant reference point), return
   `NOT_A_CANDIDATE`.
4. Evaluate `reset_plausible` — `runs <= config.max_runs_for_new_segment AND wickets <=
   config.max_wickets_for_new_segment` (research.md Decision 5). If false, reset the confirmation
   count to zero and return `REJECTED_IMPLAUSIBLE_RESET`.
5. Evaluate `over_ball_reset` — over_number/ball_in_over both at or near the start (research.md
   Decision 6). If false, reset the confirmation count to zero and return
   `REJECTED_NO_OVER_BALL_RESET`.
6. Both plausibility checks passed: increment the consecutive-confirmation count. Compute
   `required_confirmations` from `config.min_consecutive_confirmations`, scaled up per research.md
   Decision 7 if this reading's confidence is below `config.low_confidence_threshold`. If the
   count is still below `required_confirmations`, return `REJECTED_INSUFFICIENT_PERSISTENCE`
   (confirmation count is preserved, not reset — this candidate run is still in progress).
7. Confirmation threshold met: if `current_segment == config.max_segments`, return
   `REJECTED_MAX_SEGMENTS_REACHED` (research.md Decision 9) — confirmation count is NOT reset here
   either (so if `max_segments` is later reconfigured upward mid-run, already-accumulated evidence
   isn't lost, though this is not an expected runtime scenario).
8. Otherwise: accept. Increment `current_segment`, replace the trusted baseline with this reading,
   reset the confirmation count to zero, return `ACCEPTED`.

**Postcondition — protected baseline** (research.md Decision 8): the trusted baseline used in
step 3-7's comparisons updates on cold start (step 2), normal ongoing play (step 3), and
acceptance (step 8) — it tracks the match's actual current state — but is NEVER set to a reading
from any `REJECTED_*` path. A rejected candidate can never become the reference point later
readings are judged against, which is precisely the mechanism that let one bad frame cause a
second in the real incident this feature fixes.

**Postcondition — bounded segments**: `current_segment` never exceeds `config.max_segments` for
any input sequence, however constructed (spec SC-006).

**Postcondition — never dropped**: exactly one `InningsTransitionDecision` is returned per
`observe()` call; the caller decides what to do with a `NOT_A_CANDIDATE`/`REJECTED_*` decision
(continue treating the reading as part of the current segment) versus `ACCEPTED` (segment
advances) — `InningsTracker` never raises for a well-formed reading.

**Determinism** (spec FR-013): given the same sequence of `observe()` calls and the same
`InningsTransitionConfig`, every returned `InningsTransitionDecision` sequence is identical across
runs — verified by a contract test calling the same sequence twice against fresh trackers and
asserting equality.

## Call-site postconditions (data-model.md's "Call-Site Adaptation")

- `video/scoreboard_ocr.py`: `_validate_reading`'s existing external return shape
  (`Tuple[bool, Optional[ValidationFailureReason]]`) and every other validation rule in that
  function are UNCHANGED — only the internal `innings_transition` boolean's source changes, from
  an inline check to `tracker.observe(...).outcome == InningsDecisionOutcome.ACCEPTED`.
- `events/detection.py`: `EventDetectionRunner`'s existing external contract (`DetectedEvent`
  shape, `innings` field meaning, `_innings_transitions_detected` diagnostics field meaning) is
  UNCHANGED — only how the transition itself is decided changes.
- `orchestrator.py`: `_tag_readings_with_innings`'s existing signature and
  `_ScoreboardReadingWithInnings`'s shape are UNCHANGED — the function's internal implementation
  becomes a thin adapter over one shared `InningsTracker` instead of its own independent scan.

## No new error taxonomy

`InningsTracker.observe()` never raises for well-formed input (missing fields are handled via
`NOT_A_CANDIDATE`, per step 1) — there is no new `*Error`/`*FailureReason` type for this module,
consistent with Constitution Principle VI applied at the *reading* level (an ambiguous reading
produces a visible, explained decision, never an exception that would abort an entire match's
analysis over one bad frame).
