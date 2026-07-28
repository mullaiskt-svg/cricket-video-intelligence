# Implementation Plan: Scoreboard OCR

**Branch**: `005-scoreboard-ocr` | **Date**: 2026-07-28 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/005-scoreboard-ocr/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

Extracts a raw, per-second scoreboard timeline (runs, wickets, over/ball, players, run rate) from a validated match video, via Tesseract OCR (`pytesseract`) against a configured scoreboard ROI, after a grayscale → upscale → threshold preprocessing pipeline. Never hard-fails on a single bad reading — instead records it with a low `ocr_confidence`, or a rule-violation-specific `parse_confidence = 0`, always producing exactly one `ScoreboardSample` per sampled frame plus an internal `OCREvidence` record capturing the full per-stage detail. The platform's own Performance Targets flag this as the single most expensive module (~15-25 min of the ~40 min budget from ~12,600 Tesseract calls); this plan resolves that via a perceptual-difference-based skip that reuses the previous reading whenever the scoreboard ROI is pixel-unchanged, rather than parallelizing across the target hardware's only 2 physical cores (research.md Decision 1).

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: `pytesseract` (already pinned in `requirements.txt`, not yet installed in this dev environment — see research.md Decision 5) wrapping the native Tesseract OCR binary (already a documented prerequisite, `docs/DEPENDENCIES.md`); OpenCV (`opencv-python`) for preprocessing (grayscale/upscale/threshold) and the ROI-unchanged skip check — no new dependency beyond what Video Loader/Scene Detection/Replay Detection already use. Reuses the Frame Extraction Service (`cvip.video.frame_extraction`) for all frame access via its shared `FrameContext` (spec.md FR-003), and `cvip.common.diagnostics` for the standardized diagnostics record.

**Storage**: N/A for this feature directly — it returns an in-memory result (spec.md FR-022), consistent with every other detection module on this platform. The existing `scoreboard_readings` table shape in `specs/technical_plan.md` already matches this feature's fields (`runs`, `wickets`, `over_number`, `ball_in_over`, `batter`, `non_striker`, `bowler`, `run_rate`, `raw_text`, `ocr_confidence`, `parse_confidence`) and needs no schema change, unlike Replay Detection's `replays` table.

**Testing**: pytest, per project convention and constitution Principle VII — contract test for the module boundary, unit tests for the preprocessing pipeline, the parser, the rule-validation logic (including the innings-transition heuristic and the ROI-unchanged skip), integration tests against real fixture videos (reusing `tests/fixtures/video_loader/`), and a benchmark test for the time-budget success criterion.

**Target Platform**: Windows 11 desktop, CPU-only x86_64 — specifically the constitution's named target, an **Intel Core i3-1115G4, a 2-core/4-thread part**. This is directly relevant to this feature's own performance design (research.md Decision 1): there is little headroom to parallelize ~12,600 Tesseract calls across cores when only 2 physical cores exist, so the mitigation strategy leans on doing *less total OCR work*, not spreading the same amount of work across more cores.

**Project Type**: Single project — a Python module inside `src/cvip/video/`, alongside Video Loader, the Frame Extraction Service, Scene Detection, and Replay Detection (it consumes the Frame Extraction Service's `FrameContext` directly, so keeping it in the same subpackage avoids a new cross-package dependency that isn't already implied).

**Performance Goals**: Completes within its ~15-25 minute share of the platform's overall ~40-minute analysis budget (SC-004, `specs/technical_plan.md` Performance Targets) — achieved primarily by skipping the Tesseract call entirely (and reusing the previous sample's fields/confidences) whenever the sampled frame's scoreboard ROI is pixel-unchanged from the previous sampled frame's ROI (research.md Decision 1), since the scoreboard graphic is static for most of the time between scoring events.

**Constraints**: Fully offline (no network calls); CPU-only (no GPU dependency); exactly one forward pass over the video (FR-024); deterministic output across repeated runs (FR-020, including the ROI-unchanged skip check); 4-value failure taxonomy (FR-018) with a diagnostics record emitted on every exit path, including a configuration-validation failure; never hard-fails on a single bad or unreadable frame (FR-006, a deliberate departure from this platform's usual "fail fast" default for a module's *primary* per-unit-of-work outcome — structural failures still fail fast per FR-018).

