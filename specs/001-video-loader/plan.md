# Implementation Plan: Video Loader

**Branch**: `001-video-loader` | **Date**: 2026-07-27 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-video-loader/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

Load a cricket match video file (MP4/MKV), validate that it can actually be opened and decoded, and expose its duration, resolution, frame rate, and codec — failing immediately and specifically when the file is missing, corrupted, or unsupported — so that no downstream module (scene detection, replay detection, OCR, event detection) ever runs against bad or missing video state. Technical approach: use OpenCV's `VideoCapture`, already a project dependency for later pipeline stages, as the primary metadata/validation path, cross-checked with `ffprobe` for codec identification where OpenCV's own reporting is unreliable. This feature also introduces the project's first implementation of the Module Observability & Diagnostics standard (structured per-invocation logs with timing, peak memory, and input/output summaries), intended for reuse by every later pipeline module.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: OpenCV (`opencv-python`) for opening the video and reading container-level metadata; `ffmpeg-python` (wrapping `ffprobe`) as a secondary codec cross-check — both already required by the project (CLAUDE.md tech stack). `psutil` is newly introduced (see research.md) to measure peak memory usage cross-platform (including Windows, the target platform) for the Module Observability & Diagnostics standard (FR-013); it is open-source and requires no network/GPU access, so it doesn't conflict with the constitution's dependency constraints.

**Storage**: N/A — this feature has no persistent storage of its own; it produces an in-memory `LoadResult` consumed by the next pipeline stage. (The event database used by later modules is out of scope here.) Diagnostics records (FR-013) are written to structured logs, not a database.

**Testing**: pytest, per project convention (`requirements-dev.txt`) and constitution Principle VII (Test-First Development) — contract tests for the module's input/output boundary, unit tests for validation/error-path logic, and an enforced coverage gate (`pytest --cov=src/cvip/video --cov-fail-under=100`) run as part of task completion (see tasks.md Phase 6), since Principle VII requires 100% coverage on critical paths, not merely tests existing.

**Target Platform**: Windows 11 desktop, CPU-only x86_64 (Intel Core i3-1115G4 class hardware).

**Project Type**: Single project — a Python subpackage (`src/cvip/video/`) inside the larger CVIP desktop application's `src/cvip/` package, invoked by the pipeline orchestrator that runs the full analysis phase.

**Performance Goals**: Metadata available within 10 seconds for a 3-4 hour match video (SC-001); load/validation step must not scale with video duration (no full-file decode).

**Constraints**: Fully offline (no network calls); CPU-only (no GPU dependency); ≤200MB memory footprint for this module regardless of video length (SC-005); must run within the overall pipeline budget (≤40 min / <6GB for a full 3-hour match, per constitution Principle II).

**Scale/Scope**: One video file per invocation; MP4 and MKV containers only for v1; durations from short test clips up to at least 4 hours; 720p/1080p expected, other resolutions loaded and reported rather than rejected (per spec Assumptions).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate | Status |
|---|---|---|
| I. Offline-First, Always | No network/cloud calls anywhere in the load path | PASS — OpenCV/ffprobe operate on local files only (FR-009) |
| II. Performance is Non-Negotiable | Fits within the 40 min / 6GB / CPU-only budget | PASS — 10s / ≤200MB micro-budget defined (SC-001, SC-005), no GPU dependency |
| III. Single-Pass Analysis Principle | Video is not reprocessed by this module | PASS — load happens once per invocation; no re-reads or caching of full frame data |
| IV. Detection Accuracy Requirements | Confidence scores on detected events | N/A — this module detects no cricket events, only validates/reads metadata |
| V. Modular & Extensible Architecture | Independently testable, clear I/O contract | PASS — see `contracts/video_loader_contract.md`; downstream modules depend only on the `LoadResult` contract, not on OpenCV/ffprobe directly |
| VI. Fail Fast, Never Silently | Crash loudly, no silent fallback, detailed logging | PASS — FR-004/FR-005/FR-007, US2 define specific-reason rejection and logging for every attempt |
| VII. Test-First Development | Contract tests at module boundary; 100% coverage on critical paths | PASS — contract tests planned ahead of implementation (Principle VII); the "100% coverage" clause is enforced by an explicit gate task (tasks.md Phase 6: `pytest --cov=src/cvip/video --cov-fail-under=100`), not left implicit |

