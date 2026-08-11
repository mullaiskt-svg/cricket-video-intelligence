# Cricket Video Intelligence Platform (CVIP)

## Project Overview
Offline, CLI-driven cricket match analysis and highlight generation. Analyzes a broadcast once, builds a queryable SQLite event database, and generates unlimited highlight videos from it without reprocessing.

## Authority Order
Constitution (`.specify/memory/constitution.md`) > `docs/PRD.md` > `specs/technical_plan.md` > `specs/features.md`. Any conflict resolves in favor of the higher document.

## Tech Stack
- Python 3.11+
- OpenCV + PySceneDetect (scene detection), Tesseract via `pytesseract` (OCR), FFmpeg (stitching)
- SQLite (event database), `loguru` (structured logging), `psutil` (peak-memory diagnostics)
- Windows 11 desktop, CPU-only, fully offline

## Package Layout
One top-level package, `src/cvip/`. In practice, every module that consumes frames via the Frame Extraction Service or otherwise sits in the frame-analysis pipeline (Video Loader through the OCR Timeline Smoother — Modules 1, 1a, 2, 3, 4, 4a) lives together in `src/cvip/video/`, one file-set per module (`<module>.py`, `<module>_models.py`, `<module>_errors.py`), rather than one subpackage per module — this avoids awkward cross-package imports between tightly-coupled pipeline stages (e.g., Replay Detection consuming Scene Detection's result type, the OCR Timeline Smoother consuming Scoreboard OCR's). `common/` holds cross-cutting infrastructure (`diagnostics.py`) shared by every module. A later module that *isn't* part of this frame-analysis chain (Event Detection, Event Ranking, Clip Generator, Video Stitcher) should get its own subpackage per its own concern (`events/`, `clips/`, etc.) rather than also being folded into `video/` — see `specs/001-video-loader/plan.md` Project Structure for the pattern to follow when adding a new subpackage.

(Superseded: an earlier version of this section listed `{video, ocr, replay, events, db, clips, templates, config, common}` as separate one-subpackage-per-concern directories. Modules 3 and 4 were both placed in `video/` instead of dedicated `replay/`/`ocr/` packages, and Module 4a followed the same precedent — this section now documents that actual, intentional convention rather than the original aspirational one.)

## Pipeline Modules
See `specs/technical_plan.md` for full detail; summary:

