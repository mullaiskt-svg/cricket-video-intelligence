# Implementation Plan: Robust Innings Transition Detection

**Branch**: `015-innings-transition-detection` | **Date**: 2026-08-08 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/015-innings-transition-detection/spec.md`

## Summary

Three independent copies of the same single-signal heuristic ("runs and wickets both decreased
relative to the last reading") currently decide innings transitions across this pipeline
(`video/scoreboard_ocr.py`, `events/detection.py`, `orchestrator.py`), with inconsistent
guardrails between them. Real-match validation (Wild Wanderers vs Phoenix Firehawks) proved the
weakest copy (`orchestrator.py`'s `_tag_readings_with_innings`, which populates
`scoreboard_readings.innings`) fragments a genuine two-innings match into five, because a single
noisy OCR frame is sufficient to fire a transition, and the same bad reading immediately becomes
the baseline for judging the next one — letting one bad frame cause a second.

This feature replaces all three copies with one shared, stateful decision service
(`src/cvip/video/innings_transition.py`): a small state machine holding a *trusted* baseline
(never a rejected reading) and a hard cap on transitions, gated by a multi-signal evidence check
(plausible reset magnitude, over/ball corroboration, multi-reading persistence, confidence
weighting) instead of one raw comparison. Every call site is updated to consume this one service
identically.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: None new — pure-Python state machine over already-extracted reading
fields (`runs`, `wickets`, `over_number`, `ball_in_over`, `ocr_confidence`/`parse_confidence`,
`timestamp_seconds`), consistent with every module this feature touches.

**Storage**: SQLite (Event Database) — no schema change. This feature changes how the existing
`scoreboard_readings.innings` and `events.innings` columns are computed, not their shape.

**Testing**: pytest, matching `tests/unit/test_orchestrator_analyze.py`'s existing
`_tag_readings_with_innings` tests, `tests/unit/test_event_detection_rules.py`'s existing
innings-transition test, and `tests/unit/test_scoreboard_ocr_validation.py`'s existing
false-transition test as the baseline this feature must not regress, extended with new
contract/unit tests for the shared module itself.

**Target Platform**: Windows 11 desktop, CPU-only, offline — unchanged.

**Project Type**: Single Python package (`src/cvip/`), CLI tool — no new project type.

**Performance Goals**: Negligible added cost — a small state machine evaluated once per already-
extracted reading, same order of magnitude as the single comparisons it replaces. Runs entirely
inside the existing `cvip analyze` budget (Constitution Principle II), adding no new pass over
video/frames.

**Constraints**: Must remain deterministic (spec FR-013); must not change `cvip analyze`'s
external behavior/CLI surface (spec FR-014); must require no new OCR-extracted signals (spec
FR-009) — team name and on-screen target text remain explicitly out of scope, flagged as a
valuable, separate follow-on.

**Scale/Scope**: Same scale as the modules being touched — one shared decision made once per
scoreboard reading across a whole match (up to ~11K raw per-second readings for a 3-hour match,
per real observed data).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Check | Status |
|---|---|---|
| I. Offline-First | No network/cloud calls — pure computation over already-local data. | PASS |
| II. Performance | Negligible cost added to the existing `cvip analyze` budget; no new frame/video pass. | PASS |
| III. Single-Pass | Reads only already-extracted reading fields; never re-triggers OCR, scene detection, or any frame-consuming stage. | PASS |
| IV. Detection Accuracy | Not a fours/sixes/wickets/replay-removal accuracy target — governs Modules 2-5's own detection quality, not this cross-cutting tagging concern. N/A. |
| V. Modular & Extensible | Consolidates three independently-drifting copies of one concern into a single, independently-testable shared module (`video/innings_transition.py`) with its own contract — directly improves modularity versus the current three-copy state. | PASS |
| VI. Fail Fast, Never Silently | Every transition decision (accepted or rejected) is recorded with explicit evidence (spec FR-012) — an ambiguous reading never silently becomes a wrong guess; the max-segments bound converts "detector logic went wrong somewhere" from silent data corruption into a visible, bounded, explained condition. | PASS |
| VII. Test-First | Contract tests for the shared module written before implementation; this is an explicit critical path (spec: "gates which team's footage every downstream consumer thinks it's looking at") requiring 100% coverage on the new decision logic, per the same bar `specs/014-anchor-validation` was held to. | PASS (planned) |

No violations requiring Complexity Tracking justification.

## Project Structure

### Documentation (this feature)

```text
specs/015-innings-transition-detection/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   └── innings_transition_contract.md
└── tasks.md             # Phase 2 output (/speckit-tasks — not created here)
```

### Source Code (repository root)

```text
src/cvip/video/
├── innings_transition.py         # NEW: the shared state machine + evidence
│                                  # evaluation (InningsTracker, evaluate_* signal
│                                  # functions) — the ONE implementation every
│                                  # call site below now consumes
├── innings_transition_models.py  # NEW: InningsTransitionConfig, InningsDecisionOutcome,
│                                  # InningsTransitionDecision, InningsSignals
├── scoreboard_ocr.py              # MODIFIED: _validate_reading's own
│                                  # innings_transition special-case (lines 562-569)
│                                  # now defers to the shared module's decision
│                                  # instead of re-deriving it inline
└── scoreboard_ocr_models.py       # UNCHANGED (no new fields needed on ScoreboardSample)

