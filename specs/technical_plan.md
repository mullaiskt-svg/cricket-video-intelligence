# CVIP Technical Plan

## MVP Goal

Analyze one cricket broadcast once, extract scoreboard-based events, persist them to SQLite, and generate replay-excluded highlight videos without reprocessing — as a CLI pipeline. See [docs/MVP_PLAN.md](../docs/MVP_PLAN.md) for the phased delivery plan and [specs/features.md](./features.md) for the MVP/V1.5/V2 feature split.

## Architecture Overview

### Phase 1: Match Analysis Pipeline
[PRD Section 6]

```
Input Video (MP4/MKV, 3-4hr)
    ↓
[Module 1] Video Loader
    - Detect FPS, resolution, duration, codec
    ↓
[Module 1a] Frame Extraction Service  <-- shared by Modules 2, 3, 4, (future) 6
    - Configurable-rate frame streaming, timestamps, progress, resume
    ↓
[Module 2] Scene Detection (PySceneDetect + OpenCV)
    - Detect scene changes, camera transitions, replay transitions
    ↓
[Module 3] Replay Detection
    - Logo detection, scoreboard disappearance, slow-motion
    ↓
[Module 4] Scoreboard OCR (Tesseract)
    - Extract runs, wickets, overs, batter, bowler every second
    ↓
[Module 5] Event Detection
    - Compare OCR readings, detect score changes
    ↓
[Module 6] Fielding Detection
    - Detect diving catches, boundary saves, direct hits
    ↓
[Module 7] Event Ranking
    - Assign importance scores (0-100)
    ↓
Event Database (SQLite) + Timeline JSON
```

Modules 2, 3, 4 (and, when built, 6) all read pixel data exclusively through Module 1a — none of them opens the video file directly. See Module 1a below for why, and for the open question about whether they can share a single decode pass.

### Phase 2: Highlight Generation
[PRD Section 6]

```
User Selection (filter, template, players)
    ↓
Query Event Database
    ↓
[Module 8] Clip Generator
    - 8s before event, 12s after, merge overlaps
    ↓
[Module 9] Video Stitcher (FFmpeg)
    - Merge clips, maintain resolution, copy codec
    ↓
MP4 Output Highlight Video
```

## Module Specifications

[PRD Section 7 defines each module]

### Module 1: Video Loader

Authoritative spec, plan, data model, and contract now live in [specs/001-video-loader/](./001-video-loader/spec.md) — see that directory rather than treating this section as the source of truth. Summary:

- Input: video file path (MP4/MKV)
- Output: `LoadResult` — on success, `duration_seconds`, `resolution`, `frame_rate`, `codec`; on failure, a specific `failure_reason` (`FILE_NOT_FOUND`, `UNSUPPORTED_FORMAT`, `CORRUPTED_OR_UNDECODABLE`)
- Validation: file must exist and decode at least one frame before being considered valid; failures block all downstream modules (fail-fast, per constitution Principle VI)

### Module 1a: Frame Extraction Service

**Revised scope**: originally scoped as a narrow "sample frames at 1 FPS for OCR" step. Reframed as the platform's single shared abstraction for reading frames from a validated video. Every downstream module that needs pixel data — Scene Detection (2), Replay Detection (3), Scoreboard OCR (4), and (when built) Fielding Detection (6) and any future computer-vision module — MUST consume frames through this service rather than opening the video file with OpenCV directly. This is what constitution Principle V ("Modular & Extensible Architecture") actually requires for frame access: one shared contract, not five modules each independently wrapping `cv2.VideoCapture`.

**Input**: a successful `LoadResult` from Video Loader (`specs/001-video-loader/`) — never a raw file path; the service trusts Video Loader's validation rather than re-validating the file itself.

