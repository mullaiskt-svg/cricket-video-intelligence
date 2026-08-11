# Implementation Plan: Anchor Validation for Timeline Alignment

**Branch**: `014-anchor-validation` | **Date**: 2026-08-07 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/014-anchor-validation/spec.md`

## Summary

Stage 2 (Timeline Alignment, `src/cvip/metadata/alignment.py`) of the merged Structured Match
Metadata Validation layer (013) currently converts a metadata event's over.ball position into a
video timestamp by finding the nearest scoreboard reading at that position and committing to it
unconditionally — real-match validation showed this produces confidently-wrong timestamps (6 of
33 recovered events out of chronological order on one match) whenever the underlying OCR is
unreliable, which is common on this platform's target broadcasts.

The fix inserts an **Anchor Validation** sub-step between candidate search and evidence
construction, entirely inside Stage 2: candidate search is extended to surface a ranked set of
candidates per event (not just the first hit); a new deterministic scoring pass judges each
candidate against OCR quality, score-state plausibility, chronological ordering against
already-accepted anchors in the same innings, and neighboring-anchor pacing; only a candidate
that survives is accepted, classified into a High/Medium/Low/Unresolved confidence tier, and
only High/Medium tiers remain `recovery_eligible`. Rejected/unresolved events carry a full
diagnostic trail. This is additive to `MatchAlignmentEvidence` (013's shared substrate consumed
identically by Accuracy Analysis and Recovery) — no new pipeline stage, no new CLI surface.

## Technical Context

**Language/Version**: Python 3.11+ (matches project-wide constraint)

**Primary Dependencies**: None new — pure-Python logic over already-persisted `scoreboard_readings`/`events` rows, consistent with 013's existing dependency footprint (stdlib only in `src/cvip/metadata/`).

**Storage**: SQLite (Event Database) — read-only for this feature; no schema change. `MatchAlignmentEvidence` remains an in-memory-only value object (013 research.md Decision 2), never persisted verbatim, so the richer validation detail this feature adds does not require a schema migration.

**Testing**: pytest, matching the existing `tests/contract/test_metadata_alignment_contract.py` and `tests/unit/test_metadata_alignment.py` structure — new contract/unit test files follow the same naming convention for the new module(s).

**Target Platform**: Windows 11 desktop, CPU-only, offline (unchanged — this feature touches no I/O boundary beyond what 013 already reads).

**Project Type**: Single Python package (`src/cvip/`), CLI tool — no new project type.

**Performance Goals**: Negligible added cost. Today's `align()` already runs in milliseconds against a full match's `scoreboard_readings` (observed: sub-1s for an 11,434-row match in real validation runs). The added validation pass is O(events × candidates-per-event), still trivial relative to the ≤40-minute full-pipeline budget (Constitution Principle II) — this feature runs only inside the already-optional `cvip validate` path, never inside `cvip analyze`/`cvip generate`.

**Constraints**: Must remain deterministic (spec FR-013 / 013's own FR-018); must never write to the database itself (Stage 2 remains read-only, exactly as today); must not alter `cvip analyze`/`cvip generate` behavior in any way (spec FR-014).

**Scale/Scope**: Same scale as 013 — a single match's metadata file (tens to low hundreds of ball-by-ball entries) and scoreboard readings (~1 per second of match video, so low thousands to ~11K rows for a full match, per real observed data).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Check | Status |
|---|---|---|
| I. Offline-First | No network/cloud calls introduced — pure computation over already-local data. | PASS |
| II. Performance | No measurable impact on the 40-minute/6GB budget — this feature only runs inside optional, already-out-of-band `cvip validate`, never `analyze`/`generate`. | PASS |
| III. Single-Pass | Reads only already-persisted `scoreboard_readings`/`events` rows; never re-invokes Video Loader, Scene Detection, Replay Detection, or Scoreboard OCR. | PASS |
| IV. Detection Accuracy | Not a video-detection module (no fours/sixes/wickets/replay-removal accuracy target applies) — this governs Modules 2-5, not the metadata layer. N/A. |
| V. Modular & Extensible | Anchor Validation is a new, independently-testable internal component (own file-set, own contract tests) invoked by `align()` — does not entangle Stage 3/4/5's own contracts, which keep consuming `MatchAlignmentEvidence` exactly as before. | PASS |
| VI. Fail Fast, Never Silently | This is the feature's entire purpose: an unresolved event is now a visible, explained outcome instead of a silently-wrong timestamp. Diagnostics extended per FR-009/FR-010. | PASS |
| VII. Test-First | Contract tests for the new candidate-ranking and anchor-validation functions written before implementation (Phase 2, `/speckit-tasks` + `/speckit-implement`); Timeline Alignment is explicitly a critical path (it now gates highlight-video correctness) requiring 100% coverage on the new decision logic. | PASS (planned) |

No violations requiring Complexity Tracking justification.

## Project Structure

### Documentation (this feature)

```text
specs/014-anchor-validation/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md         # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   └── anchor_validation_contract.md
└── tasks.md             # Phase 2 output (/speckit-tasks — not created here)
```

### Source Code (repository root)

```text
src/cvip/metadata/
├── alignment.py                 # MODIFIED: align() now calls the new candidate-ranking +
│                                 # anchor-validation functions instead of committing to the
│                                 # first search hit; _search_reading() becomes
│                                 # _rank_candidates() (returns all matches in the search
│                                 # window, ranked, not just the earliest)
├── alignment_models.py          # MODIFIED (additive): MatchAlignmentEvidence gains
│                                 # validation_tier, validation_signals, rejected_candidates;
│                                 # recovery_eligible's meaning changes (documented, not a
│                                 # field rename) per FR-005/FR-006
├── anchor_validation.py         # NEW: the validation pass — per-innings, over.ball-ordered
│                                 # walk that scores each ranked candidate and accepts/rejects
├── anchor_validation_models.py  # NEW: AnchorConfidenceTier, AnchorValidationSignals,
│                                 # CandidateAnchor, OrderingConflict, AlignmentValidationSummary
├── recovery.py                  # UNCHANGED — find_recovery_candidates() keeps filtering on
│                                 # recovery_eligible; its meaning changed upstream only
├── validation.py                # MODIFIED (additive fields only): analyze_accuracy() reports
│                                 # the new tier breakdown alongside existing recall/precision
├── validation_models.py         # MODIFIED (additive): AccuracyReport gains tier-breakdown
│                                 # and ordering-conflict fields
└── diagnostics.py                # MODIFIED (additive): extends the existing metadata.validate
                                    # diagnostics record with the new operational metrics
                                    # (spec FR-010)

