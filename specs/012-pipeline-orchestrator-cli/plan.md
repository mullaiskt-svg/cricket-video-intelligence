# Implementation Plan: Pipeline Orchestrator and CLI

**Branch**: `012-pipeline-orchestrator-cli` | **Date**: 2026-08-04 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/012-pipeline-orchestrator-cli/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

Wires the ten already-implemented, already-tested pipeline modules (Video Loader through Event Database) into an actual runnable tool: `src/cvip/orchestrator.py` (pure sequencing — no detection/persistence/transformation logic of its own) and `src/cvip/cli.py` (argument parsing and delegation only, per `specs/technical_plan.md`'s own explicit file-location and separation-of-concerns note). `analyze()` sequences Video Loader → Frame Extraction (called once per consuming stage at that stage's own sampling rate, not a single shared step) → Scene Detection → Replay Detection → Scoreboard OCR → OCR Timeline Smoother → Event Detection, opening the Event Database first for the single-pass check and persisting each stage's output to it as that stage completes. `generate()` queries the Event Database and sequences Clip Generator → Video Stitcher, never touching Modules 1-7. `cli.py` translates `config/default.yaml` into each module's own existing request dataclass exactly once per invocation, and translates every module's own existing failure taxonomy into `specs/cli.md`'s ten-value exit-code table.

## Technical Context

**Language/Version**: Python 3.11+

**Primary Dependencies**: `argparse` (stdlib — no new pip dependency; matches this platform's established minimal-dependency posture, e.g. Event Database's `sqlite3`) for CLI argument parsing; `PyYAML` for config loading — already *listed* in `requirements.txt` (pinned `6.0.1`) but, confirmed during implementation, never actually installed or imported by any existing code (`config/default.yaml`'s many references throughout the codebase are all documentation/comments, not a real parse call anywhere) — this feature is the first to actually install and use it, not a genuinely new dependency addition to the project's own declared manifest. Every pipeline module this feature calls is already implemented: `cvip.video.loader`, `cvip.video.frame_extraction`, `cvip.video.scene_detection`, `cvip.video.replay_detection`, `cvip.video.scoreboard_ocr`, `cvip.video.ocr_timeline_smoother`, `cvip.events.detection`, `cvip.clips.generator`, `cvip.stitcher.stitcher`, `cvip.db.database`.

**Storage**: Delegates entirely to Module 10 (Event Database) — this feature opens and drives an `EventDatabase` connection but owns no schema or persistence logic of its own.

**Testing**: pytest. Given this feature's job is sequencing ten already-independently-tested modules, not new detection/transformation logic, its own test suite is deliberately three-tiered (research.md Decision 5): (1) unit tests for `orchestrator.py`'s sequencing/translation logic with every pipeline module call mocked (`mocker.patch`) — verifying call order, config-to-request translation, single-pass gating, and fail-fast-on-first-error behavior, without ever running real OCR/scene-detection; (2) unit/contract tests for `cli.py`'s argument parsing, help text, and exit-code translation, with the orchestrator layer mocked; (3) exactly one genuine, real, slow end-to-end smoke test (`tests/benchmark/`, deselected by default like every prior module's own benchmark tier) running the actual full `analyze` pipeline against a real short video fixture (`tests/fixtures/video_loader/valid_short.mp4`, 5 seconds, no real scoreboard content) to prove the real wiring works end-to-end without crashing — not a detection-accuracy test, which remains each underlying module's own already-established, already-measured concern (specs/005 through specs/007's own accuracy work).

**Target Platform**: Windows 11 desktop, CPU-only — no new surface; every constitution gate this feature could affect is already satisfied by the modules it calls.

**Project Type**: Single project. Per `specs/technical_plan.md`'s own explicit file-location note, this feature is NOT part of any existing subpackage — `src/cvip/orchestrator.py` and `src/cvip/cli.py` are new top-level modules directly under `src/cvip/`, not a new subpackage (there is exactly one orchestrator and one CLI entry point for the whole platform, not a family of related types the way `events/`, `clips/`, `db/` each host).