No violations identified. Complexity Tracking table not required.

**Post-Phase 1 re-check**: Design artifacts (data-model.md, contracts/, quickstart.md) introduce no new dependencies, storage, or network surface beyond what's captured above, with one addition surfaced during `/speckit-analyze`: `psutil` (peak memory measurement for FR-013 diagnostics — see Technical Context and research.md). All gates above still PASS after design; no re-justification needed.

**Deferred verification note**: FR-006 and SC-003 (no invalid video reaches downstream modules) are guaranteed by this feature's contract (`contracts/video_loader_contract.md` "Consumer obligation") but cannot be end-to-end tested until a consumer module exists. This is an intentional, tracked deferral — full verification happens when Scene Detection (the next feature) is implemented, not here.

## Project Structure

### Documentation (this feature)

```text
specs/001-video-loader/
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
├── __init__.py
├── common/
│   ├── __init__.py
│   └── diagnostics.py     # ExecutionDiagnostics dataclass + structured JSON log emitter;
│                          # shared by video now and by every future pipeline module
│                          # (see specs/technical_plan.md Module Observability & Diagnostics)
├── video/
│   ├── __init__.py
│   ├── loader.py         # load_video(path) -> LoadResult; wraps OpenCV VideoCapture
│   ├── metadata.py        # codec cross-check via ffprobe (ffmpeg-python)
│   ├── hashing.py          # compute_file_hash(path) -> str; sampled (prefix+suffix+size) digest, FR-014
│   ├── models.py          # MatchVideoSource, LoadResult dataclasses
│   └── errors.py           # VideoLoadError and specific subtypes (NotFound, Unsupported, Corrupted, Locked)
├── config/                # empty scaffolding — populated by a later feature (config loader)
├── ocr/                   # empty scaffolding — populated by the Scoreboard OCR feature
├── replay/                # empty scaffolding — populated by the Replay Detection feature
├── events/                # empty scaffolding — populated by the Event Detection feature
├── db/                    # empty scaffolding — populated by the Event Database feature
├── clips/                 # empty scaffolding — populated by the Clip Generator feature
└── templates/             # empty scaffolding — populated by the highlight-templates feature (V1.5, per specs/features.md)

tests/
├── contract/
│   └── test_video_loader_contract.py   # asserts video/loader.py matches contracts/video_loader_contract.md
├── integration/
│   └── test_video_loader_e2e.py        # loads sample fixtures, checks metadata + rejection paths
├── unit/
│   └── test_video_loader_validation.py # unit tests for error classification logic
├── benchmark/
│   └── test_video_loader_performance.py # SC-001/SC-005 timing + memory check against the multi-hour fixture
└── fixtures/
    └── video_loader/
        ├── generate_fixtures.py        # generates valid/corrupted/zero-byte/unsupported/multi-hour fixtures via ffmpeg
        └── (generated .mp4/.mkv/.avi files, not committed — see tasks.md T007)
```

**Structure Decision**: Single project (Option 1), organized as one top-level package, `src/cvip/`, with one subpackage per pipeline concern rather than one top-level package per feature. This feature (Video Loader) lives at `src/cvip/video/` — no separate frontend/backend or mobile split applies. It exposes a single entry point (`video.loader.load_video`) consumed by the pipeline orchestrator that will run scene detection, replay detection, OCR, and event detection in later features, each landing in its own sibling subpackage (`ocr/`, `replay/`, `events/`, etc.) rather than its own top-level package. `src/cvip/common/diagnostics.py` is introduced alongside it as shared infrastructure: Video Loader is the first module to implement the project-wide Module Observability & Diagnostics standard (FR-013), and later modules are expected to reuse the same emitter rather than each inventing their own logging shape.

**Revision note**: This feature originally planned `src/video_loader/` and `src/common/` as separate top-level packages. Both were moved under `src/cvip/` (as `src/cvip/video/` and `src/cvip/common/`) once the project's real top-level package layout was established across `src/cvip/{config,video,ocr,replay,events,db,clips,templates,common}/`. Every path below, and in `tasks.md`, `data-model.md`, `research.md`, and `contracts/video_loader_contract.md`, was updated to match.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

None — the Constitution Check above found no violations, so no complexity needs justifying.