config/default.yaml               # MODIFIED (additive): new `metadata.anchor_validation` block

tests/contract/
├── test_metadata_alignment_contract.py     # MODIFIED: recovery_eligible semantics assertions
│                                            # updated to reflect validation-gated meaning
└── test_anchor_validation_contract.py      # NEW

tests/unit/
├── test_metadata_alignment.py              # MODIFIED
└── test_anchor_validation.py               # NEW

tests/integration/
└── test_metadata_validation_real_dataset.py  # MODIFIED: extended with the real ww_vs_pf
                                                 # fixture data that originally surfaced this bug
```

**Structure Decision**: Extends the existing `src/cvip/metadata/` package (013's own structure)
with two new sibling files for the validation sub-step, following this package's own established
one-file-set-per-concern convention (`extraction.py`/`extraction_models.py`,
`recovery.py`/`recovery_models.py`, etc.) — Anchor Validation is a *concern* within Stage 2, not
a new pipeline stage, so it does not get a new numbered stage in the contract, but it does get
its own file-set exactly as `video/`'s `scoreboard_ocr.py` + `scoreboard_parsers.py` +
`scoreboard_preprocessing.py` already split one module into concern-specific files without
creating a new module. Per CLAUDE.md's package-layout convention, this stays in
`src/cvip/metadata/`, not `src/cvip/video/` (it consumes already-persisted OCR output; it does
not consume frames).

## Complexity Tracking

*No Constitution Check violations — this section is not needed.*
