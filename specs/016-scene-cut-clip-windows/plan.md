# Implementation Plan: Scene-Cut-Anchored Clip Windows

**Branch**: `016-scene-cut-clip-windows` | **Date**: 2026-08-08 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/016-scene-cut-clip-windows/spec.md`

## Summary

`specs/014` and `specs/015` fixed WHICH scoreboard reading an event's timestamp comes from (right
team, right chronological position). Real-data investigation of the resulting highlights found a
third, distinct problem: even a fully correct reading's timestamp can fall during a replay or a
static scoreboard hold — verified directly by extracting frames around one recovered event, which
showed a "REPLAY" overlay and an unchanging scoreboard across the entire existing clip window. OCR
has no concept of "live" vs. "replay" vs. "hold," so no amount of validating the OCR match harder
can fix this.

This feature gives Clip Generator (`src/cvip/clips/generator.py`) an optional second signal —
already-detected camera cut timestamps, independent of OCR — and snaps each clip's start to the
nearest real cut at or before the event, when one is close enough. When no cut-boundary data is
supplied, or no qualifying cut exists near a given event, behavior is byte-for-byte identical to
today's fixed pre-roll offset.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: None new — `bisect` (stdlib), already used elsewhere in this codebase
for the same class of timestamp-lookup problem (`specs/007-event-detection/research.md` Decision 2).

**Storage**: SQLite (Event Database) — no schema change in this feature's own scope (see research.md
Decision 2 for the deferred production-wiring question).

**Testing**: pytest, matching `tests/{contract,unit,integration}/test_clip_generator_*.py`'s
existing structure and fixtures.

**Target Platform**: Windows 11 desktop, CPU-only, offline — unchanged.

**Project Type**: Single Python package (`src/cvip/`), CLI tool — no new project type, no new
subpackage.

**Performance Goals**: Negligible. One `bisect`-based O(log n) lookup per event against an
already-in-memory, already-sorted list — no new I/O, no new frame/OCR work, well within the
existing `cvip generate` budget.

**Constraints**: Must not change behavior when no cut-boundary data is supplied (spec FR-007);
must not change clip end/post-roll computation (spec FR-006); must not change `cvip generate`'s
CLI surface (spec FR-008); must remain deterministic (spec FR-010).

**Scale/Scope**: Same scale as Clip Generator already handles — tens to low hundreds of events per
match; cut-boundary lists in the low hundreds to low thousands of entries for a full match (267
detected for the real match this investigation used).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Check | Status |
|---|---|---|
| I. Offline-First | No network/cloud calls — pure computation over already-supplied local data. | PASS |
| II. Performance | O(log n) per event, negligible against the existing budget; no new frame/video pass. | PASS |
| III. Single-Pass | Never re-triggers Scene Detection or any frame-consuming stage — consumes an already-provided timestamp list only. | PASS |
| IV. Detection Accuracy | Not a fours/sixes/wickets/replay-removal accuracy target — this is a clip-window-placement refinement, not a detection module. N/A. |
| V. Modular & Extensible | Confined to Clip Generator's own existing module (`clips/generator.py`/`models.py`) — no new subpackage, no new pipeline stage, consistent with this being a scoped enhancement to an existing, already-independently-testable module. | PASS |
| VI. Fail Fast, Never Silently | Missing/malformed cut-boundary data degrades gracefully to the existing, already-correct fixed-offset behavior (spec FR-004) — a deliberate, spec-mandated exception mirroring `specs/014`'s own LOW-confidence-exclusion precedent, not a silent-wrong-guess. Every clip's start mechanism (cut-matched vs. fallback) is recorded, never unexplained (FR-009). | PASS |
| VII. Test-First | Contract tests before implementation; Clip Generator is an existing critical path (it directly determines what makes it into every highlight video) — 100% coverage on the new logic, same bar as `specs/014`/`specs/015`. | PASS (planned) |

No violations requiring Complexity Tracking justification.

## Project Structure

### Documentation (this feature)

```text
specs/016-scene-cut-clip-windows/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   └── clip_window_snapping_contract.md
└── tasks.md             # Phase 2 output (/speckit-tasks — not created here)
```

### Source Code (repository root)

```text
src/cvip/clips/
├── generator.py   # MODIFIED: Pass 1's raw_start computation (run(), lines ~107-137)
│                  # gains an optional scene-cut-snapping step before the existing
│                  # fixed-offset fallback; everything downstream (clamping, replay
│                  # filtering, Merge Engine, ClipPlan assembly) unchanged
└── models.py      # MODIFIED (additive): ClipGenerationRequest gains an optional
                   # scene_cuts field + max search distance config; ClipEvidence
                   # gains an optional field recording which mechanism produced
                   # each clip's start

tests/contract/
└── test_clip_generator_contract.py   # MODIFIED: new contract assertions for the
                                        # snap-vs-fallback postcondition and the
                                        # "no cut data supplied → identical to today"
                                        # regression guarantee

tests/unit/
└── test_clip_generator_rules.py      # MODIFIED (or new test file alongside it):
                                        # nearest-before-cut search, bounded distance,
                                        # boundary_type inclusion, tie/edge cases

tests/integration/
└── test_clip_generator_e2e.py        # MODIFIED: real-data scenario using the
                                        # ww_vs_pf scene-boundary fixture once available
```

**Structure Decision**: Entirely confined to the existing `src/cvip/clips/` subpackage — no new
subpackage, no new pipeline stage, no CLI change. This mirrors the "scoped, single-module
enhancement" framing from the spec itself; `orchestrator.py`'s own production wiring of where
`scene_cuts` data comes from is explicitly out of this feature's scope (research.md Decision 2)
and requires no changes here.

## Complexity Tracking

*No Constitution Check violations — this section is not needed.*
