# Implementation Plan: Event Detection

**Branch**: `007-event-detection` | **Date**: 2026-07-29 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/007-event-detection/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

Detects `FOUR`, `SIX`, `WICKET`, and `TEAM_MILESTONE` events by diffing consecutive entries in the OCR Timeline Smoother's cleaned scoreboard timeline (Module 4a), consulting Scoreboard OCR's raw result (Module 4) only for confidence lookup and Replay Detection's segments (Module 3) only for the `is_replay` flag. Internally, each comparison flows through a fixed five-stage pipeline (Timeline Comparison → Event Rule Engine → Replay Annotation → Confidence Assignment → Importance Assignment, spec.md Processing Model) built around a precedence-ordered rule engine: an innings-transition heuristic and `WICKET` take priority over `FOUR`/`SIX` for the same comparison (mutually exclusive), while `TEAM_MILESTONE` is evaluated independently and may co-occur with any of them. This is the second module on the platform (after Module 4a) with no video/frame dependency at all — its three inputs are already-structured Python objects from three upstream modules, not frames or OCR text.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: None beyond the standard library and this platform's own prior modules — reuses `cvip.video.ocr_timeline_smoother_models` (`OCRTimelineSmootherResult`/`CleanedScoreboardSample`, the primary diffing input), `cvip.video.scoreboard_ocr_models` (`ScoreboardOcrResult`/`ScoreboardSample`, consulted only for `ocr_confidence`/`parse_confidence` lookup by timestamp), `cvip.video.replay_detection_models` (`ReplayDetectionResult`/`ReplaySegment`, consulted only for the `is_replay` check), and `cvip.common.diagnostics` (`DiagnosticsTracker`/`ExecutionDiagnostics`/`emit_diagnostics`). No OpenCV, no `pytesseract`, no FFmpeg, no `numpy` — the second module in the pipeline (after the OCR Timeline Smoother) with zero new external dependencies, since all three inputs are already fully-structured in-memory Python objects.

**Storage**: N/A — returns an in-memory `EventDetectionResult`, consistent with every prior module; the Pipeline Orchestrator remains solely responsible for persisting rows into the `events` table (spec.md Key Entities; `specs/technical_plan.md` Database Schema).

**Testing**: pytest — contract test for the module boundary (entry point shape, error taxonomy); unit tests for each detection rule (FR-004 through FR-011), the full precedence model (FR-023: `WICKET` > `FOUR`/`SIX` mutual exclusion, `TEAM_MILESTONE` orthogonality/co-occurrence), the single-legal-ball-advance guard (FR-006a) including over/ball rollover, the innings-transition heuristic (FR-010), `null`-field comparison skipping (FR-009), `EventEvidence` field completeness (FR-024), `event_key` determinism/uniqueness (FR-025, SC-007), `milestone_value` population (FR-026), and the `importance`-never-gates-detection guarantee (FR-027); an integration test built entirely from synthetic in-memory `OCRTimelineSmootherResult`/`ScoreboardOcrResult`/`ReplayDetectionResult` fixtures (no video/frame fixtures needed, matching Module 4a's precedent) covering confidence derivation (FR-014), replay flagging (FR-016), and both failure-taxonomy rejections (FR-020); a benchmark test for SC-004 (~12,600 synthetic cleaned samples, <1 minute).

**Target Platform**: Windows 11 desktop, CPU-only — trivially satisfied, same as Module 4a: there is no OpenCV/Tesseract/video-decode surface at all, so the constitution's CPU-only/no-GPU/offline gates are structurally guaranteed by this feature's architecture.

**Project Type**: Single project. Per CLAUDE.md's Package Layout section, Event Detection is explicitly **not** part of the frame-analysis chain (Modules 1, 1a, 2, 3, 4, 4a) that shares `src/cvip/video/` — it gets its own subpackage, `src/cvip/events/`, per the pattern documented in `specs/001-video-loader/plan.md` Project Structure (which already reserved this directory as scaffolding).

**Performance Goals**: Completes in under 1 minute for a full match's ~12,600 cleaned samples (SC-004, matching `specs/technical_plan.md`'s Performance Targets budget for this module) — achievable via a single O(n) pass over an in-memory list of dataclasses, plus an O(1) or O(log n) timestamp lookup into the raw OCR result and replay segments per detected event (not per sample).

**Constraints**: Fully offline and CPU-only (both trivially true — no external calls of any kind); deterministic output for the same inputs and configuration (FR-021); `event_key` uniqueness and stability (FR-025, SC-007); strict stage-order separation between detection and enrichment (FR-022, FR-027 — `importance` and `confidence` must never influence whether an event fires); 2-value-or-more failure taxonomy with a diagnostics record emitted on every exit path, including rejected input (FR-019, FR-020); cooperative cancellation that still emits exactly one diagnostics record for a partial run (FR-018).

