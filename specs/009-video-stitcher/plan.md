# Implementation Plan: Video Stitcher

**Branch**: `009-video-stitcher` | **Date**: 2026-07-29 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/009-video-stitcher/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

Turns Module 8's `ClipPlan` into the platform's first genuinely watchable artifact: a single MP4 highlight video. Implemented as a six-stage pipeline (ClipPlan Input → Validation → FFmpeg Segment Extraction → Concatenation → Output Validation → Stitch Result), shelling out directly to the `ffmpeg` CLI via `subprocess` (matching Video Loader's own `ffprobe` precedent, not the dormant `ffmpeg-python` dependency) with a stream-copy strategy throughout. Each clip is extracted to a temporary segment file, all segments are concatenated via FFmpeg's concat demuxer, and the result is independently verified (exists, non-empty, container opens) before success is ever reported — closing the gap where an FFmpeg exit code of 0 doesn't actually guarantee a valid file. An internal `StitchEvidence` record — FFmpeg invocation details, segment paths, concatenation order, cleanup actions, stream-copy parameters — preserves full derivation traceability, mirroring Event Detection's `EventEvidence` and Clip Generator's `ClipEvidence` precedent.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: FFmpeg (native binary, invoked via `subprocess` — CLAUDE.md tech stack, `docs/DEPENDENCIES.md`), matching Video Loader's own `ffprobe`-via-`subprocess` precedent (`src/cvip/video/metadata.py`) rather than the `ffmpeg-python` package already listed in `requirements.txt` but never actually used anywhere in the codebase (research.md Decision 2). No OpenCV, no `pytesseract`, no `numpy` — this module's only external-process dependency is `ffmpeg`/`ffprobe` themselves.

**Storage**: N/A for the module's own state — it produces an in-memory `Stitch Result` (matching every prior module's return-a-result precedent) and, as its one genuine side effect, writes the final MP4 file to the caller-specified output path (spec.md's own note that this is the platform's first module with a real side effect). Diagnostics records are written to structured logs, not a database (spec.md FR-019).

**Testing**: pytest — contract test for the module boundary (entry point shape, error taxonomy); unit tests for each Processing Model stage in isolation (Validation's four precondition checks, Output Validation's three checks); an integration test built against small real video fixtures (this module, unlike Modules 5/8, genuinely needs real playable video content to stitch and probe — synthetic in-memory objects alone can't exercise FFmpeg) reusing/extending `tests/fixtures/video_loader/`'s existing fixture-generation approach; a benchmark test for SC-005 (a few dozen clips, well under the 2-minute `generate` budget).

**Target Platform**: Windows 11 desktop, CPU-only — FFmpeg's stream-copy mode is trivially CPU-light (no decode/encode), so the constitution's CPU-only/no-GPU gate is satisfied by the chosen strategy itself, not just by architecture as in Modules 5/8.

**Project Type**: Single project. Per CLAUDE.md's Package Layout section, Video Stitcher is explicitly **not** part of the frame-analysis chain (Modules 1, 1a, 2, 3, 4, 4a) that shares `src/cvip/video/` — it gets its own new subpackage, `src/cvip/stitcher/` (research.md Decision 1; unlike `events/`/`clips/`, this name was not pre-reserved as scaffolding, since the original `src/cvip/` layout in `specs/001-video-loader/plan.md` predates this module's design).

**Performance Goals**: Well within the platform's under-2-minute `generate` budget (spec.md SC-005) — stream-copy avoids re-encoding cost entirely, so wall-clock time is dominated by disk I/O (reading/writing segment files) and process-spawn overhead for a few dozen `ffmpeg` invocations, not codec work.

**Constraints**: Fully offline and CPU-only (FFmpeg invoked with no network-capable flags); a five-value failure taxonomy with a diagnostics record emitted on every exit path (spec.md FR-016, Key Entities); no database writes of any kind (FR-019); temporary artifacts never accumulate on the filesystem, success or failure (FR-015); success is never reported without independent Output Validation (FR-011).

**Scale/Scope**: One `Stitch Request` (a `ClipPlan` + output path) per `generate` invocation; on the order of a few dozen clips per plan; single-process, synchronous, one `ffmpeg` subprocess per segment extraction plus one for the final concatenation plus one lightweight `ffprobe` for Output Validation.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate | Status |
|---|---|---|
| I. Offline-First, Always | No network/cloud calls anywhere | PASS — FFmpeg/ffprobe operate on local files only, invoked with no network-capable flags, matching Video Loader's own `ffprobe` precedent |
| II. Performance is Non-Negotiable | Fits within the overall 40 min / 6GB / CPU-only budget (or, for `generate`, the <2 min highlight-gen budget) | PASS — stream-copy is CPU-light by construction (no decode/encode); SC-005's expectation is a negligible-to-modest fraction of the 2-minute `generate` budget, dominated by I/O and process-spawn overhead for a few dozen clips |
| III. Single-Pass Analysis Principle | Each match analyzed only once, no reprocessing | PASS — this is a Phase 2 (`generate`) module by design; it never re-runs analysis (Modules 1-7) or re-invokes Clip Generator (spec.md FR-013), only stitching from an already-computed `ClipPlan` |
| IV. Detection Accuracy Requirements | Confidence scores on detected events; contributes to ≥95% detection accuracy | N/A — this module detects nothing; it assembles already-detected, already-planned clips into a video file. It does not read or depend on `confidence` at all |
| V. Modular & Extensible Architecture | Independently testable, clear I/O contract | PASS — accepts a `Stitch Request` (`ClipPlan` + output path), produces a self-contained `Stitch Result`; the Processing Model's six-stage separation (spec.md) is explicitly structured so Output Validation's checks or the extraction strategy can each change within one stage without touching the others |
| VI. Fail Fast, Never Silently | Crash loudly on structural failure, no silent fallback, detailed logging | PASS — spec.md's five-value failure taxonomy covers every precondition and mid-run failure with a specific reason; FR-016 requires a diagnostics record on every exit path; FR-011's Output Validation stage specifically exists to prevent this module from ever silently reporting success for an unverified result — the single strongest instance of this principle of any module built so far |
| VII. Test-First Development | Contract tests at module boundary; 100% coverage on critical paths | PASS — contract tests planned ahead of implementation; coverage gate planned in tasks.md Polish phase, matching the established precedent from all prior features |

