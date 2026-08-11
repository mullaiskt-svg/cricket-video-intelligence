# Quickstart: Validating Robust Innings Transition Detection

Two real datasets already in this repository ground validation — the match that surfaced the bug,
and matches that were already working correctly (the no-regression check).

## Prerequisites

- `data/matches/ww_vs_pf.sqlite` (or, for a from-scratch reproduction without re-running the
  ~11-hour full `cvip analyze`, the same raw CSV snapshot
  `third_match_raw_ocr_v2.csv`/`third_match_events_v5.csv` `specs/014-anchor-validation`'s own
  integration test already loads) — known to produce 5 spurious segments under the old logic.
- `data/matches/platinum_final_3rd.sqlite` — known-good match (single clean transition), the
  SC-003 no-regression fixture.

## Scenario 1 — The real bug is fixed

Re-run `_tag_readings_with_innings`'s new (shared-`InningsTracker`-backed) logic against the raw
`ww_vs_pf` reading sequence.

**Expected outcome**:
- Exactly 2 distinct segment values appear across the whole match (not 5).
- The real second-innings start (the reading at t≈6171s, where Phoenix Firehawks starts batting,
  runs≈6, wickets≈1, over≈1.3) is labeled segment 2.
- The two previously-false transitions (t≈3208s, t≈4048s: Wild Wanderers still batting at that
  point) do NOT appear as accepted transitions — inspecting their `InningsTransitionDecision`
  shows `REJECTED_IMPLAUSIBLE_RESET` or `REJECTED_INSUFFICIENT_PERSISTENCE` (single-frame
  misreads, not sustained), with a specific reason string (spec SC-005).

## Scenario 2 — No regression on an already-correct match

Re-run the same logic against `platinum_final_3rd`'s reading sequence (or its own equivalent raw
data).

**Expected outcome**: Still exactly 2 segments, with the transition landing at the same real
point in the match as before this feature (no shift, no new spurious segments introduced by the
stricter multi-signal requirement).

## Scenario 3 — Determinism

Run Scenario 1's reading sequence through two independently-constructed `InningsTracker`
instances (same config).

**Expected outcome**: Byte-identical sequences of `InningsTransitionDecision` objects.

## Scenario 4 — The bound holds under adversarial input

Feed a synthetic sequence engineered to look like more transitions than `max_segments` allows
(e.g., several well-separated, fully-corroborated, sustained low-score runs in a row).

**Expected outcome**: `current_segment` never exceeds `config.max_segments`; every candidate past
the bound is returned as `REJECTED_MAX_SEGMENTS_REACHED`, not silently ignored or crashing.

## What this quickstart does not cover

Full contract/unit test coverage of the individual signal checks (`reset_plausible`,
`over_ball_reset`, confirmation counting, confidence scaling) belongs in
`tests/contract/test_innings_transition_contract.py` and `tests/unit/test_innings_transition.py`
(Phase 2, `/speckit-tasks`) — this document is an end-to-end sanity check against real data, not a
substitute for that isolated coverage.
