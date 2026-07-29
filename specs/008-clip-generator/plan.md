# Implementation Plan: Clip Generator

**Branch**: `008-clip-generator` | **Date**: 2026-07-29 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/008-clip-generator/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

Turns an already-filtered sequence of detected events (Module 5's `DetectedEvent`-shaped output) into an ordered, non-overlapping `ClipPlan` — the input Module 9 (Video Stitcher) will cut and stitch. Each event's raw pre-roll/post-roll window is computed and boundary-clamped unconditionally (Processing Model stages 2-3), replay-flagged events are then dropped unless explicitly included (stage 4), and surviving windows are merged via a single sorted sweep that tags each join with a `MergeReason` (`OVERLAP`/`GAP_THRESHOLD`/`CHAIN_MERGE`, stage 5) before final ordering (stage 6). An internal `ClipEvidence` trail — one record per *input* event, including replay-excluded ones — preserves full derivation traceability for diagnostics and future tuning, mirroring Module 5's `EventEvidence`/`event_key` precedent.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: None beyond the standard library and this platform's own prior modules — accepts `DetectedEvent`-shaped records (Module 5, `cvip.events.models`) as input (by structural shape: `event_key`/`timestamp_seconds`/`is_replay`, not a hard import dependency — see research.md Decision 7), and reuses `cvip.common.diagnostics` (`DiagnosticsTracker`/`ExecutionDiagnostics`/`emit_diagnostics`). No OpenCV, no `pytesseract`, no FFmpeg, no `numpy` — this module never touches a video file or frame, matching Module 5's own precedent as a pure in-memory data-transformation stage.

**Storage**: N/A — returns an in-memory `ClipPlan`, consistent with every prior module; the Pipeline Orchestrator remains solely responsible for persisting `clip_start_seconds`/`clip_end_seconds` back onto `events` rows, if desired (spec.md FR-019).

**Testing**: pytest — contract test for the module boundary (entry point shape, error taxonomy); unit tests for each Processing Model stage in isolation (window generation, clamping, replay filtering, merge — including transitive chains and `MergeReason` tagging), the FR-009 tie-break rule, `clip_id` determinism (FR-010), and `ClipEvidence` completeness (FR-016, SC-008); an integration test built entirely from synthetic in-memory `DetectedEvent`-shaped fixtures (no video/frame/database fixtures needed, matching Module 5's own precedent) covering the full pipeline end-to-end including replay inclusion/exclusion and boundary clamping; a lightweight benchmark test for SC-006 (a few hundred synthetic events, well under the 2-minute `generate` budget).

**Target Platform**: Windows 11 desktop, CPU-only — trivially satisfied: there is no OpenCV/Tesseract/video-decode surface at all, so the constitution's CPU-only/no-GPU/offline gates are structurally guaranteed by this feature's architecture, matching Module 5's own precedent.

**Project Type**: Single project. Per CLAUDE.md's Package Layout section, Clip Generator is explicitly **not** part of the frame-analysis chain (Modules 1, 1a, 2, 3, 4, 4a) that shares `src/cvip/video/` — it gets its own subpackage, `src/cvip/clips/`, already reserved as empty scaffolding (populated here for the first time, the same way `src/cvip/events/` was reserved scaffolding until Module 5 populated it).

**Performance Goals**: Negligible relative to the platform's overall `generate` budget of under 2 minutes (spec.md SC-006) — a single-digit-millisecond, pure in-memory computation over on the order of a few hundred events, dominated entirely by Module 9's actual FFmpeg work, not this stage.

**Constraints**: Fully offline and CPU-only (both trivially true — no external calls of any kind); deterministic output for the same inputs and configuration, including `clip_id`, `source_event_ids` order, and `MergeReason` assignments (FR-014); strict stage-order separation per the Processing Model (FR-018); a two-value failure taxonomy with a diagnostics record emitted on every exit path, including rejected input (FR-015, FR-017); no database writes of any kind (FR-019).

**Scale/Scope**: One `ClipGenerationRequest` (already-filtered event sequence + source video path/duration + clip settings + replay-inclusion flag) per `generate` invocation; on the order of a few hundred detected events for a full match's worth of filtered highlights; single-process, synchronous, one sequential pass plus a sorted merge sweep.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate | Status |
|---|---|---|
| I. Offline-First, Always | No network/cloud calls anywhere | PASS (trivially) — this feature makes no external calls of any kind; its only input is an already-filtered in-memory event sequence and caller-supplied numeric settings |
| II. Performance is Non-Negotiable | Fits within the overall 40 min / 6GB / CPU-only budget (or, for `generate`, the <2 min highlight-gen budget) | PASS (trivially) — SC-006's expectation is a negligible fraction of the 2-minute `generate` budget, achieved by a plain O(n log n)-worst-case, O(n)-common-case pass with no OCR/decode/FFmpeg cost of its own |
| III. Single-Pass Analysis Principle | Each match analyzed only once, no reprocessing | PASS — this is a Phase 2 (`generate`) module by design; it never re-runs analysis (Modules 1-7) and only operates on already-persisted event data (spec.md FR-013), consistent with PRD Section 6's Phase 2 restriction |
| IV. Detection Accuracy Requirements | Confidence scores on detected events; contributes to ≥95% detection accuracy | N/A — this module detects nothing; it windows and merges events Module 5 already detected and scored. It does not read, alter, or depend on `confidence` (spec.md Assumptions: only `event_key`/`timestamp_seconds`/`is_replay` are read) |
| V. Modular & Extensible Architecture | Independently testable, clear I/O contract | PASS — accepts a `ClipGenerationRequest` (event sequence + video path/duration + clip settings), produces a self-contained `ClipPlan`; the Processing Model's six-stage separation (spec.md) is explicitly structured so replay-inclusion policy, merge-gap tuning, or a future clip-metadata field can each change within one stage without touching the others |
| VI. Fail Fast, Never Silently | Crash loudly on structural failure, no silent fallback, detailed logging | PASS — FR-015's failure taxonomy covers missing/malformed input and invalid clip settings (negative/non-finite) with a specific reason; FR-017 requires a diagnostics record on every exit path; every input event's disposition (contributed to a clip, or replay-excluded) is always explicitly recorded via `ClipEvidence`, never silently dropped without a trace (FR-016, SC-008) |
| VII. Test-First Development | Contract tests at module boundary; 100% coverage on critical paths | PASS — contract tests planned ahead of implementation; coverage gate planned in tasks.md Polish phase, matching the established precedent from all prior features |

No violations identified. Complexity Tracking table not required.

**Post-Phase 1 re-check**: Design artifacts (data-model.md, contracts/, quickstart.md) introduce no new dependency, no storage, and no network/GPU surface — the Merge Engine, `ClipEvidence` capture, and `clip_id` derivation (research.md) are all pure in-memory constructs over plain dataclasses/tuples. All gates above still PASS after design; no re-justification needed.

## Project Structure

### Documentation (this feature)

```text
specs/008-clip-generator/
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
├── events/
│   └── models.py         # existing — DetectedEvent, the structural shape this module's input events match
└── clips/                 # NEW population — Clip Generator is not part of the video/ frame-analysis
    │                       # chain (CLAUDE.md Package Layout); this directory was reserved as empty
    │                       # scaffolding (the same pattern src/cvip/events/ followed until Module 5)
    │                       # and is populated here for the first time.
    ├── __init__.py         # existing (empty)
    ├── models.py           # NEW: ClipGenerationRequest, PlannedClip, ClipPlan, ClipEvidence,
    │                        #      MergeReason (enum) -- the Merge Engine's internal sweep state
    │                        #      (group_start/group_end/group_anchor_end/group_members) is plain
    │                        #      local state within generator.py, not a data-model.md entity
    │                        #      (see data-model.md "Merge Engine Internal State")
    ├── errors.py           # NEW: ClipGenerationFailureReason + ClipGenerationError
    └── generator.py        # NEW: ClipGeneratorRunner class + generate_clips() entry point;
                             # the six-stage Processing Model (Filtered Events -> Clip Window
                             # Generation -> Boundary Clamping -> Replay Filtering -> Merge Engine
                             # -> Ordered Clip Plan)

tests/
├── contract/
│   └── test_clip_generator_contract.py     # asserts clips/generator.py matches contracts/clip_generator_contract.md
├── integration/
│   └── test_clip_generator_e2e.py          # synthetic in-memory DetectedEvent-shaped fixtures
├── unit/
│   └── test_clip_generator_rules.py        # per-stage: windowing, clamping, replay filter, merge
│                                             # (incl. transitive chains, MergeReason tagging, tie-break),
│                                             # clip_id determinism, ClipEvidence completeness
└── benchmark/
    └── test_clip_generator_performance.py  # SC-006 (well under the 2-minute generate budget)
                                              # against a few hundred synthetic events
```

**Structure Decision**: Single project (Option 1). Like Event Detection (Module 5) — and unlike Modules 1, 1a, 2, 3, 4, and 4a, which share `src/cvip/video/` — Clip Generator gets its own subpackage, `src/cvip/clips/`, exactly as CLAUDE.md's Package Layout section directs and exactly as `specs/001-video-loader/plan.md` originally scaffolded (`clips/  # empty scaffolding — populated by the Clip Generator feature`). Within `clips/`, files use the same short-name convention `events/` established (`models.py`, `errors.py`, and a primary module named after its function — `generator.py`, not `clip_generator.py`), since this subpackage hosts exactly one primary module and doesn't need a longer disambiguating prefix. No new test fixtures are created; this feature's tests build `DetectedEvent`-shaped instances directly in Python, since it has no video or database dependency to fixture against.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

None — the Constitution Check above found no violations, so no complexity needs justifying.