**Responsibilities**:
- **Configurable sampling rate**: callers specify how densely they need frames — every frame (Scene Detection's likely need), a fixed rate such as 1 FPS (Scoreboard OCR's need, per `config/default.yaml`'s `video.sample_fps`), or a custom frame-index/timestamp list. Not hardcoded to any one rate.
- **Timestamp/frame-index generation**: every yielded frame carries both its 0-based index in the *original* video and its timestamp in seconds from match start — no caller computes this itself.
- **Streaming iteration**: exposed as a generator/iterator, never a function returning a list — the service must not hold the whole video (or a large fraction of it) in memory at once, per the constitution's <6GB budget (Principle II).
- **Deterministic output**: the same video plus the same sampling configuration always yields the identical sequence of (frame_index, timestamp) pairs, run to run — no dependency on wall-clock timing or thread scheduling.
- **Progress reporting**: exposes current position (frames processed / total, or elapsed / total duration) so the CLI (`tqdm` is already a dependency) or the Pipeline Orchestrator can report progress during a multi-hour extraction.
- **Resume support**: extraction can start from an arbitrary frame index or timestamp, not only from the beginning — this is what lets the Pipeline Orchestrator's "resume interrupted processing" responsibility (see below) skip already-processed frames instead of restarting a multi-hour extraction from zero.
- **Standardized diagnostics**: emits one `ExecutionDiagnostics` record (`src/cvip/common/diagnostics.py`) per extraction run (covering the whole requested range), not per-frame — a per-frame record would itself become a performance and log-volume problem at 10,000+ frames per match.

**Resolved during `/speckit-plan`** (`specs/002-frame-extraction-service/research.md`):
- **Shared decode pass**: decided against, for v1. Each caller (Scene Detection, Replay Detection, Scoreboard OCR) performs its own independent extraction request rather than sharing one broadcast decode pass — a true shared pass would need buffering/backpressure machinery this single-threaded, synchronous codebase has no precedent for. The Performance Targets budget below already priced Scene Detection's full-frame pass and this service's 1 FPS pass as *separate* line items, so this decision doesn't invalidate that budget — it's what the budget already assumed. Revisit only if the aggregate 40-minute budget proves too tight once Modules 2-4 are actually benchmarked.
- **Module location**: `src/cvip/video/frame_extraction.py` (plus `frame_extraction_models.py`/`frame_extraction_errors.py`), not `src/cvip/common/` — it consumes Video Loader's `LoadResult`/`MatchVideoSource` directly, and every consumer already depends on `cvip.video` for that type regardless of where the extractor itself lives.

**Still open** (Scene Detection's own concern — resolve during that module's `/speckit-plan`):
- Whether PySceneDetect (Module 2's named technology, `scenedetect==0.6.1` per requirements.txt) can consume frames fed by this service, or whether it insists on opening the file itself via its own reader — if the latter, Module 2 either reimplements scene-cut detection directly on this service, or PySceneDetect's internal reader becomes a documented, deliberate exception to the "always use this service" rule.

### Module 2: Scene Detection
- Technology: PySceneDetect + OpenCV
- Input: frames from Module 1a's Frame Extraction Service — see Module 1a's open design question on reconciling this with PySceneDetect's own reader
- Output: List of scene boundaries with timestamps

### Module 3: Replay Detection
- Methods: Logo detection, scoreboard tracking, slow-mo
- Input: frames from Module 1a's Frame Extraction Service, not direct OpenCV access
- Output: Replay segments with start/end times
- Target: Remove ≥90% replays

### Module 4: Scoreboard OCR
- Technology: Tesseract OCR
- Frequency: Every 1 second, requested from Module 1a's Frame Extraction Service via `config/default.yaml`'s `video.sample_fps`
- Input: one sampled video frame, the configured scoreboard region (ROI), and that frame's timestamp
- Extract: runs, wickets, overs, batter (striker), non-striker, bowler, run_rate
- Configurable ROI via config file
- Output: one `ScoreboardSample` per sampled frame, persisted to the `scoreboard_readings` table (see Database Schema) as the raw Scoreboard Timeline output required by PRD Section 6. Timestamps are stored as `timestamp_seconds` (REAL), consistent with the rest of the schema, even if the frame's native timestamp arrives in milliseconds — convert at the module boundary, not downstream.
- Confidence fields (both persisted, and distinct from each other): `ocr_confidence` — Tesseract's own character-recognition confidence for the raw text; `parse_confidence` — confidence that the raw text was successfully interpreted into valid, cricket-rule-consistent runs/wickets/overs/names. A high `ocr_confidence` with a low `parse_confidence` means "we read the characters clearly, but they don't parse into a sane score" (e.g., an overlay/animation was mid-transition).
- Failure/low-confidence handling — a single bad reading does **not** fail the pipeline (that would violate the Single-Pass Analysis principle by wasting an otherwise-good 3-hour run over one noisy second); instead:
  - **Scoreboard region not detected in frame** (e.g., temporarily obscured, off-screen graphic): recorded as a `ScoreboardSample` with `ocr_confidence = 0` and empty `raw_text`, not a hard failure.
  - **OCR confidence below a configurable threshold**: recorded as-is with its low `ocr_confidence`; Module 4a (OCR Timeline Smoother) is responsible for discounting or interpolating over low-confidence samples, not Module 4 itself.
  - **Parsed score violates cricket rules** (e.g., wickets decreasing, runs going backward, overs out of range): recorded with `parse_confidence = 0`; Module 5 (Event Detection) MUST NOT derive an event from a sample with `parse_confidence = 0`.
  - These are the mitigations for [docs/RISK_REGISTER.md](../docs/RISK_REGISTER.md) R1 (Scoreboard OCR Reliability): "OCR confidence tracking" and "cricket-rule validation" are implemented exactly as `ocr_confidence`/`parse_confidence` and the rule-violation check above.

### Module 4a: OCR Timeline Smoother (MVP addition)
- Smooths noisy per-second OCR readings (drops transient misreads, fills short gaps) before Module 5 diffs them
- Implements the "timeline smoothing" mitigation listed in [docs/RISK_REGISTER.md](../docs/RISK_REGISTER.md) R1 (Scoreboard OCR Reliability)
- Output: a cleaned `scoreboard_readings` sequence (same schema as Module 4's output) ready for diffing

### Module 5: Event Detection
- Input: the (smoothed) `scoreboard_readings` sequence from Module 4a, plus the replay timeline from Module 3 (Replay Detection)
- Logic: Compare consecutive (smoothed) OCR readings; skip any reading with `parse_confidence = 0` (see Module 4) rather than deriving a spurious event from it
- Initial MVP event types: `FOUR`, `SIX`, `WICKET`, `FIFTY`, `CENTURY`, `TEAM_MILESTONE` — this is a hard ceiling, not a starting point: see "Event Taxonomy & Detectability" below for why dismissal-subtype events (`RUN_OUT`, `CAUGHT`, etc.), `HAT_TRICK`, and `MATCH_WINNING_SHOT` are explicitly out of scope until a new data source is designed for them. `WICKET` stays generic (no subtype) for MVP and V1.5.
- Output: one row per detected event, inserted into the `events` table (see Database Schema; collectively this is the "Event Database"). Module 5 populates `event_type`, `timestamp_seconds`, `innings`, `over_number`, `ball_in_over`, `player`, `team`, `confidence`, `importance` (per Module 7's scoring), and `is_replay` (cross-referenced against Module 3's replay timeline). It does **not** populate `clip_start_seconds`/`clip_end_seconds` — those are computed later by Module 8 (Clip Generator) applying the 8s/12s pre/post-roll window, so a fresh event row has them `NULL` until Module 8 runs.
- **Confidence derivation**: `events.confidence` is the minimum of `ocr_confidence` and `parse_confidence` across the `scoreboard_readings` row(s) that produced the detected delta (i.e., the lower of the two readings bracketing the change, and the lower of each reading's own two confidence fields). A confidence chain is only as strong as its weakest link — if either reading was noisy or its parse was rule-inconsistent, the derived event's confidence must reflect that, not average it away.
- Open design question for the full spec (not resolved at this architecture-summary level): whether `player` for a `WICKET` event is the dismissed batter, the bowler, or both — resolve this when Event Detection gets its own `/speckit-specify` treatment.

### Module 6: Fielding Detection
- Events: Diving catch, running catch, boundary save, direct hit, etc.
- Method: Lightweight CV heuristics (v1), future AI models
- Input: frames from Module 1a's Frame Extraction Service (once built), not direct OpenCV access
- Output: Store to database with confidence
- **Status**: Deferred post-MVP — see Deferred Until Later, below, and [docs/RISK_REGISTER.md](../docs/RISK_REGISTER.md) R4

### Module 7: Event Ranking
- Importance Scoring: values live in `ranking` in [config/default.yaml](../config/default.yaml) — the source of truth. Do not copy the numbers into this document; if they need updating, update the config only.
- **Detectability tier** (see "Event Taxonomy & Detectability" below): only event types Module 5 can actually produce today have a *meaningful* ranking score. PRD Section 7's full 10-event table includes several (`Hat Trick`, `Match Winning Shot`, `Run Out`, `Catch`, `Great Fielding`) that no current module can detect — their scores exist in PRD Section 7 as long-term vision, not as MVP configuration. `config/default.yaml` only defines scores for the event types Module 5 currently emits.
- Configurable values

### Module 8: Clip Generator
- Input: the event list (queried from the Event Database per user selection/template), the source video path, clip settings (pre-roll/post-roll seconds), and a replay-exclusion flag (see [docs/RISK_REGISTER.md](../docs/RISK_REGISTER.md) R2 "user-configurable replay inclusion")
- Default: 8s pre-roll, 12s post-roll (both configurable via clip settings, not hardcoded)
- Logic: compute each event's clip window, drop or keep replay-flagged events per the exclusion flag, merge overlapping clip windows, avoid duplicate clips
- Output: an ordered clip plan (start/end times + source path per clip) — **not** the final video; that is Module 9's output (see below). Clip plan generation performs no OCR, replay detection, or other analysis (constitution Principle III; PRD Section 6 — Phase 2 only queries the already-built Event Database)

### Module 9: Video Stitcher
- Input: the ordered clip plan from Module 8
- Technology: FFmpeg
- Strategy: Copy codec (no re-encoding)
- Output: the final MP4 highlight video, in original resolution — this, not Module 8's clip plan, is the "Final MP4 highlight video" deliverable of Phase 2

### Pipeline Orchestrator

Not one of the numbered PRD modules, but a required component: the thing that actually sequences Modules 1 → 1a → 2 → 3 → 4 → 4a → 5 (and separately, 8 → 9), rather than that sequencing logic living inside the CLI layer (which would undermine Principle V's "independently testable" modules by making the CLI the de facto integration point for all nine modules).

Responsibilities:
- **`analyze` sequencing**: run Modules 1 → 1a → 2 → 3 → 4 → 4a → 5 in order, passing each module's output to the next per that module's contract; stop immediately on any module's failure (Principle VI). Note Module 1a is a shared service Modules 2/3/4 each call into (with their own sampling rate), not a single one-shot step whose output only feeds Module 4.
- **Single-Pass Analysis enforcement**: before running anything, check the `matches` table (see Database Schema) for an existing row with the candidate file's `file_hash` (from Video Loader); if found and `--force` was not passed, stop with exit code 9 (`cli.md`) rather than reprocessing.
- **Match record lifecycle**: insert a `matches` row with `status = 'IN_PROGRESS'` before Module 2 begins, update to `'COMPLETE'` after Module 5 finishes successfully, or `'FAILED'` on error.
- **Resume interrupted processing** (PRD Section 16, previously an orphaned requirement with no owner): if a prior `cvip analyze` run for this `file_hash` left a `matches` row with `status = 'IN_PROGRESS'` (i.e., the process died mid-run), the Orchestrator is what would detect this and either resume from the last completed module or require `--force` to restart cleanly. The exact resume granularity (per-module vs. full-restart) is a follow-up decision, not resolved here — but the Orchestrator, not any individual module, is where it belongs.
- **`generate` sequencing**: query the Event Database per the CLI's filter arguments, then run Modules 8 → 9. Never invokes Modules 1-7 (Principle III; PRD Section 6 Phase 2 restriction).

**Location**: `src/cvip/orchestrator.py` (a single module to start; split into a package if it grows complex). The `cvip` CLI entry point itself lives at `src/cvip/cli.py` and should do nothing but argument parsing and delegation to the Orchestrator — it must not contain sequencing logic itself.

### CLI (MVP entry point)

Full command reference: [specs/cli.md](./cli.md). Summary:

- `cvip analyze` invokes the Pipeline Orchestrator's `analyze` sequencing, above
- `cvip generate --template <match|player|team|custom>` invokes the Orchestrator's `generate` sequencing — it does not rerun analysis
- `cvip export-timeline`, `cvip inspect-db`, and `cvip doctor` (environment/dependency check, implementing [docs/DEPENDENCIES.md](../docs/DEPENDENCIES.md)'s recommended startup checks) round out the MVP surface
- No GUI in MVP — the Interactive Timeline and Search UI are V2 scope (see [specs/features.md](./features.md))

## Cross-Cutting Concern: Event Taxonomy & Detectability

PRD Section 7's importance table and Section 8's full event taxonomy list several event types (`Hat Trick`, `Match Winning Shot`, `Run Out`, `Catch`, `Great Fielding`, and dismissal subtypes `Bowled`/`LBW`/`Stumped`/`Hit Wicket`) that **the current architecture has no data source for**. Module 4's OCR extracts only `runs`, `wickets` (a count), `over`, `batter`, `non_striker`, `bowler`, `run_rate` at one-reading-per-second granularity. A wicket falling only changes the `wickets` count and swaps `batter`/`non_striker` — there is no field capturing *how* the batter was dismissed, no fielder attribution for a catch, and no ball-level (as opposed to over-level) granularity that bowler-attributed consecutive-wicket tracking (`Hat Trick`) would require.

**Decision**: These event types are explicitly out of scope for MVP and V1.5, not implicitly missing. They require one of:
- An enhanced OCR source (e.g., reading a post-wicket "how out" scorecard overlay, if/when broadcasts reliably show one) — undesigned, not scheduled.
- Module 6 (Fielding Detection, already deferred post-MVP per `docs/RISK_REGISTER.md` R4) for `Catch`/`Great Fielding`.

Until one of those exists, `config/default.yaml`'s `ranking` block MUST only contain entries for event types Module 5 can actually emit (see Module 5 above). Do not add `HAT_TRICK`, `MATCH_WINNING_SHOT`, `RUN_OUT`, `CATCH`, or `GREAT_FIELDING` back into the config until their data source is designed — their presence previously implied detectability the pipeline didn't have.

**Canonical MVP/V1.5 event set**: `FOUR`, `SIX`, `WICKET` (generic, no subtype), `FIFTY`, `CENTURY`, `TEAM_MILESTONE`. Everything else in PRD Section 8's taxonomy remains valid long-term product vision, gated behind the data-source work above.

## Database Schema

[PRD Section 9]

```sql
-- One row per analyzed match; this table is what makes Single-Pass Analysis (constitution
-- Principle III) and `cvip analyze --force` / exit code 9 (see specs/cli.md) actually
-- implementable, and what `cvip inspect-db` reads. Populated by the Pipeline Orchestrator
-- from Video Loader's LoadResult (specs/001-video-loader/) at the start of `cvip analyze`.
--
-- Single-Pass enforcement: by default, `match_id` (and therefore the .sqlite filename,
-- data/matches/<match_id>.sqlite) is the first 12 hex characters of the Video Loader
-- file_hash (FR-014) -- so "has this exact video already been analyzed" is a simple
-- file-existence check, no registry needed. If the user overrides the output path with a
-- friendly name via `--output-db`, the file_hash column (not the filename) is what a
-- duplicate-analysis check must key against instead -- this override case requires scanning
-- data/matches/*.sqlite for a matching file_hash, which is a known follow-up, not yet built.
CREATE TABLE matches (
  match_id TEXT PRIMARY KEY,        -- default: file_hash[:12]; user-overridable via --output-db
  source_video_path TEXT NOT NULL,
  file_hash TEXT NOT NULL,          -- Video Loader FR-014 sampled digest
  duration_seconds REAL,
  resolution_width INTEGER,
  resolution_height INTEGER,
  frame_rate REAL,
  codec TEXT,
  analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  status TEXT CHECK (status IN ('IN_PROGRESS', 'COMPLETE', 'FAILED')) DEFAULT 'IN_PROGRESS'
);

CREATE UNIQUE INDEX idx_matches_file_hash ON matches (file_hash);

CREATE TABLE events (
  event_id INTEGER PRIMARY KEY,
  timestamp_seconds REAL,   -- seconds from match start; format as HH:MM:SS at display time
  innings INTEGER,          -- 1 or 2
  over_number INTEGER,      -- completed overs, 0-indexed within the innings
  ball_in_over INTEGER,     -- 0-5. Cricket "over.ball" notation (e.g. "18.4") is NOT a decimal
                             -- number -- there is no .6-.9 -- so this is two integer columns,
                             -- not one REAL. Combine as (over_number * 6 + ball_in_over) for
                             -- range arithmetic; format "{over_number}.{ball_in_over}" only
                             -- for display. (Previously stored as a single `over REAL`, which
                             -- would silently miscompute over-range filters -- see
                             -- docs/ARCHITECTURE_REVIEW.md H4.)
  event_type TEXT CHECK (event_type IN ('FOUR', 'SIX', 'WICKET', 'FIFTY', 'CENTURY', 'TEAM_MILESTONE')),
  player TEXT,
  team TEXT,
  confidence REAL,          -- 0.0-1.0; see Module 5 "confidence derivation" note above
  importance INTEGER,       -- 0-100
  clip_start_seconds REAL,  -- seconds from match start; NULL until Module 8 (Clip Generator) runs
  clip_end_seconds REAL,    -- seconds from match start; NULL until Module 8 (Clip Generator) runs
  is_replay BOOLEAN,        -- denormalized from `replays` at write time; `replays` is the source of truth
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_events_event_type ON events (event_type);
CREATE INDEX idx_events_player ON events (player);
CREATE INDEX idx_events_team ON events (team);
CREATE INDEX idx_events_over ON events (over_number, ball_in_over);

CREATE TABLE replays (
  replay_id INTEGER PRIMARY KEY,
  start_seconds REAL,
  end_seconds REAL,
  detection_method TEXT CHECK (detection_method IN ('logo', 'scoreboard', 'slowmo')),
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_replays_time_range ON replays (start_seconds, end_seconds);

-- Raw per-second OCR readings: the "Scoreboard Timeline" output listed in PRD Section 6.
-- Event Detection (Module 5) derives events by diffing consecutive rows of this table.
CREATE TABLE scoreboard_readings (
  reading_id INTEGER PRIMARY KEY,
  timestamp_seconds REAL,
  innings INTEGER,
  over_number INTEGER,      -- see events.over_number above -- same integer convention, not REAL
  ball_in_over INTEGER,
  runs INTEGER,
  wickets INTEGER,
  batter TEXT,
  non_striker TEXT,
  bowler TEXT,
  run_rate REAL,
  raw_text TEXT,             -- unparsed OCR output, kept for debugging OCR accuracy against the >=95% target
  ocr_confidence REAL,       -- 0.0-1.0; Tesseract's character-recognition confidence
  parse_confidence REAL,     -- 0.0-1.0; confidence the raw text parsed into a valid, cricket-rule-consistent reading
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_scoreboard_readings_timestamp ON scoreboard_readings (timestamp_seconds);
```

## Cross-Cutting Concern: Module Observability & Diagnostics

Every pipeline module (Video Loader, Scene Detection, Replay Detection, Scoreboard OCR, Event Detection, Fielding Detection, Event Ranking, Clip Generator, Video Stitcher) MUST emit a standardized execution diagnostics record for each invocation, as structured (machine-parseable) log output. This formalizes constitution Principle VI's existing mandate ("MUST produce detailed logging for every stage") into one consistent schema across the whole pipeline, rather than leaving each module to invent its own logging shape.

**Record shape** (see `specs/001-video-loader/data-model.md` `ExecutionDiagnostics` for the first concrete implementation):

| Field | Meaning |
|---|---|
| Module Name | Which pipeline module produced this record |
| Start Time | When the module's invocation began |
| End Time | When it ended (success or failure) |
| Execution Duration | End minus start, provided directly for convenience |
| Peak Memory Usage | Peak memory attributable to the invocation |
| Input Summary | A brief, module-specific description of what was processed |
| Output Summary | A brief, module-specific description of what was produced (on success) |
| Warnings | Any non-fatal issues noticed during execution |
| Failure Reason | Populated when the invocation failed; matches that module's own failure taxonomy |

**Rationale**: Beyond satisfying Principle VI (Fail Fast, Never Silently), a consistent diagnostics shape across all nine modules is what makes future cross-module performance reporting possible — e.g., answering "which stage is eating the 40-minute budget for this match" requires every stage to report timing and memory the same way, not module-by-module ad hoc logging.

**Implementation**: A shared emitter lives at `src/cvip/common/diagnostics.py` (introduced by the Video Loader feature, `specs/001-video-loader/`) so every module reuses one implementation instead of duplicating logging logic. Diagnostics records are written to structured logs (not the SQLite event database, which is reserved for cricket match events per PRD Section 9) — see `specs/001-video-loader/research.md` for the rationale behind that separation.

## Cross-Cutting Concern: Golden Dataset & Accuracy Verification

Constitution Principle IV and PRD Section 18 mandate ≥95% detection accuracy (fours/sixes/wickets) and ≥90% replay-removal accuracy as **MUST** requirements. Neither is measurable without a human-labeled reference match to compare pipeline output against — no amount of unit/contract/integration testing (which check *behavior*, not *accuracy against real broadcast footage*) can verify these numbers.

**Decision**:
- Maintain at least one "golden" match recording (a real or representative broadcast) with a hand-annotated ground-truth list of every four, six, wicket, and replay segment (timestamp + type), checked into `tests/fixtures/golden/` (large video file itself stored outside git, per `.gitignore`'s `*.mp4`/`*.mkv` rules — document the retrieval location separately once one exists).
- A `tests/golden/` test category runs the full `cvip analyze` pipeline against this recording and computes: (detected events matching ground truth within a small time tolerance) / (total ground-truth events) for accuracy, and (replay seconds correctly excluded) / (total replay seconds) for replay removal — asserting both meet their constitutional thresholds.
- This category has a long lead time (sourcing and annotating a real match takes real effort) and should be started in parallel with Module 3/4/5 development, not treated as a final-polish step — by the time Event Detection (Module 5) is implementable, this dataset should already exist so its accuracy claim can be checked immediately, not assumed.
- Annotation format and tooling are not yet decided — this is a follow-up decision, not resolved by this note. What *is* decided is that this category must exist before any claim of constitution Principle IV compliance is made.

## Performance Targets

[PRD Section 15]

- **Processing Time:** ≤40 minutes for 3-hour match
- **Memory Usage:** <6 GB peak
- **CPU:** No GPU required
- **Hardware:** Intel i3-1115G4, 8GB RAM
- **Highlight Gen:** <2 minutes (after analysis)

**Per-module rough budget** (for a 3.5-hour match; illustrative estimates to sanity-check the 40-minute total on paper, not measured benchmarks — replace each row with real numbers as each module gets implemented and benchmarked per its own `tests/benchmark/`):

| Module | Rough estimate | Basis |
|---|---|---|
| 1. Video Loader | ≤10s | SC-001, already measured-and-gated (`specs/001-video-loader/`) |
| 1a. Frame Extraction Service | ~3-5 min | Seeking to ~12,600 sampled frames (1 FPS × 3.5h) for OCR's rate. Scene Detection's likely denser/full-frame need is priced into Module 2's own row below as its own independent pass — no shared decode pass in v1 (decided, see Module 1a above), so this is not double-counted |
| 2. Scene Detection | ~10-20 min | PySceneDetect content-aware detection over the full video |
| 3. Replay Detection | ~2-5 min | Runs against the same sampled frames as 1a, not the full video |
| 4. Scoreboard OCR | **~15-25 min** | ~12,600 Tesseract calls, one per sampled frame — **the single largest cost in the entire budget by a wide margin** |
| 4a. OCR Timeline Smoother | <1 min | Pure data processing over ~12,600 rows |
| 5. Event Detection | <1 min | Diffing ~12,600 rows |
| **Analyze total** | **~31-52 min** | **Rounds to at-risk-or-over the 40-minute budget on the high end, driven almost entirely by Module 4** |
| 8+9. Clip Generator + Video Stitcher (`generate`, separate budget) | <2 min | FFmpeg stream-copy (no re-encode); PRD's own Phase 2 target |

**This is the concrete version of `docs/RISK_REGISTER.md` R3** — the vague "may exceed the 40-minute target" risk has a specific, identifiable cause: Module 4's naive one-Tesseract-call-per-second approach. Before Module 4 is spec'd, evaluate mitigations beyond R3's existing list (crop-before-OCR, sample at 1 FPS): batching/parallelizing Tesseract calls across CPU cores, skipping OCR on frames Module 1a/3 can cheaply determine are unchanged from the previous sample (e.g., via a fast perceptual hash of just the scoreboard ROI), or reducing OCR frequency below 1 FPS with the Smoother (4a) covering the gaps. Do not treat the 1 FPS default in `config/default.yaml` as fixed until this is validated against a real benchmark.

## Non-Negotiables

- Offline only — no network/cloud calls (constitution Principle I)
- CPU only — no GPU dependency (constitution Principle II)
- A 3-hour match is processed in ≤40 minutes, peak memory <6GB (constitution Principle II; restates Performance Targets above)
- No OCR, replay detection, or other analysis/AI work occurs during highlight generation (Phase 2) — Phase 2 only queries the already-built Event Database and stitches clips (PRD Section 6; constitution Principle III, Single-Pass Analysis)

## Deferred Until Later (Post-MVP)

- Advanced fielding detection (Module 6) — see [docs/RISK_REGISTER.md](../docs/RISK_REGISTER.md) R4
- Full UI (Interactive Timeline, Search UI, Analytics dashboard) — see [specs/features.md](./features.md) V2 Features
- Player timeline enrichment
- Advanced broadcast-event detection: DRS Review, Hawkeye, Ultra Edge (PRD Section 8)
- **"Cloud Acceleration" (PRD Section 17) is deferred indefinitely, not just post-MVP**: it directly conflicts with the ratified constitution Principle I (Offline-First, Always — "MUST NOT introduce cloud dependencies... at runtime"). It cannot be built under the current constitution without an explicit amendment (via `/speckit-constitution`) carving out an opt-in, never-required cloud mode. Treat this PRD line as long-term vision that requires a governance decision first, not an engineering backlog item.

## Success Metrics

[PRD Section 18]

✅ Event detection ≥95%
✅ Replay removal ≥90%
✅ Complete processing ≤40 min
✅ Memory <6GB
✅ Run offline, CPU-only