No violations identified. Complexity Tracking table not required.

**Post-Phase 1 re-check**: Design artifacts (data-model.md, contracts/, quickstart.md) introduce one new *runtime* dependency surface beyond prior modules — direct `ffmpeg`/`ffprobe` subprocess invocation for the actual stitch work (not just the `ffprobe` metadata read Video Loader already established) — but no new Python package dependency, no database, and no network surface. All gates above still PASS after design; no re-justification needed.

## Project Structure

### Documentation (this feature)

```text
specs/009-video-stitcher/
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
├── clips/
│   └── models.py         # existing — ClipPlan/PlannedClip, this module's input shape
└── stitcher/               # NEW subpackage — Video Stitcher is not part of the video/
    │                        # frame-analysis chain (CLAUDE.md Package Layout). Unlike
    │                        # events/ and clips/, this directory was NOT pre-reserved as
    │                        # scaffolding by specs/001-video-loader/plan.md (research.md
    │                        # Decision 1) -- created fresh by this feature.
    ├── __init__.py         # NEW (empty)
    ├── models.py           # NEW: StitchRequest, StitchResult, StitchEvidence, and their
    │                        #      nested value objects (FfmpegInvocation, CleanupAction,
    │                        #      StreamCopyParameters) -- data models only
    ├── errors.py           # NEW: VideoStitchingFailureReason + VideoStitchingError --
    │                        #      the failure taxonomy lives here, not in models.py
    ├── ffmpeg.py           # NEW: thin subprocess wrappers -- run_extract_segment(),
    │                        #      run_concat(), probe_output() (research.md Decision 2)
    └── stitcher.py          # NEW: VideoStitcherRunner class + stitch_video() entry point;
                              # the six-stage Processing Model (ClipPlan Input -> Validation
                              # -> FFmpeg Segment Extraction -> Concatenation -> Output
                              # Validation -> Stitch Result)

tests/
├── contract/
│   └── test_video_stitcher_contract.py     # asserts stitcher/stitcher.py matches contracts/video_stitcher_contract.md
├── integration/
│   └── test_video_stitcher_e2e.py          # real small video fixtures -- stitches, then
│                                             # ffprobes the output to verify duration/streams
├── unit/
│   └── test_video_stitcher_rules.py        # per-stage: validation checks, output validation
│                                             # checks, StitchEvidence/StitchResult assembly,
│                                             # temp-artifact cleanup accounting
├── benchmark/
│   └── test_video_stitcher_performance.py  # SC-005 against a few dozen clips
└── fixtures/
    └── video_stitcher/                      # NEW -- small real video fixtures (a few
        └── generate_fixtures.py             # seconds each) generated via ffmpeg, reusing
                                              # tests/fixtures/video_loader/'s own approach
                                              # (not committed as binary files -- see tasks.md)
```

**Structure Decision**: Single project (Option 1). Like Event Detection and Clip Generator — and unlike Modules 1, 1a, 2, 3, 4, and 4a, which share `src/cvip/video/` — Video Stitcher gets its own subpackage, `src/cvip/stitcher/`, per CLAUDE.md's Package Layout section's explicit list of Video Stitcher as a module requiring its own subpackage. Unlike `events/`/`clips/`, `stitcher/` was **not** pre-reserved as empty scaffolding in `specs/001-video-loader/plan.md`'s original layout (`{config,video,ocr,replay,events,db,clips,templates,common}`) — this feature creates it fresh, choosing the same short-name convention (`stitcher/`, not `video_stitcher/`) those two directories already established, for the same reason: this subpackage hosts one primary module and doesn't need a longer disambiguating prefix. A new `ffmpeg.py` module (not present in Event Detection's or Clip Generator's own layouts, since neither touches an external process) isolates every `subprocess` call behind a small set of typed functions, keeping `stitcher.py`'s Processing Model logic free of raw subprocess/argument-list handling. This feature also introduces the platform's first non-`video_loader` fixture directory containing real (if tiny) video files, since — unlike every module since Module 4a — it has no way to be meaningfully tested against purely synthetic in-memory objects.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

None — the Constitution Check above found no violations, so no complexity needs justifying.