**Scale/Scope**: One `EventDetectionRequest` (cleaned timeline + raw OCR result + replay timeline + config) per detection run; up to ~12,600 cleaned samples for a full 3-4 hour match; single-process, synchronous, one sequential O(n) pass with per-event enrichment lookups.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate | Status |
|---|---|---|
| I. Offline-First, Always | No network/cloud calls anywhere | PASS (trivially) — this feature makes no external calls of any kind; all three inputs are already in-memory Python objects from prior modules |
| II. Performance is Non-Negotiable | Fits within the overall 40 min / 6GB / CPU-only budget | PASS (trivially) — SC-004's own <1 minute ceiling is a tiny fraction of the platform budget, achieved by a plain O(n) pass with no OCR/decode cost |
| III. Single-Pass Analysis Principle | Each match analyzed only once, no reprocessing | PASS — this feature doesn't decide whether `cvip analyze` re-runs; that remains the Pipeline Orchestrator's responsibility, same as every prior module |
| IV. Detection Accuracy Requirements | Confidence scores on detected events; contributes to ≥95% detection accuracy | PASS (with a documented dependency) — every `Detected Event` carries a `confidence` derived from the bracketing raw OCR readings (FR-014, SC-002); SC-001's ≥95% accuracy claim depends on the platform's golden dataset, which doesn't exist yet (same documented gap every prior module's own accuracy criterion has carried) |
| V. Modular & Extensible Architecture | Independently testable, clear I/O contract | PASS — accepts an `EventDetectionRequest` (three upstream results + config), produces a self-contained `EventDetectionResult`; the Processing Model's stage separation and precedence model (FR-022, FR-023) are explicitly designed so a future event type is added within the Event Rule Engine stage only (spec.md Scope & Extensibility) |
| VI. Fail Fast, Never Silently | Crash loudly on structural failure, no silent fallback, detailed logging | PASS — FR-020's failure taxonomy covers missing/malformed input with a specific reason; FR-019 requires a diagnostics record on every exit path; a skipped comparison (`null` fields, innings transition) is always explicitly recorded via `EventEvidence`, never silently dropped without a trace |
| VII. Test-First Development | Contract tests at module boundary; 100% coverage on critical paths | PASS — contract tests planned ahead of implementation; coverage gate planned in tasks.md Polish phase, matching the established precedent from all prior features |

No violations identified. Complexity Tracking table not required.

**Post-Phase 1 re-check**: Design artifacts (data-model.md, contracts/, quickstart.md) introduce no new dependency, no storage, and no network/GPU surface — the rule engine, `EventEvidence` capture, and `event_key` derivation (research.md) are all pure in-memory constructs over existing dataclasses. All gates above still PASS after design; no re-justification needed.

## Project Structure

### Documentation (this feature)

```text
specs/007-event-detection/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md        # Phase 1 output (/speckit-plan command)
├── quickstart.md        # Phase 1 output (/speckit-plan command)
├── contracts/           # Phase 1 output (/speckit-plan command)
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
src/cvip/
├── common/
│   └── diagnostics.py    # existing — reused as-is for ExecutionDiagnostics/emit_diagnostics
├── video/
│   ├── ocr_timeline_smoother_models.py  # existing — OCRTimelineSmootherResult/CleanedScoreboardSample, this feature's primary input
│   ├── scoreboard_ocr_models.py         # existing — ScoreboardOcrResult/ScoreboardSample, consulted for confidence lookup only
│   └── replay_detection_models.py       # existing — ReplayDetectionResult/ReplaySegment, consulted for is_replay only
└── events/                # NEW subpackage — Event Detection is not part of the video/ frame-analysis
    │                       # chain (CLAUDE.md Package Layout); this directory was reserved as empty
    │                       # scaffolding by specs/001-video-loader/plan.md and is populated here for
    │                       # the first time.
    ├── __init__.py         # NEW
    ├── models.py           # NEW: DetectedEvent, EventEvidence, EventDetectionRequest, EventDetectionResult
    ├── errors.py           # NEW: EventDetectionFailureReason + EventDetectionError
    └── detection.py        # NEW: EventDetectionRunner class + detect_events() entry point;
                             # the five-stage pipeline (Processing Model) and precedence-ordered
                             # rule engine (FR-023)

tests/
├── contract/
│   └── test_event_detection_contract.py     # asserts events/detection.py matches contracts/event_detection_contract.md
├── integration/
│   └── test_event_detection_e2e.py          # synthetic in-memory fixtures across all three upstream result types
├── unit/
│   └── test_event_detection_rules.py        # per-rule detection, precedence, EventEvidence, event_key, milestone_value
└── benchmark/
    └── test_event_detection_performance.py  # SC-004 (<1 minute) against a synthetic ~12,600-sample timeline
```

**Structure Decision**: Single project (Option 1). Unlike Modules 1, 1a, 2, 3, 4, and 4a — which all share `src/cvip/video/` per CLAUDE.md's documented convention for the frame-analysis chain — Event Detection gets its own subpackage, `src/cvip/events/`, exactly as CLAUDE.md's Package Layout section directs ("Event Detection, Event Ranking, Clip Generator, Video Stitcher... should get its own subpackage per its own concern... rather than also being folded into `video/`") and exactly as `specs/001-video-loader/plan.md` originally scaffolded (`events/  # empty scaffolding — populated by the Event Detection feature`). Within `events/`, files use the short-name convention Video Loader itself established (`models.py`, `errors.py`, and a primary module named after its function — `detection.py`, not `event_detection.py`), since this subpackage hosts exactly one module and doesn't need the longer disambiguating prefix that `video/`'s multi-module files require. No new test fixtures are created; this feature's tests build `OCRTimelineSmootherResult`/`ScoreboardOcrResult`/`ReplayDetectionResult` instances directly in Python, since it has no video dependency to fixture against.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

None — the Constitution Check above found no violations, so no complexity needs justifying.