**Performance Goals**: This feature adds negligible overhead of its own (argument parsing, config translation, sequencing calls) — the platform's real 40-minute/6GB `analyze` budget and 2-minute `generate` budget (constitution Principle II) are already owned and measured by the modules this feature calls, not by this feature itself.

**Constraints**: Fully offline, CPU-only (trivially — no new dependency of any kind beyond stdlib/PyYAML); single-pass enforcement is a hard constitutional requirement (Principle III) this feature is the *sole* enforcement point for, since no individual module owns cross-invocation state; fail-fast on the first stage failure, no partial continuation (Principle VI); the CLI layer itself must contain zero sequencing logic (FR-015) — testable directly, by inspection, by confirming `cli.py` never imports any `cvip.video.*`/`cvip.events.*`/`cvip.clips.*`/`cvip.stitcher.*` module directly, only `cvip.orchestrator`.

**Scale/Scope**: One `cvip analyze`/`cvip generate`/`cvip export-timeline`/`cvip inspect-db`/`cvip doctor` invocation per process; single-process, synchronous, no concurrency of its own (matches Event Database's own single-process-access assumption).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate | Status |
|---|---|---|
| I. Offline-First, Always | No network/cloud calls anywhere | PASS (trivially) — every call this feature makes is either local module invocation or local file I/O |
| II. Performance is Non-Negotiable | Fits within the overall 40 min / 6GB / CPU-only budget | PASS — this feature adds negligible overhead of its own; the real budget is owned by the modules it sequences, each already independently measured against it |
| III. Single-Pass Analysis Principle | Each match analyzed only once, no reprocessing | PASS — this feature **is** the single point that enforces this end-to-end (FR-002): it is the first caller in the whole platform positioned before any pipeline stage runs, since no individual module has cross-invocation memory of its own |
| IV. Detection Accuracy Requirements | Confidence scores on detected events; contributes to ≥95% detection accuracy | N/A — this feature detects nothing; it sequences modules that already own detection and its own accuracy measurement (specs/005 through specs/007) |
| V. Modular & Extensible Architecture | Independently testable, clear I/O contract | PASS — `orchestrator.py` (sequencing) and `cli.py` (argument parsing/delegation) are themselves two cleanly separated layers (FR-015), each independently testable; adding an eleventh pipeline module in the future is a change scoped to `orchestrator.py`'s sequence list, not a redesign |
| VI. Fail Fast, Never Silently | Crash loudly on structural failure, no silent fallback, detailed logging | PASS — FR-005/FR-012/FR-017's fail-fast-on-first-stage-failure, exit-code mapping, and IN_PROGRESS-never-silently-COMPLETE guarantees directly implement this; FR-016 requires a visible per-stage progress marker so a long run's failure point is never a mystery |
| VII. Test-First Development | Contract tests at module boundaries; 100% coverage on critical paths | PASS — contract tests for both `orchestrator.py` and `cli.py` planned ahead of implementation; coverage gate planned in tasks.md Polish phase, matching every prior feature's precedent |

No violations identified. Complexity Tracking table not required.

**Post-Phase 1 re-check**: Design artifacts (data-model.md, contracts/, quickstart.md) introduce no new dependency beyond stdlib `argparse` and the already-present `PyYAML`, no new storage, and no network/GPU surface — `AnalysisRun`/`GenerateRequest`/the exit-code mapping (research.md) are all pure in-memory constructs and a fixed translation table. All gates above still PASS after design; no re-justification needed.

## Project Structure

### Documentation (this feature)

```text
specs/012-pipeline-orchestrator-cli/
├── plan.md              # This file (/speckit-plan command output)
├── research.md          # Phase 0 output (/speckit-plan command)
├── data-model.md         # Phase 1 output (/speckit-plan command)
├── quickstart.md         # Phase 1 output (/speckit-plan command)
├── contracts/            # Phase 1 output (/speckit-plan command)
└── tasks.md              # Phase 2 output (/speckit-tasks command - NOT created by /speckit-plan)
```

### Source Code (repository root)

```text
src/cvip/
├── video/{loader,frame_extraction,scene_detection,replay_detection,scoreboard_ocr,ocr_timeline_smoother}.py   # existing
├── events/detection.py    # existing
├── clips/generator.py     # existing
├── stitcher/stitcher.py   # existing
├── db/database.py         # existing
├── orchestrator.py         # NEW: analyze()/generate()/inspect_db()/export_timeline()/
│                            #      run_doctor_checks() sequencing, config-to-request
│                            #      translation, single-pass gating, per-stage
│                            #      Event Database persistence
├── orchestrator_models.py  # NEW: AnalyzeRequest, AnalysisRun, GenerateRequest,
│                            #      GenerateResult, DependencyCheckResult (data-model.md)
│                            #      -- matching CLAUDE.md's <module>_models.py convention
├── orchestrator_errors.py  # NEW: OrchestratorFailureReason + OrchestratorError
│                            #      (the pre-exit-code-translation failure taxonomy)
└── cli.py                  # NEW: argparse setup for analyze/generate/export-timeline/
                             #      inspect-db/doctor; exit-code translation
                             #      (contracts/exit_code_mapping.md); the `main()`
                             #      function pyproject.toml's `cvip` entry point calls

tests/
├── contract/
│   ├── test_orchestrator_contract.py   # asserts orchestrator.py matches
│   │                                     # contracts/orchestrator_contract.md
│   └── test_cli_contract.py            # asserts cli.py contains no direct
│                                         # cvip.video/.events/.clips/.stitcher imports
│                                         # (FR-015), and every documented command/flag parses
├── unit/
│   ├── test_orchestrator_analyze.py    # analyze() sequencing, config translation,
│   │                                     # single-pass gating, fail-fast-on-error --
│   │                                     # every pipeline module call mocked
│   ├── test_orchestrator_generate.py   # generate() query translation, Clip
│   │                                     # Generator -> Video Stitcher sequencing,
│   │                                     # template rejection -- mocked
│   ├── test_cli_analyze.py             # `cvip analyze` argument parsing/validation,
│   │                                     # exit-code translation -- orchestrator mocked
│   ├── test_cli_generate.py            # `cvip generate` argument parsing/validation,
│   │                                     # exit-code translation -- orchestrator mocked
│   ├── test_cli_inspect_export.py      # `cvip inspect-db`/`cvip export-timeline`
│   │                                     # argument parsing and output formatting --
│   │                                     # Event Database mocked
│   └── test_cli_doctor.py              # `cvip doctor`'s individual checks --
│                                         # subprocess/importlib/filesystem calls mocked
└── benchmark/
    └── test_orchestrator_e2e_smoke.py  # the ONE real, slow, full-pipeline smoke test
                                          # (research.md Decision 5) -- deselected by
                                          # default like every prior benchmark test
```

**Structure Decision**: Single project (Option 1). `orchestrator.py`/`orchestrator_models.py`/`orchestrator_errors.py`/`cli.py` live directly under `src/cvip/`, not inside a new subpackage — per `specs/technical_plan.md`'s own explicit statement that `src/cvip/orchestrator.py` and `src/cvip/cli.py` are single top-level modules, matching the fact that there is exactly one of each for the whole platform (unlike `events/`, `clips/`, `db/`, which each host a family of related types justifying their own subpackage). `orchestrator_models.py`/`orchestrator_errors.py` are new top-level files with a name prefix rather than `orchestrator/models.py`/`orchestrator/errors.py`, consistent with that same "no subpackage" decision while still following CLAUDE.md's established `<module>.py`/`<module>_models.py`/`<module>_errors.py` per-module file-set convention.

## Complexity Tracking

> **Fill ONLY if Constitution Check has violations that must be justified**

None — the Constitution Check above found no violations, so no complexity needs justifying.