src/cvip/events/
├── detection.py                  # MODIFIED: EventDetectionRunner._process_comparison's
│                                  # own innings-transition branch (lines 184-207) now
│                                  # delegates to the shared module instead of its
│                                  # own inline `current.runs < previous.runs and
│                                  # current.wickets < previous.wickets` check
└── models.py                     # UNCHANGED

src/cvip/orchestrator.py           # MODIFIED: `_tag_readings_with_innings` (lines
                                    # 149-166) becomes a thin adapter over the shared
                                    # module instead of its own independent forward
                                    # scan; `_NEW_INNINGS_MAX_RUNS` module-level
                                    # constant removed (superseded by
                                    # InningsTransitionConfig)

config/default.yaml                 # MODIFIED (additive): new `innings_transition`
                                    # config block

tests/contract/
└── test_innings_transition_contract.py   # NEW

tests/unit/
├── test_innings_transition.py            # NEW
├── test_orchestrator_analyze.py          # MODIFIED: existing `_tag_readings_with_innings`
│                                          # tests (lines 460-493) updated to reflect
│                                          # the new shared-module-backed behavior;
│                                          # must still pass for the two ALREADY-covered
│                                          # cases (genuine transition, PLATINUM CUP
│                                          # FINAL-style small-decrease noise)
├── test_scoreboard_ocr_validation.py     # MODIFIED: existing false-transition test
│                                          # (lines 498-527) updated for the new
│                                          # shared-module call, same intent preserved
└── test_event_detection_rules.py         # MODIFIED: existing innings-transition test
                                            # updated for the new shared-module call

tests/integration/
└── test_innings_transition_real_dataset.py   # NEW: reproduces the real ww_vs_pf fix
                                                # (2 segments, not 5) and the no-regression
                                                # check against platinum_final_3rd-style data
```

**Structure Decision**: New shared module lives in `src/cvip/video/`, alongside
`scoreboard_ocr.py` (one of its three consumers already lives there) — consistent with
CLAUDE.md's package-layout rationale that Modules 1/1a/2/3/4/4a live together specifically to
avoid awkward cross-package imports between tightly-coupled pipeline stages, and consistent with
the existing import direction (`events/detection.py` already imports OCR-stage types from
`video/`, never the reverse). `orchestrator.py`, as the composition root, already imports freely
from both `video/` and `events/` regardless of which package owns this module.

## Complexity Tracking

*No Constitution Check violations — this section is not needed.*
