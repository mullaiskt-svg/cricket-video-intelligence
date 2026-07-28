# Implementation Plan: OCR Timeline Smoother

**Branch**: `006-ocr-timeline-smoother` | **Date**: 2026-07-28 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/006-ocr-timeline-smoother/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

Cleans Scoreboard OCR's raw, per-second timeline before Event Detection diffs it: every sample Scoreboard OCR already flagged unusable (`ocr_confidence = 0` or `parse_confidence = 0`) is replaced by holding forward the most recently established known-good reading, and every individually rule-consistent sample that is nonetheless an isolated single-sample outlier relative to its surrounding neighbors is discounted the same way. This is the first pipeline module with no video/frame/`LoadResult` dependency at all — its only input is Scoreboard OCR's own `ScoreboardOcrResult`, making it a pure in-memory, two-pass data transformation (an outlier-flagging pass with lookahead, then a sequential hold-forward pass) rather than a computer-vision stage. Outlier detection compares each usable sample's core scoring tuple (`runs`, `wickets`, `over_number`, `ball_in_over`) against its nearest usable neighbors on each side within a configurable window (default 2), never against `batter`/`non_striker`/`bowler`/`run_rate`, which are excluded from the consensus check (research.md Decision 2).

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: None beyond the standard library and this platform's own prior modules — reuses `cvip.video.scoreboard_ocr_models` (`ScoreboardOcrResult`/`ScoreboardSample`) as its sole input type and `cvip.common.diagnostics` (`DiagnosticsTracker`/`ExecutionDiagnostics`/`emit_diagnostics`) for the standardized diagnostics record. No OpenCV, no `pytesseract`, no FFmpeg, no `numpy` — the first module in the pipeline with zero new external dependencies, a direct consequence of never touching a video frame (spec.md Assumptions).

**Storage**: N/A — returns an in-memory `OCRTimelineSmootherResult`, consistent with every prior module (FR-011); the Pipeline Orchestrator remains solely responsible for persistence.

**Testing**: pytest — contract test for the module boundary; unit tests for the outlier-flagging pass, the hold-forward fill pass, window-boundary cases (fewer than `outlier_window` usable neighbors available near either end of the sequence), leading-gap vs trailing-gap behavior, the "two-or-more-consecutive-divergent-samples is a genuine change, not noise" edge case, determinism, and both `INVALID_INPUT`/`INVALID_SMOOTHING_CONFIGURATION` rejections; an integration test built entirely from synthetic in-memory `ScoreboardOcrResult` fixtures (no `tests/fixtures/video_loader/` dependency — this module never touches a video file); a benchmark test for SC-008 (~12,600 synthetic samples, <1 minute).

**Target Platform**: Windows 11 desktop, CPU-only — trivially satisfied here: there is no OpenCV/Tesseract/video-decode surface at all, so the constitution's CPU-only/no-GPU/offline gates are structurally guaranteed by this feature's own architecture rather than requiring active design attention (unlike every prior module).

