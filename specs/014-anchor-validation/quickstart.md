# Quickstart: Validating Anchor Validation

Two real, already-collected match datasets ground this feature's validation — no synthetic
fixtures needed for the end-to-end check (unit/contract tests still use small hand-built fixtures
per Constitution Principle VII).

## Prerequisites

- `data/matches/ww_vs_pf.sqlite` — a COMPLETE match analysis with known-poor OCR quality (avg
  confidence 0.34) and a supplied commentary file (`data/ww_vs_pf_commentary.json`) that, under
  013's original behavior, produced 6 out-of-order recovered events out of 33.
- `data/matches/platinum_final_3rd.sqlite` — a COMPLETE match analysis with moderately better OCR
  quality (avg confidence 0.49) and its own commentary file, used as the regression check (SC-006:
  this feature must not shrink the previously-recoverable high-confidence set).

## Scenario 1 — Previously wrong anchors are no longer silently accepted

```powershell
cvip validate ww_vs_pf --metadata data/ww_vs_pf_commentary.json --recover --enrich
```

**Expected outcome** (contrasted with pre-feature behavior):
- The 6 events previously recovered out of chronological order (documented in this feature's
  spec.md — e.g. the over `0.2`/`0.3` pair, previously anchored to t=2115s and t=0s respectively)
  no longer appear as silently-accepted `METADATA`-sourced events in the resulting database at
  those same wrong timestamps. Each now shows as either `UNRESOLVED` (excluded from recovery
  entirely) or `LOW` confidence (excluded from *automatic* recovery) in the validation report.
- The printed/written `AccuracyReport` includes the new tier-breakdown fields
  (`anchored_high_confidence`, `anchored_medium_confidence`, `anchored_low_confidence`,
  `unresolved_count`) and `ordering_violations_prevented` is greater than 0 for this match —
  concretely demonstrating validation caught something 013's original behavior would have missed.
- For at least one of the 6 previously-mis-anchored events, the report's diagnostic detail names a
  specific rejection reason (e.g. an ordering conflict naming the anchor it would have preceded
  out of turn, or an OCR-quality verdict citing the low `ocr_confidence` value) — verifying spec
  FR-009/Story 2 end-to-end.

## Scenario 2 — Determinism

```powershell
cvip validate ww_vs_pf --metadata data/ww_vs_pf_commentary.json --output out1.json
cvip validate ww_vs_pf --metadata data/ww_vs_pf_commentary.json --output out2.json
```

(Read-only accuracy-reporting mode — no `--recover`/`--enrich`, so this is safely repeatable
against the same COMPLETE match without idempotency concerns from the write path.)

**Expected outcome**: `out1.json` and `out2.json` are byte-identical, verifying spec FR-013 /
013's own FR-018 continues to hold with the new validation logic included.

## Scenario 3 — No regression on a match with better OCR quality

```powershell
cvip validate platinum_final_3rd --metadata <its commentary file> --recover --enrich
```

**Expected outcome**: The count of events recovered at `HIGH` or `MEDIUM` confidence is not lower
than the count of events this match's OCR-supported commentary recovery achieved before this
feature (30 events recovered, per this project's own prior validated run) — demonstrating SC-006:
correctness validation does not come at the cost of losing already-trustworthy recoveries. Some
individual events may shift from being silently accepted to being explicitly `LOW`/`UNRESOLVED`
if their underlying evidence genuinely doesn't support high confidence, but the well-supported
majority should classify `HIGH`/`MEDIUM` and remain recoverable.

## What this quickstart does not cover

Full contract/unit test coverage for the individual signal-evaluation functions
(`evaluate_signal_ocr_quality`, `evaluate_signal_score_state`, `evaluate_signal_ordering`,
`evaluate_signal_neighbor_pacing`) and the confidence-tier rule table belongs in
`tests/contract/test_anchor_validation_contract.py` and `tests/unit/test_anchor_validation.py`
(Phase 2, `/speckit-tasks`) — this document is an end-to-end sanity check against real data, not
a substitute for that isolated test coverage.
