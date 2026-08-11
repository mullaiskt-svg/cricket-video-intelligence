# Quickstart: Validating Scene-Cut-Anchored Clip Windows

The concrete defect that motivated this feature, and the real data needed to prove it's fixed, are
both already identified — this is a targeted end-to-end check, not exploratory testing.

## Prerequisites

- `data/matches/ww_vs_pf_scene_boundaries.json` — real Scene Detection output for the match whose
  investigation motivated this feature (produced by the standalone background run,
  `data/matches/run_scene_detection_standalone.py`; ~267 boundaries expected, per the original
  `analyze()` run's diagnostics).
- The specific previously-identified defective event: over 7.0, FOUR, Phoenix Firehawks innings,
  anchored at the timestamp verified by direct frame inspection to fall during a "REPLAY" overlay
  with a static, unchanging scoreboard (49-2, "Dileep K 14(13)") across the entire existing
  fixed-offset clip window.
- `config/default.yaml`'s existing `events.pre_roll_seconds`/`post_roll_seconds` (10s/10s) as the
  baseline this feature's fallback path must reproduce exactly.

## Scenario 1 — The real defective clip now starts at a real cut (SC-001)

Build a `ClipGenerationRequest` for the ww_vs_pf event list, with `scene_cuts` populated from
`ww_vs_pf_scene_boundaries.json`'s `boundaries[*].timestamp_seconds` (both `ORDINARY_CUT` and
`REPLAY_TRANSITION` included, per research.md Decision 3) and `max_cut_search_seconds` at its
calibrated default (20.0s). Run `generate_clips(request).run()` and inspect the `ClipEvidence` for
the over-7.0 FOUR event.

**Expected outcome**:
- `start_source == CUT_MATCHED`.
- `original_window[0]` equals a real boundary from `ww_vs_pf_scene_boundaries.json`, at or before
  the event's OCR-anchored timestamp, within 20 seconds of it.
- Extracting the frame at the new `clamped_window[0]` (the same direct-inspection technique used
  to originally find this defect) shows the moment the camera actually cuts — not the static
  "REPLAY" hold previously observed at the old fixed-offset start.

## Scenario 2 — No cut data supplied is byte-for-byte identical to today (SC-002)

Build the identical `ClipGenerationRequest` from Scenario 1, but with `scene_cuts=()` (the
default).

**Expected outcome**: Every `PlannedClip.clip_start_seconds`/`clip_end_seconds` in the resulting
`ClipPlan` matches what `specs/008`'s original, unmodified Clip Generator produces for the same
event list and settings — confirmed by running the same request through both the pre-016 and
post-016 code paths (or, equivalently, asserting every `ClipEvidence.start_source ==
FIXED_OFFSET` and every `original_window[0] == event.timestamp_seconds - pre_roll_seconds`).

## Scenario 3 — Mixed availability within one run

Using the real ww_vs_pf event list and scene-boundary data, inspect `runner.evidence` across all
events, not just the one known-defective one.

**Expected outcome**: Some events show `start_source == CUT_MATCHED` (a qualifying cut existed
nearby), others `FIXED_OFFSET` (none did, e.g. events during an unusually long unbroken shot) —
both outcomes appear in the same run, each independently correct for its own event, with no event
causing the run to fail regardless of which case it falls into.

## Scenario 4 — Determinism (SC-004)

Run Scenario 1's request through `generate_clips().run()` twice, independently.

**Expected outcome**: Byte-identical `ClipPlan`s, including identical `start_source` values and
identical `original_window[0]` timestamps for every event.

## What this quickstart does not cover

Full contract/unit coverage of the nearest-before search itself (exact-match-on-cut, empty
`scene_cuts`, cut exactly `max_cut_search_seconds` away, negative `max_cut_search_seconds`
rejection, unsorted input) belongs in `tests/contract/test_clip_generator_contract.py` and
`tests/unit/test_clip_generator_rules.py` (Phase 2, `/speckit-tasks`) — this document is a
targeted real-data sanity check against the concrete motivating defect, not a substitute for that
isolated coverage.
