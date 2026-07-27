# Implementation Plan: Scene Detection

**Branch**: `003-scene-detection` | **Date**: 2026-07-27 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/003-scene-detection/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

Segments a validated cricket match video into an ordered list of scene boundaries — each with a stable ID, a timestamp, a classification (`ORDINARY_CUT` or `REPLAY_TRANSITION`), and a mandatory confidence score — consumed within the same `cvip analyze` run by Replay Detection (and later Event Detection). Technical approach: drive PySceneDetect's per-frame detector API (`ContentDetector.process_frame()`), fed one frame at a time from the Frame Extraction Service's `FULL` sampling mode, rather than PySceneDetect's own `SceneManager.detect_scenes()` convenience method (which would open the video file itself). This keeps the entire pipeline on the "always read frames through the Frame Extraction Service" rule with no exception needed. A lightweight secondary heuristic, layered on top of PySceneDetect's raw content-change cut points, classifies each cut as an ordinary hard cut or a replay-style editorial transition (a longer, gradual multi-frame content ramp reads as `REPLAY_TRANSITION`; an instantaneous single-frame jump reads as `ORDINARY_CUT`), producing the mandatory confidence score from how strongly that pattern matched.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: `scenedetect==0.6.1` (PySceneDetect) — already a project dependency per `requirements.txt` and `specs/technical_plan.md`'s named technology for this module; used via its per-frame `SceneDetector.process_frame()` API, not its file-opening `SceneManager.detect_scenes()` convenience path. Reuses the Frame Extraction Service (`cvip.video.frame_extraction`) for all frame access, and `cvip.common.diagnostics` for the standardized diagnostics record. No new dependency introduced.

**Storage**: N/A — this feature has no persistent storage of its own (per spec.md's Assumptions: the Scene Detection Result is an in-memory, per-run artifact; `specs/technical_plan.md`'s Database Schema has no `scene_boundaries` table).