| # | Module | Status |
|---|---|---|
| 1 | Video Loader | Implemented and merged: `specs/001-video-loader/`, `src/cvip/video/loader.py` |
| 1a | Frame Extraction Service (1 FPS, MVP addition) | Implemented and merged: `specs/002-frame-extraction-service/`, `src/cvip/video/frame_extraction.py` |
| 2 | Scene Detection (PySceneDetect + OpenCV) | Implemented and merged: `specs/003-scene-detection/`, `src/cvip/video/scene_detection.py` |
| 3 | Replay Detection | Implemented and merged: `specs/004-replay-detection/`, `src/cvip/video/replay_detection.py` |
| 4 | Scoreboard OCR (Tesseract) | Implemented and merged: `specs/005-scoreboard-ocr/`, `src/cvip/video/scoreboard_ocr.py`; pluggable per-broadcast-format parser architecture in `scoreboard_parsers.py` (3 formats supported), per-parser preprocessing strategy in `scoreboard_preprocessing.py` |
| 4a | OCR Timeline Smoother (MVP addition) | Implemented and merged: `specs/006-ocr-timeline-smoother/`, `src/cvip/video/ocr_timeline_smoother.py` |
| 5 | Event Detection | Implemented and merged: `specs/007-event-detection/`, `src/cvip/events/detection.py`; State Transition Detection (`src/cvip/events/state_transition.py`) collapses the raw OCR timeline into distinct score states before comparison — see below before starting further work here |
| 6 | Fielding Detection | Deferred post-MVP (`docs/RISK_REGISTER.md` R4) |
| 7 | Event Ranking | Values live in `config/default.yaml`, not duplicated elsewhere |
| 8 | Clip Generator | Implemented and merged: `specs/008-clip-generator/`, `src/cvip/clips/generator.py` |
| 9 | Video Stitcher (FFmpeg) | Implemented and merged: `specs/009-video-stitcher/`, `src/cvip/stitcher/stitcher.py` |
| 10 | Event Database (SQLite persistence/query layer) | Implemented and merged: `specs/010-event-database/`, `src/cvip/db/database.py` |
| — | Pipeline Orchestrator | Implemented and merged: `specs/012-pipeline-orchestrator-cli/`, `src/cvip/orchestrator.py`. Sequences Video Loader→Scene Detection→Replay Detection→Scoreboard OCR→OCR Timeline Smoother→Event Detection for `analyze` (Frame Extraction has no orchestrator-level call site of its own — it's a shared library Modules 2/3/4 each already call internally), and Clip Generator→Video Stitcher for `generate`; owns single-pass enforcement via the Event Database. An `IN_PROGRESS` match (a prior run that died mid-`analyze`) is treated the same as `COMPLETE` for the single-pass gate — true per-module resume is undesigned, documented future scope. |
| — | CLI (`cvip`) | Implemented and merged: `specs/012-pipeline-orchestrator-cli/`, `src/cvip/cli.py`. Full command reference: `specs/cli.md` — `analyze`/`generate`/`export-timeline`/`inspect-db`/`doctor`/`validate` all real. Argument parsing and delegation only, per `specs/technical_plan.md`'s own instruction — contains no pipeline-sequencing logic, verified by a static contract test (`tests/contract/test_cli_contract.py`) that it never imports `cvip.video`/`.events`/`.clips`/`.stitcher`/`.db`/`.metadata` directly. `generate --template player/team/custom` parses but is rejected with a "planned for V1.5" error (V1.5 scope, `specs/cli.md`'s own documented split) — only `--template match` actually runs. |
| — | Structured Match Metadata Validation Layer | Implemented and merged: `specs/013-match-metadata-validation/`, `src/cvip/metadata/`. Optional, decoupled post-hoc layer (`cvip validate <match> --metadata PATH [--recover] [--enrich]`) that aligns externally-supplied ball-by-ball commentary against an already-COMPLETE match's own OCR-detected events: reports recall/precision (`--metadata` alone, read-only), recovers events OCR missed entirely (`--recover`, additive write, source-tagged `'METADATA'`), and attaches dismissal type/fielder to wicket events from commentary text (`--enrich`) — this is the "another reliable player-stat source" the note below anticipated. `cvip analyze`/`generate` are provably unaffected whether or not this feature is ever used (FR-003). Bumped the Event Database schema to v2 (additive only — `events.source`/`dismissal_type`/`fielder`, new append-only `metadata_operations` audit table); a v1 database needs `cvip analyze --force` before this feature can write to it. |
| — | Anchor Validation for Timeline Alignment | Implemented and merged: `specs/014-anchor-validation/`, `src/cvip/metadata/anchor_validation.py`. Strengthens the Structured Match Metadata Validation Layer above: real validation against the Wild Wanderers vs Phoenix Firehawks match found `--recover` anchoring some events to the wrong point in the video (6/33 out of chronological order, one 35 minutes off) because alignment committed to the nearest scoreboard reading unconditionally. Candidates are now ranked and scored (OCR confidence, chronological ordering, neighbor pacing) into HIGH/MEDIUM/LOW/INSUFFICIENT confidence tiers, and only HIGH/MEDIUM are auto-recovery-eligible; `cvip validate` surfaces the per-event tier/reason and a run-level trust summary. |
| — | Robust Innings Transition Detection | Implemented and merged: `specs/015-innings-transition-detection/`, `src/cvip/video/innings_transition.py`. Replaces three previously-independent, single-signal "runs and wickets both dropped" copies of the same heuristic (Scoreboard OCR's own validation, Event Detection's own FR-010, the Orchestrator's `_tag_readings_with_innings`) with one shared `InningsTracker` every consumer now uses identically, requiring multi-signal corroboration (plausible reset magnitude, over/ball reset, persistence) before accepting a transition — closes a real incident where the weakest of the three fragmented a real two-innings match into five. |
| — | Scene-Cut-Anchored Clip Windows | Implemented and merged: `specs/016-scene-cut-clip-windows/`, `src/cvip/clips/generator.py`. Optional enhancement to Module 8 (Clip Generator): when a caller supplies `ClipGenerationRequest.scene_cuts`, a clip's start snaps to the nearest real camera cut before the event instead of a fixed pre-roll offset (which could land mid-replay or mid-setup), falling back to the existing fixed-offset behavior when no qualifying cut is found within range. Currently dormant in production — `orchestrator.generate()` does not yet populate `scene_cuts`; wiring Scene Detection's output through to `generate()` (e.g. via a persisted `scenes` table) is a deliberately deferred follow-on (research.md Decision 2), documented as a known limitation until that wiring and real-data calibration exist. |

**Before specifying Module 5 (Event Detection) or the Event Database**: read `specs/technical_plan.md`'s "Event Taxonomy & Detectability" and "Cross-Cutting Concern" sections. The video-only pipeline still cannot distinguish dismissal types or attribute a catch to a fielder from OCR alone — `RUN_OUT`, `CATCH`, `HAT_TRICK`, `MATCH_WINNING_SHOT`, `GREAT_FIELDING` remain out of scope as `event_type` values, and `config/default.yaml`'s `ranking` block must still not list them. Dismissal type/fielder detail is now available, but only as optional `events.dismissal_type`/`fielder` columns populated by the Structured Match Metadata Validation Layer above when a user supplies commentary and runs `--enrich` — never derived from video/OCR itself, and never populated for a match analyzed without it.

## Non-Negotiables (Constitution)
- Offline-first: no network/cloud calls at runtime
- CPU-only: no GPU dependency
- ≤40 minutes / <6GB peak memory for a 3-hour match
- Single-pass: never reprocess the same video (`matches` table + Video Loader's `file_hash`, FR-014, is the enforcement mechanism)
- ≥95% detection accuracy (fours/sixes/wickets), ≥90% replay removal, confidence score on every detected event
- Every module: clear input/output contract, independently testable, contract tests written before implementation, 100% coverage on critical paths
- Fail fast with a specific error; never fall back to a silent default

## Key Documents
- `docs/PRD.md` — product vision (includes V2/future scope; not all of it is near-term)
- `specs/technical_plan.md` — architecture, database schema, module specs (authoritative except where a module has its own `specs/00X-*/` directory)
- `specs/features.md` — MVP / V1.5 / V2 feature split
- `specs/cli.md` — full CLI command reference
- `docs/MVP_PLAN.md` — phased delivery plan
- `docs/RISK_REGISTER.md` — known risks and mitigations
- `docs/DEPENDENCIES.md` — native (non-pip) dependency setup (FFmpeg, Tesseract)
- `docs/ARCHITECTURE_REVIEW.md` — pre-implementation review findings; check before starting a new module in case a finding affects it

## Reference
Full PRD: `docs/PRD.md` (this repo, not an external path).
