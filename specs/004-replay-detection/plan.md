# Implementation Plan: Replay Detection

**Branch**: `004-replay-detection` | **Date**: 2026-07-28 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/004-replay-detection/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

Detects broadcast replay footage by combining five independently-weighted signals into one confidence score per candidate segment (Scene Detection-derived), thresholded to decide replay/not-replay. Four signals (logo presence, scoreboard-region absence, motion profile, camera-angle difference) are computed by this feature itself, sampled at the platform's existing 1 FPS rate and characterized via comparison against a rolling "live-action baseline" the detector maintains as it walks the video — a shared computational pattern across all three baseline-relative signals. The fifth (transition) is consumed as-is from Scene Detection's own `REPLAY_TRANSITION` classification/confidence. Returns an in-memory result; the `replays` table schema is updated (this plan) to fit the weighted-confidence design instead of the incompatible 3-value `detection_method` enum it previously had.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: OpenCV (`opencv-python`) for all frame-level signal computation (template matching for logo presence, simple edge/variance measures for scoreboard-region content, frame-difference magnitude for motion profile, downscaled frame comparison for camera-angle) — no new dependency introduced, all via APIs already used by Video Loader/Scene Detection. Reuses the Frame Extraction Service (`cvip.video.frame_extraction`) for all frame access, Scene Detection's (`cvip.video.scene_detection`) result type for candidate-segment boundaries and the transition signal, and `cvip.common.diagnostics` for the standardized diagnostics record.

**Storage**: N/A for this feature directly — it returns an in-memory result (spec.md FR-026), consistent with every other detection module on this platform. However, this plan updates the *shape* of the existing `replays` table in `specs/technical_plan.md`'s schema (a cross-cutting document, not owned by this feature alone) so the Pipeline Orchestrator can persist this feature's output once it exists.

**Testing**: pytest, per project convention and constitution Principle VII — contract tests for the module boundary, unit tests for the four signal computations and the weighted-combination/validation logic, integration tests against real fixture videos (reusing `tests/fixtures/video_loader/`), and a benchmark test for the time-budget success criterion.

**Target Platform**: Windows 11 desktop, CPU-only x86_64 (Intel Core i3-1115G4 class hardware) — same as the rest of the platform.