**Testing**: pytest, per project convention and constitution Principle VII — contract tests for the module boundary, unit tests for classification-heuristic and edge-case logic, integration tests against real fixture videos (reusing `tests/fixtures/video_loader/`'s existing fixtures via Video Loader + Frame Extraction Service, no new fixtures), and a benchmark test for the memory/time-budget success criteria.

**Target Platform**: Windows 11 desktop, CPU-only x86_64 (Intel Core i3-1115G4 class hardware) — same as the rest of the platform.

**Project Type**: Single project — a Python module inside `src/cvip/video/`, alongside Video Loader and the Frame Extraction Service (it directly consumes the Frame Extraction Service's `FrameContext`/`extract_frames()` types, so keeping it in the same subpackage avoids a new cross-package dependency that isn't already implied).

**Performance Goals**: Completes within its ~10-20 minute share of the platform's overall analysis budget (SC-003, `specs/technical_plan.md` Performance Targets); peak memory does not scale with video duration (SC-004) — a single forward pass over the Frame Extraction Service's `FULL` stream, holding only a small fixed-size window of recent frames for the transition heuristic, not the whole video.

**Constraints**: Fully offline (no network calls); CPU-only (no GPU dependency); exactly one forward traversal of the video, no backward seeking, no re-decoding (FR-004); deterministic output across repeated runs (FR-020, SC-008).

**Scale/Scope**: One `LoadResult` (one video) per detection run; match recordings up to at least 4 hours (inherited from Video Loader's own scope); two canonical boundary classifications; single-process, synchronous — no threading/async infrastructure exists elsewhere in this codebase, so none is introduced here either.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate | Status |
|---|---|---|
| I. Offline-First, Always | No network/cloud calls anywhere in the detection path | PASS — PySceneDetect's detector classes operate on locally-supplied frame data only; no network access anywhere in the path (FR-016) |
| II. Performance is Non-Negotiable | Fits within the 40 min / 6GB / CPU-only budget | PASS — single forward pass (FR-004), memory bounded regardless of duration (SC-004). **Noted, not a violation**: this is an independent extraction pass over the Frame Extraction Service, distinct from Scoreboard OCR's and Replay Detection's own passes — `specs/technical_plan.md`'s per-module budget table already prices Scene Detection's full-frame pass (~10-20 min) as a separate line item from the Frame Extraction Service's own 1 FPS pass, so this doesn't invalidate that budget; it's what the budget already assumed (same reasoning already established in `specs/002-frame-extraction-service/plan.md`). |
| III. Single-Pass Analysis Principle | Each match analyzed only once, no reprocessing of an already-analyzed match | PASS — this feature doesn't decide whether to re-run `cvip analyze`; that's the Pipeline Orchestrator's job (enforced via the `matches` table). One detection run per match per analysis attempt. |
| IV. Detection Accuracy Requirements | Confidence scores on detected events | PASS (partial applicability) — every boundary carries a mandatory confidence score (FR-008, SC-009); this feature detects no cricket *events* itself, so the ≥95% event-accuracy target doesn't apply directly, and per spec.md's Assumptions, the ≥90% replay-removal target is Replay Detection's responsibility to meet using this feature's output combined with its other signals, not a bar this feature must hit alone. |
| V. Modular & Extensible Architecture | Independently testable, clear I/O contract | PASS — accepts a `LoadResult`, produces a `SceneDetectionResult`; no other module's internals are touched. The explicit Out of Scope section keeps this module from expanding into Replay Detection's responsibility. |
| VI. Fail Fast, Never Silently | Crash loudly, no silent fallback, detailed logging | PASS — FR-018 defines specific-reason fail-fast for mid-run failures; FR-015 requires a diagnostics record on every run including cancelled ones (FR-019) |
| VII. Test-First Development | Contract tests at module boundary; 100% coverage on critical paths | PASS — contract tests planned ahead of implementation; coverage gate planned in tasks.md Polish phase, matching Video Loader's and Frame Extraction Service's precedent |

No violations identified. Complexity Tracking table not required.

**Post-Phase 1 re-check**: Design artifacts (data-model.md, contracts/, quickstart.md) introduce no new dependencies, storage, or network surface beyond what's captured above. Driving PySceneDetect's per-frame detector API (research.md Decision 1) keeps this feature fully compliant with FR-003's "always use the Frame Extraction Service" rule — no documented exception was needed after all. All gates above still PASS after design; no re-justification needed.

## Project Structure

### Documentation (this feature)

```text
specs/003-scene-detection/
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
├── __init__.py                             # existing (Video Loader)
├── loader.py, metadata.py, hashing.py, models.py, errors.py            # existing (Video Loader) — unchanged
├── frame_extraction.py, frame_extraction_models.py, frame_extraction_errors.py   # existing (Frame Extraction Service) — unchanged
├── scene_detection_models.py               # NEW: SceneBoundary, SceneDetectionRequest, SceneDetectionResult, BoundaryType
├── scene_detection_errors.py                # NEW: SceneDetectionFailureReason enum (distinct taxonomy from the other two modules' errors)
└── scene_detection.py                       # NEW: detect_scenes() entry point + the PySceneDetect-driving detection loop

tests/
├── contract/
│   └── test_scene_detection_contract.py     # asserts scene_detection.py matches contracts/scene_detection_contract.md
├── integration/
│   └── test_scene_detection_e2e.py          # reuses tests/fixtures/video_loader/ fixtures via load_video() + extract_frames()
├── unit/
│   └── test_scene_detection_validation.py   # classification-heuristic logic, edge cases, cancellation, determinism
└── benchmark/
    └── test_scene_detection_performance.py  # SC-003 (time budget) and SC-004 (memory) against the multi-hour fixture
```

**Structure Decision**: Single project (Option 1), extending the existing `src/cvip/video/` subpackage established by Video Loader and the Frame Extraction Service — this feature's inputs (`LoadResult`, `FrameContext`/`extract_frames()`) already live there, so every consumer already depends on `cvip.video` regardless. New files are distinctly named (`scene_detection_*`) to avoid colliding with the other two modules' existing `models.py`/`errors.py` files, which describe different data/failure taxonomies. No new test fixtures are created; this feature's tests reuse Video Loader's existing fixtures (`tests/fixtures/video_loader/`) by calling `load_video()` then `extract_frames()` to obtain this feature's required inputs.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

None — the Constitution Check above found no violations, so no complexity needs justifying.
