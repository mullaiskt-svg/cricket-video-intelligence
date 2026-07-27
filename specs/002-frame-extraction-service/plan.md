# Implementation Plan: Frame Extraction Service

**Branch**: `002-frame-extraction-service` | **Date**: 2026-07-27 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/002-frame-extraction-service/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

A shared, single abstraction for reading frames from an already-validated match video (a successful `LoadResult` from Video Loader), replacing every downstream module's own direct OpenCV access. Exposes a streaming, memory-bounded, deterministic frame iterator supporting four sampling modes (full, fixed-rate, frame-index list, timestamp list), each yielded frame carrying a stable `FrameContext` payload. Adds progress reporting, cooperative cancellation, and resume-from-a-point support, and emits one standardized diagnostics record per run. Technical approach: a class-based iterable (`FrameExtractor`, returned by an `extract_frames()` factory function and usable as a context manager) built on OpenCV's `VideoCapture`, using frame-index seeking rather than full sequential decode-and-filter to keep fixed-rate/list-based sampling fast, while still reading each yielded frame's *actual* timestamp from the decoder rather than computing it from an assumed constant frame rate (which is what makes Variable Frame Rate sources work correctly without special-casing).

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: OpenCV (`opencv-python`) for frame seeking/decoding — already a hard project dependency (used by Video Loader and, per `specs/technical_plan.md`, by Scene Detection). No new dependency introduced; reuses `cvip.common.diagnostics` (built by the Video Loader feature) for the standardized diagnostics record.

**Storage**: N/A — this feature has no persistent storage of its own. It produces an in-memory stream of `FrameContext` objects consumed by the caller; nothing here writes to the event database.

**Testing**: pytest, per project convention and constitution Principle VII — contract tests for the module boundary, unit tests for sampling-mode/edge-case logic, integration tests against real fixture videos (reusing `tests/fixtures/video_loader/`'s existing fixtures rather than duplicating them), and a benchmark test for the memory/throughput success criteria.

**Target Platform**: Windows 11 desktop, CPU-only x86_64 (Intel Core i3-1115G4 class hardware) — same as the rest of the platform.

**Project Type**: Single project — a Python module inside `src/cvip/video/`, alongside Video Loader (it directly consumes Video Loader's `LoadResult`/`MatchVideoSource` types, so keeping it in the same subpackage avoids a new cross-package dependency that isn't already implied).

**Performance Goals**: Peak memory stays constant regardless of video duration (SC-002); fixed-rate/list-based sampling must not degrade into a full sequential decode of every native frame (see the seeking-based Decision in research.md) — this is what keeps the `specs/technical_plan.md` per-module budget's "~3-5 min" estimate for 1 FPS-style extraction credible.

**Constraints**: Fully offline (no network calls); CPU-only (no GPU dependency); must not require holding the whole video, or a large fraction of it, in memory (constitution Principle II, <6GB overall budget); optimized for forward sequential traversal, not arbitrary fast random seeking (spec Assumptions).

**Scale/Scope**: One `LoadResult` (one video) per `FrameExtractor` instance; match recordings up to at least 4 hours (inherited from Video Loader's own scope); four sampling modes; single-process, synchronous — no threading/async infrastructure exists elsewhere in this codebase, so none is introduced here either.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate | Status |
|---|---|---|
| I. Offline-First, Always | No network/cloud calls anywhere in the extraction path | PASS — OpenCV operates on the local file only (FR-011) |
| II. Performance is Non-Negotiable | Fits within the 40 min / 6GB / CPU-only budget | PASS — memory bounded regardless of duration (SC-002); seek-based sampling avoids a full decode for fixed-rate/list modes, protecting the per-module time budget in `specs/technical_plan.md`. **Noted, not a violation**: each independent caller (Scene Detection, Replay Detection, Scoreboard OCR) performing its own extraction request means the file may be physically read more than once per `cvip analyze` run — a deliberate v1 tradeoff (see research.md), watched against the 40-minute budget, not a constitution violation (Principle III concerns *re-running a completed analysis*, not *how many internal passes one analysis run takes* — see Principle III row below). |
| III. Single-Pass Analysis Principle | Each match analyzed only once, no reprocessing of an already-analyzed match | PASS — this feature doesn't decide whether to re-run `cvip analyze`; that's the Pipeline Orchestrator's job (enforced via the `matches` table, per `specs/technical_plan.md`). Multiple extraction requests *within* one `cvip analyze` run are a performance consideration (Principle II), not repeat analysis of an already-completed match. |
| IV. Detection Accuracy Requirements | Confidence scores on detected events | N/A — this module detects no cricket events; it only reads frames |
| V. Modular & Extensible Architecture | Independently testable, clear I/O contract | PASS — this feature exists specifically to satisfy this principle for frame access: one contract (`FrameContext`), consumed by every downstream module instead of each wrapping OpenCV independently |
| VI. Fail Fast, Never Silently | Crash loudly, no silent fallback, detailed logging | PASS — FR-009/FR-014 define specific-reason rejection for out-of-range resume points and mid-run failures; FR-010 requires a diagnostics record on every run including cancelled ones |
| VII. Test-First Development | Contract tests at module boundary; 100% coverage on critical paths | PASS — contract tests planned ahead of implementation; coverage gate planned in tasks.md Polish phase, matching Video Loader's precedent |

No violations identified. Complexity Tracking table not required.

**Post-Phase 1 re-check**: Design artifacts (data-model.md, contracts/, quickstart.md) introduce no new dependencies, storage, or network surface beyond what's captured above. The seek-based sampling decision (research.md) and the "independent pass per caller, no shared decode in v1" decision are both explicitly priced into the existing `specs/technical_plan.md` performance budget rather than invalidating it. All gates above still PASS after design; no re-justification needed.

## Project Structure

### Documentation (this feature)

```text
specs/002-frame-extraction-service/
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
├── __init__.py                       # existing (Video Loader)
├── loader.py                         # existing (Video Loader) — unchanged
├── metadata.py, hashing.py, models.py, errors.py   # existing (Video Loader) — unchanged
├── frame_extraction_models.py        # NEW: FrameContext, ExtractionRequest, ExtractionProgress, SamplingMode
├── frame_extraction_errors.py        # NEW: ExtractionFailureReason enum (distinct from Video Loader's own errors.py taxonomy)
└── frame_extraction.py               # NEW: FrameExtractor class + extract_frames() entry point

tests/
├── contract/
│   └── test_frame_extraction_contract.py   # asserts frame_extraction.py matches contracts/frame_extraction_contract.md
├── integration/
│   └── test_frame_extraction_e2e.py        # reuses tests/fixtures/video_loader/ fixtures via load_video()
├── unit/
│   └── test_frame_extraction_validation.py # sampling-mode logic, edge cases, resume precedence, cancellation
└── benchmark/
    └── test_frame_extraction_performance.py # SC-002 (memory) and SC-008 (throughput consistency) against the multi-hour fixture
```

**Structure Decision**: Single project (Option 1), extending the existing `src/cvip/video/` subpackage established by Video Loader rather than creating a new one — this feature's sole input type (`LoadResult`) already lives there, so every consumer already depends on `cvip.video` regardless. New files are distinctly named (`frame_extraction_*`) to avoid colliding with Video Loader's existing `models.py`/`errors.py`, which describe a different module's data/failure taxonomy. No new test fixtures are created; this feature's tests reuse Video Loader's existing fixtures (`tests/fixtures/video_loader/`) by calling `load_video()` to obtain the `LoadResult` this feature requires as input.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

None — the Constitution Check above found no violations, so no complexity needs justifying.