**Project Type**: Single project — per the user's confirmed package-layout decision (see CLAUDE.md's updated "Package Layout" section), this feature lives in `src/cvip/video/` alongside Modules 1–4, using the same `<module>.py`/`<module>_models.py`/`<module>_errors.py` naming convention, even though it has no frame-analysis dependency itself — it is still part of the same conceptual frame-analysis-to-Event-Detection chain (it consumes Scoreboard OCR's output directly) and keeping it there avoids a new one-off subpackage for a single small module.

**Performance Goals**: Completes in under 1 minute for a full match's ~12,600 samples (SC-008) — trivially achievable, since both passes of the algorithm are O(n) over an in-memory list of dataclasses with no I/O, no OCR, and no frame decode.

**Constraints**: Fully offline and CPU-only (both trivially true — no external calls of any kind); deterministic output for the same input and configuration (FR-016); strict 1:1 sample correspondence, same order, same timestamps, never fewer or reordered (FR-007); hold-forward only, never numeric interpolation (FR-005); 2-value failure taxonomy (`INVALID_INPUT`, `INVALID_SMOOTHING_CONFIGURATION`) with a diagnostics record emitted on every exit path including a rejected configuration (FR-014, FR-017); cooperative cancellation that still emits exactly one diagnostics record for the partial run (FR-015).

**Scale/Scope**: One `ScoreboardOcrResult` per smoothing run; up to ~12,600 samples for a full 3–4 hour match; single-process, synchronous, two sequential O(n) passes.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate | Status |
|---|---|---|
| I. Offline-First, Always | No network/cloud calls anywhere | PASS (trivially) — this feature makes no external calls of any kind, not even a local video decode; there is nothing to call out to |
| II. Performance is Non-Negotiable | Fits within the overall 40 min / 6GB / CPU-only budget | PASS (trivially) — SC-008's own <1 minute ceiling is a tiny fraction of the platform budget, achieved by a plain O(n) two-pass in-memory algorithm with no OCR/decode cost |
| III. Single-Pass Analysis Principle | Each match analyzed only once, no reprocessing | PASS — this feature doesn't decide whether `cvip analyze` re-runs; that remains the Pipeline Orchestrator's responsibility, same as every prior module |
| IV. Detection Accuracy Requirements | Confidence scores on detected events; contributes to ≥95% detection accuracy | PASS (with a documented dependency) — this feature deliberately drops per-sample confidence fields from its public output (spec.md Assumptions), since resolving trustworthiness is its entire job; SC-009's own accuracy claim depends on the platform's golden dataset and Event Detection, neither of which exist yet — this feature's own test suite validates the gap-filling/outlier mechanics, not a real-world accuracy number, consistent with how Scoreboard OCR's own SC-011 was scoped |
| V. Modular & Extensible Architecture | Independently testable, clear I/O contract | PASS — accepts an `OCRTimelineSmootherRequest` (a `ScoreboardOcrResult` + `outlier_window`), produces an `OCRTimelineSmootherResult`; Out of Scope section keeps this module from expanding into Event Detection's responsibilities |
| VI. Fail Fast, Never Silently | Crash loudly on structural failure, no silent fallback, detailed logging | PASS — FR-014's 2-value failure taxonomy covers every failure mode with a specific reason; FR-017 requires a diagnostics record on every exit path, including a rejected configuration; a gap/outlier is always explicitly recorded via `Smoothing Evidence`, never silently dropped |
| VII. Test-First Development | Contract tests at module boundary; 100% coverage on critical paths | PASS — contract tests planned ahead of implementation; coverage gate planned in tasks.md Polish phase, matching the established precedent from all four prior features |

No violations identified. Complexity Tracking table not required.

**Post-Phase 1 re-check**: Design artifacts (data-model.md, contracts/, quickstart.md) introduce no new dependency, no storage, and no network/GPU surface — the two-pass algorithm (research.md Decisions 1–3) and the reused `ExecutionDiagnostics` shape (research.md Decision 5) are both pure in-memory constructs. All gates above still PASS after design; no re-justification needed.

## Project Structure

### Documentation (this feature)

```text
specs/006-ocr-timeline-smoother/
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
├── scoreboard_ocr.py, scoreboard_ocr_models.py, scoreboard_ocr_errors.py        # existing (Scoreboard OCR) — unchanged; this feature's sole input type
├── ocr_timeline_smoother_models.py   # NEW: CleanedScoreboardSample, SmoothingEvidence, OCRTimelineSmootherRequest, OCRTimelineSmootherResult
├── ocr_timeline_smoother_errors.py   # NEW: OCRTimelineSmootherFailureReason (2 values) + OCRTimelineSmootherError
└── ocr_timeline_smoother.py          # NEW: OCRTimelineSmootherRunner class + smooth_timeline() entry point; the two-pass outlier-flagging + hold-forward-fill algorithm

tests/
├── contract/
│   └── test_ocr_timeline_smoother_contract.py    # asserts ocr_timeline_smoother.py matches contracts/ocr_timeline_smoother_contract.md
├── integration/
│   └── test_ocr_timeline_smoother_e2e.py         # synthetic in-memory ScoreboardOcrResult fixtures — no video/frame fixtures needed
├── unit/
│   └── test_ocr_timeline_smoother_algorithm.py   # gap-fill, outlier window boundary cases, leading/trailing gaps, genuine-change edge case, determinism, both failure reasons
└── benchmark/
    └── test_ocr_timeline_smoother_performance.py # SC-008 (<1 minute) against a synthetic ~12,600-sample sequence
```

**Structure Decision**: Single project (Option 1), placing this feature in the existing `src/cvip/video/` subpackage per the user's confirmed package-layout decision — even though this feature never touches a video frame, it directly consumes Scoreboard OCR's result type and sits in the same conceptual analysis chain, so it follows the same `ocr_timeline_smoother_*` naming precedent set by the four prior additions to this subpackage rather than getting a one-off new subpackage for a single module. No new test fixtures are created; this feature's tests build `ScoreboardOcrResult`/`ScoreboardSample` instances directly in Python, since it has no video dependency to fixture against.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

None — the Constitution Check above found no violations, so no complexity needs justifying.