**Project Type**: Single project — a Python module inside `src/cvip/video/`, alongside Video Loader, the Frame Extraction Service, and Scene Detection (it directly consumes Scene Detection's result type and Frame Extraction Service's frames, so keeping it in the same subpackage avoids a new cross-package dependency that isn't already implied).

**Performance Goals**: Completes within its ~2-5 minute share of the platform's overall analysis budget (SC-004, `specs/technical_plan.md` Performance Targets) — achieved by sampling all four self-computed signals at the platform's existing 1 FPS rate (`config/default.yaml`'s `video.sample_fps`) rather than native frame rate, resolving spec.md's open question about motion-profile's sampling-density needs (research.md Decision 2).

**Constraints**: Fully offline (no network calls); CPU-only (no GPU dependency); exactly one forward pass over the video (FR-019); deterministic output across repeated runs (FR-024, including whatever sampling strategy is used); five-value failure taxonomy (FR-022) with a diagnostics record emitted on every exit path, including a configuration-validation failure.

**Scale/Scope**: One `LoadResult` + one Scene Detection result (one video) per detection run; match recordings up to at least 4 hours (inherited scope); five signals (four computed, one reused); single-process, synchronous.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate | Status |
|---|---|---|
| I. Offline-First, Always | No network/cloud calls anywhere in the detection path | PASS — OpenCV-based signal computation operates on locally-supplied frame data only (FR-020) |
| II. Performance is Non-Negotiable | Fits within the 40 min / 6GB / CPU-only budget | PASS — single forward pass (FR-019) at the existing 1 FPS rate keeps this within its documented ~2-5 minute share; this is an independent extraction pass over the Frame Extraction Service, already priced as a separate line item in `specs/technical_plan.md`'s per-module budget table (same reasoning established in `specs/002-frame-extraction-service/plan.md` and `specs/003-scene-detection/plan.md`) |
| III. Single-Pass Analysis Principle | Each match analyzed only once, no reprocessing of an already-analyzed match | PASS — this feature doesn't decide whether to re-run `cvip analyze`; that's the Pipeline Orchestrator's job |
| IV. Detection Accuracy Requirements | Confidence scores on detected events; ≥90% replay-removal accuracy | PASS (with a documented dependency) — every segment carries a mandatory confidence (FR-013); the ≥90% target (SC-009) depends on the platform's golden dataset, which does not yet exist (`specs/technical_plan.md`'s "Golden Dataset & Accuracy Verification" section) — this feature's own test suite validates the mechanics (weighted combination, thresholding, graceful degradation), not the real-world accuracy number itself, consistent with how that section already scopes this limitation platform-wide |
| V. Modular & Extensible Architecture | Independently testable, clear I/O contract | PASS — accepts a `LoadResult` + Scene Detection result, produces a `ReplayDetectionResult`; the "sole owner of replay classification" rule (FR-028) and Out of Scope section keep this module from expanding into Event Detection's or Clip Generator's responsibilities; FR-006's "extensible for future signals" requirement is honored by the signal-evaluation design in research.md |
| VI. Fail Fast, Never Silently | Crash loudly, no silent fallback, detailed logging | PASS — FR-022's five-value failure taxonomy covers every mid-run and pre-run failure mode with a specific reason; FR-025 requires a diagnostics record on every exit path, including a rejected configuration |
| VII. Test-First Development | Contract tests at module boundary; 100% coverage on critical paths | PASS — contract tests planned ahead of implementation; coverage gate planned in tasks.md Polish phase, matching the established precedent from all three prior features |

No violations identified. Complexity Tracking table not required.

**Post-Phase 1 re-check**: Design artifacts (data-model.md, contracts/, quickstart.md) introduce no new dependencies, network surface, or GPU dependency beyond what's captured above. The `replays` table schema update (research.md Decision 1) is a compatibility fix to an existing cross-cutting schema, not a new storage concern this feature owns — this feature still returns an in-memory result only (FR-026). All gates above still PASS after design; no re-justification needed.

## Project Structure

### Documentation (this feature)

```text
specs/004-replay-detection/
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
├── __init__.py                                              # existing — unchanged
├── loader.py, metadata.py, hashing.py, models.py, errors.py # existing (Video Loader) — unchanged
├── frame_extraction.py, frame_extraction_models.py, frame_extraction_errors.py  # existing (Frame Extraction Service) — unchanged
├── scene_detection.py, scene_detection_models.py, scene_detection_errors.py     # existing (Scene Detection) — unchanged
├── replay_detection_models.py   # NEW: ReplaySegment, ReplayEvidence, ReplayDetectionRequest, ReplayDetectionResult
├── replay_detection_errors.py   # NEW: ReplayDetectionFailureReason enum (distinct taxonomy from the other three modules' errors)
└── replay_detection.py          # NEW: ReplayDetector class + detect_replays() entry point, the four signal computations, and the live-action baseline tracker

tests/
├── contract/
│   └── test_replay_detection_contract.py    # asserts replay_detection.py matches contracts/replay_detection_contract.md
├── integration/
│   └── test_replay_detection_e2e.py         # reuses tests/fixtures/video_loader/ fixtures via load_video() + extract_frames() + detect_scenes()
├── unit/
│   └── test_replay_detection_validation.py  # signal computations, weight/threshold validation, baseline-tracker logic, edge cases
└── benchmark/
    └── test_replay_detection_performance.py # SC-004 (time budget) against the multi-hour fixture
```

**Structure Decision**: Single project (Option 1), extending the existing `src/cvip/video/` subpackage established by Video Loader, the Frame Extraction Service, and Scene Detection — this feature's inputs (`LoadResult`, `extract_frames()`, Scene Detection's result type) already live there. New files use a `replay_detection_*` naming prefix, following the exact precedent set by the two prior additions to this subpackage. No new test fixtures are created; this feature's tests reuse Video Loader's existing fixtures via `load_video()` → `detect_scenes()` → this feature's own request construction.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

None — the Constitution Check above found no violations, so no complexity needs justifying.
