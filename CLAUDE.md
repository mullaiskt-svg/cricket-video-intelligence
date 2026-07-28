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
| 4 | Scoreboard OCR (Tesseract) | Implemented and merged: `specs/005-scoreboard-ocr/`, `src/cvip/video/scoreboard_ocr.py` |
| 4a | OCR Timeline Smoother (MVP addition) | In progress: `specs/006-ocr-timeline-smoother/` |
| 5 | Event Detection | Architecture-level only; **see below before starting** |
| 6 | Fielding Detection | Deferred post-MVP (`docs/RISK_REGISTER.md` R4) |
| 7 | Event Ranking | Values live in `config/default.yaml`, not duplicated elsewhere |
| 8 | Clip Generator | Architecture-level only |
| 9 | Video Stitcher (FFmpeg) | Architecture-level only |
| — | Pipeline Orchestrator | Sequences 1→1a→2→3→4→4a→5 for `analyze`, and 8→9 for `generate`; owns match-registry lookups and resumability |
| — | CLI (`cvip`) | Full command reference: `specs/cli.md` |

**Before specifying Module 5 (Event Detection) or the Event Database**: read `specs/technical_plan.md`'s "Event Taxonomy & Detectability" and "Cross-Cutting Concern" sections. The data model cannot currently distinguish dismissal types (bowled/caught/LBW/run out/stumped) or attribute a catch to a fielder — `RUN_OUT`, `CATCH`, `HAT_TRICK`, `MATCH_WINNING_SHOT`, `GREAT_FIELDING` are explicitly out of scope until that data source is designed. Do not add them back to `config/default.yaml`'s `ranking` block without resolving this first.

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
