# Implementation Plan: Club Broadcast Overlay Support (Scoreboard OCR Amendment)

**Branch**: `011-club-broadcast-overlay-support` | **Date**: 2026-07-29 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/011-club-broadcast-overlay-support/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

Adds a second, automatically-selected parser strategy to Scoreboard OCR's structured-parsing stage so that a club-cricket (CricHeroes-style) broadcast overlay — which packs runs/wickets/over/ball into one compound string (`0-0/0.0(20)`) and carries no "B:" bowler label or "*" striker marker — produces usable readings instead of every one failing `PLAYER_PARSE_FAILED`. The parsing stage is restructured around a `_ScoreParser` Strategy interface (research.md Decision 5): `GenericBroadcastParser` (the original module's pre-amendment logic, relocated verbatim) and `ClubBroadcastParser` (this amendment's compound-score + best-effort-name logic) are two interchangeable implementations, selected per-reading by a pure, deterministic `_select_parser(tokens)` function — never caller-configured, so a single run can freely mix both formats. The pipeline is now an explicit five-stage sequence: OCR → Parser Strategy Selection → Structured Parsing → Cricket Rule Validation → Scoreboard Sample (research.md "Pipeline"). The new strategy reuses the existing `_validate_reading()` monotonic-rule logic and `ScoreboardSample`/`OCREvidence` shapes unchanged — it only adds `parsed_fields["parser_strategy"]`, `parsed_fields["raw_compound_score_token"]`, and `parsed_fields["batter_attribution"]` markers (research.md Decisions 4 and 6) so the selected strategy, matched evidence, and name confidence all remain distinguishable in diagnostics without touching any public contract. `GenericBroadcastParser` carries the original code forward unmodified, which is how FR-002/FR-009/FR-010/FR-011's zero-regression requirement is met structurally, not just by test coverage. A reading matching neither format's specific signal still falls through to `GenericBroadcastParser` and resolves to the existing `PLAYER_PARSE_FAILED` outcome — "unknown layout" is diagnosable via `parser_strategy` alone and never becomes a new failure-taxonomy value (research.md Decision 7).

## Technical Context

**Language/Version**: Python 3.11+ (unchanged from `specs/005-scoreboard-ocr/plan.md`)

**Primary Dependencies**: None new. Reuses `pytesseract`/Tesseract, OpenCV preprocessing, and the Frame Extraction Service exactly as the original module does — this amendment only changes token-parsing logic inside `src/cvip/video/scoreboard_ocr.py`, `re` (stdlib) regex patterns.

**Storage**: N/A — unchanged from the original module; still an in-memory `ScoreboardOcrResult`, no schema change (`batter_attribution` lives inside the existing internal `OCREvidence.parsed_fields` dict, not a new column).

**Testing**: pytest — new unit test cases added to the existing `tests/unit/test_scoreboard_ocr_validation.py` (compound-score parsing, best-effort name extraction, mixed-format run, multi-word names, team-name-not-mistaken-for-player-name, and a shared-validation-rule case proving FR-009's parser-agnostic guarantee — added per `/speckit-analyze` finding C1), a regression re-run of the existing `tests/contract/`, `tests/integration/`, and `tests/benchmark/` suites (must pass unmodified — proves FR-002), a **mandatory** synthetic cross-module test in `tests/integration/test_scoreboard_ocr_e2e.py` that builds a deterministic timeline directly from `ClubBroadcastParser` output and feeds it into Event Detection's `detect_events()` to prove SC-005 without needing a real video (added per `/speckit-analyze` finding E1 — SC-005 must not depend solely on an optional fixture), and one further, genuinely optional fixture-backed case in the same file if a short clip of the real overlay is added under `tests/fixtures/` (see quickstart.md).

**Target Platform**: Windows 11 desktop, CPU-only x86_64 (unchanged).

**Project Type**: Single project — amends one existing file (`src/cvip/video/scoreboard_ocr.py`) in `src/cvip/video/`; no new module, no new subpackage.

**Performance Goals**: No new performance budget — the amendment adds a handful of extra regex checks per reading (bounded, O(tokens)), negligible against the module's existing ~15-25 minute share of the 40-minute budget (`specs/005-scoreboard-ocr/plan.md`). No new Tesseract calls, no change to the ROI-unchanged skip.

**Constraints**: Same as the original module (offline, CPU-only, single forward pass, deterministic output, never hard-fails on one bad reading) plus this amendment's own: MUST NOT alter behavior for any reading that does not contain a compound-score-shaped token (FR-002); format selection MUST be automatic from OCR text, not new caller configuration (spec.md, out of a "quick OCR tuning experiment" alternative explicitly rejected earlier in this feature's discovery).

**Scale/Scope**: Same run shape as the original module — one extra classification branch per sampled frame's token list; no change to sample count, ROI, or sampling rate.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate | Status |
|---|---|---|
| I. Offline-First, Always | No network/cloud calls | PASS — pure local regex/string logic, no new dependency |
| II. Performance is Non-Negotiable | Fits 40 min / 6GB / CPU-only | PASS — added work is a bounded number of regex matches per already-tokenized reading; no new Tesseract calls, no new frame reads |
| III. Single-Pass Analysis Principle | No reprocessing | PASS — unaffected; this amendment doesn't touch sampling or frame access |
| IV. Detection Accuracy Requirements | Confidence score on every event | PASS — every `ScoreboardSample` still carries `ocr_confidence`/`parse_confidence` unchanged; the new `batter_attribution` marker is additive diagnostics, not a replacement confidence value. Striker-accuracy itself is knowingly best-effort (spec.md Out of Scope, matches the original module's own documented innings-transition heuristic precedent) |
| V. Modular & Extensible Architecture | Independently testable, clear I/O contract | PASS — no public contract change (see contracts/scoreboard_ocr_contract_amendment.md); the two parsing paths are cleanly separated behind a `_ScoreParser` Strategy interface (research.md Decision 5), not an inline branch — a future third overlay format is one new class + one tuple entry, with zero change to `extract_scoreboard()`'s signature or any public dataclass |
| VI. Fail Fast, Never Silently | No silent fallback | PASS — a reading that fits neither format still resolves to `PLAYER_PARSE_FAILED` exactly as today (FR-008); nothing is guessed past what the heuristic explicitly documents |
| VII. Test-First Development | Contract tests, 100% coverage on critical paths | PASS — new unit tests written before implementation per tasks.md; full existing suite re-run as the regression gate |

No violations identified. Complexity Tracking table not required.

**Post-Phase 1 re-check**: Design artifacts (research.md, data-model.md, contracts/, quickstart.md) introduce no new dependency, no new public entity, and no schema change. All gates above still PASS after design.

## Project Structure

### Documentation (this feature)

```text
specs/011-club-broadcast-overlay-support/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/           # Phase 1 output (/speckit-plan command)
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
src/cvip/video/
├── scoreboard_ocr.py           # AMENDED: structured-parsing stage restructured behind a new
│                                #   internal _ScoreParser strategy interface (research.md Decision 5)
│                                #   -- GenericBroadcastParser (original _parse_fields() loop body,
│                                #   relocated verbatim) and ClubBroadcastParser (new); _select_parser()
│                                #   (pure, deterministic) replaces the old single _parse_fields() entry
│                                #   point; new module-level regexes (_COMPOUND_SCORE_RE, _STATS_MARKER_RE).
│                                #   _validate_reading(), _process_frame()'s OCR step, the ROI-unchanged
│                                #   skip, and _LastAcceptedReading are all untouched (research.md
│                                #   Decision 9 -- OCR confidence capture precedes parser selection).
├── scoreboard_ocr_models.py     # UNCHANGED — ScoreboardSample/OCREvidence/ScoreboardOcrRequest/Result
└── scoreboard_ocr_errors.py     # UNCHANGED — ValidationFailureReason already covers PLAYER_PARSE_FAILED

tests/
├── contract/
│   └── test_scoreboard_ocr_contract.py    # UNCHANGED, re-run as regression gate
├── integration/
│   └── test_scoreboard_ocr_e2e.py         # AMENDED: +1 mandatory synthetic ClubBroadcastParser ->
│                                            #   detect_events() test proving SC-005 (finding E1), +1
│                                            #   further optional real-overlay fixture case
├── unit/
│   └── test_scoreboard_ocr_validation.py  # AMENDED: new test cases for compound-score parsing,
│                                            #   best-effort batter/non_striker/bowler extraction,
│                                            #   multi-word names, team-name exclusion, mixed-format
│                                            #   runs, parser-strategy selection determinism
│                                            #   (_select_parser() called twice on identical tokens
│                                            #   returns the same strategy), original-format
│                                            #   zero-regression checks, and a shared-validation-rule
│                                            #   case proving _validate_reading() fires identically for
│                                            #   a ClubBroadcastParser-produced reading (finding C1)
└── benchmark/
    └── test_scoreboard_ocr_performance.py # UNCHANGED, re-run as regression gate
```

**Structure Decision**: Single project, amend-in-place. No new file-set is created because this is a parsing-logic amendment to an existing module, not a new module — consistent with `specs/011-club-broadcast-overlay-support/spec.md`'s framing as an *amendment* to `specs/005-scoreboard-ocr/`, not a replacement or a new pipeline stage. `scoreboard_ocr_models.py`/`scoreboard_ocr_errors.py` need no changes since no new public entity or failure reason is introduced (data-model.md); the new `_ScoreParser`/`GenericBroadcastParser`/`ClubBroadcastParser` classes are module-private additions to `scoreboard_ocr.py` itself, not a new file, since they have no reason to be imported from outside this module. Parser-strategy usage counts (Decision 8) are folded into the existing `ExecutionDiagnostics.output_summary` free-text field `scoreboard_ocr.py` already populates — `src/cvip/common/diagnostics.py`, shared cross-module infrastructure, needs no change.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

None — the Constitution Check above found no violations, so no complexity needs justifying.