**Scale/Scope**: One `LoadResult` per extraction run; match recordings up to at least 4 hours (inherited scope); ~12,600 candidate sample points at 1 FPS, most of which are expected to skip the actual Tesseract call via the ROI-unchanged optimization; single-process, synchronous.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate | Status |
|---|---|---|
| I. Offline-First, Always | No network/cloud calls anywhere in the extraction path | PASS — Tesseract runs entirely locally against locally-supplied frame data (FR-025) |
| II. Performance is Non-Negotiable | Fits within the 40 min / 6GB / CPU-only budget, CPU-only, no GPU | PASS (with a documented design choice) — the ROI-unchanged skip (research.md Decision 1) is specifically what keeps this module, the platform's single largest cost, within its ~15-25 minute share on the constitution's named 2-core target hardware; FR-026 confirms CPU-only |
| III. Single-Pass Analysis Principle | Each match analyzed only once, no reprocessing of an already-analyzed match | PASS — this feature doesn't decide whether to re-run `cvip analyze`; that's the Pipeline Orchestrator's job |
| IV. Detection Accuracy Requirements | Confidence scores on detected events; contributes to the platform's ≥95% detection accuracy target | PASS (with a documented dependency) — every sample carries both mandatory confidence fields (FR-009); SC-011's accuracy target depends on the platform's golden dataset, which does not yet exist (`specs/technical_plan.md`'s "Golden Dataset & Accuracy Verification" section) — this feature's own test suite validates the mechanics (extraction, parsing, validation, graceful degradation), not the real-world OCR accuracy number itself, consistent with how Replay Detection's own SC-009 was scoped |
| V. Modular & Extensible Architecture | Independently testable, clear I/O contract | PASS — accepts a `LoadResult` + request configuration, produces a `ScoreboardOcrResult`; Out of Scope section keeps this module from expanding into Event Detection's or the future Smoother's responsibilities; the OCR/parsing/validation stage separation (FR-030) keeps the implementation itself modular internally too |
| VI. Fail Fast, Never Silently | Crash loudly on structural failure, no silent fallback for those, detailed logging | PASS — FR-018's four-value failure taxonomy covers every structural mid-run and pre-run failure mode with a specific reason; FR-021 requires a diagnostics record on every exit path, including a rejected configuration. Per-reading OCR/parse quality issues are a deliberate, spec-documented exception to "fail fast" for this module's primary output (FR-006), not a violation of it — they're never silent either, since every quality issue is recorded via `ocr_confidence`/`parse_confidence`/`Validation Failure Reason`, not swallowed |
| VII. Test-First Development | Contract tests at module boundary; 100% coverage on critical paths | PASS — contract tests planned ahead of implementation; coverage gate planned in tasks.md Polish phase, matching the established precedent from all four prior features |

No violations identified. Complexity Tracking table not required.

**Post-Phase 1 re-check**: Design artifacts (data-model.md, contracts/, quickstart.md) introduce no new dependencies beyond `pytesseract` (already declared in `requirements.txt` prior to this feature) and no network/GPU surface. The ROI-unchanged skip mechanism (research.md Decision 1) is a pure in-memory optimization with no new storage or external dependency. All gates above still PASS after design; no re-justification needed.

## Project Structure

### Documentation (this feature)

```text
specs/005-scoreboard-ocr/
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
├── replay_detection.py, replay_detection_models.py, replay_detection_errors.py  # existing (Replay Detection) — unchanged
├── scoreboard_ocr_models.py   # NEW: ScoreboardSample, OCREvidence, ScoreboardOcrRequest, ScoreboardOcrResult
├── scoreboard_ocr_errors.py   # NEW: ScoreboardOcrFailureReason + ValidationFailureReason enums (distinct taxonomy from the other four modules' errors)
└── scoreboard_ocr.py          # NEW: ScoreboardOcrExtractor class + extract_scoreboard() entry point, the preprocessing/OCR/parsing/validation pipeline, and the ROI-unchanged skip + last-accepted-reading tracker

tests/
├── contract/
│   └── test_scoreboard_ocr_contract.py    # asserts scoreboard_ocr.py matches contracts/scoreboard_ocr_contract.md
├── integration/
│   └── test_scoreboard_ocr_e2e.py         # reuses tests/fixtures/video_loader/ fixtures via load_video() + extract_frames()
├── unit/
│   └── test_scoreboard_ocr_validation.py  # preprocessing, parsing, rule-validation logic, ROI-unchanged skip, edge cases
└── benchmark/
    └── test_scoreboard_ocr_performance.py # SC-004 (time budget) against the multi-hour fixture
```

**Structure Decision**: Single project (Option 1), extending the existing `src/cvip/video/` subpackage established by the four prior features — this feature's inputs (`LoadResult`, `extract_frames()`/`FrameContext`) already live there. New files use a `scoreboard_ocr_*` naming prefix, following the exact precedent set by the three prior additions to this subpackage. No new test fixtures are created; this feature's tests reuse Video Loader's existing fixtures via `load_video()` → this feature's own request construction (this feature does not depend on Scene Detection's or Replay Detection's output, unlike how Replay Detection depended on Scene Detection).

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

None — the Constitution Check above found no violations, so no complexity needs justifying.
