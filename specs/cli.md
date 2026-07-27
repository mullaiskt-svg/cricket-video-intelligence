# CVIP CLI Specification

## Purpose

The CVIP CLI provides offline commands for analyzing cricket match videos once and generating multiple highlight videos from the stored event database.

The CLI must preserve the two-phase architecture:

1. Analyze the match once.
2. Generate highlights many times without rerunning OCR, replay detection, or AI/video analysis.

**Template implementation status**: This spec documents the full `--template` surface (`match`, `player`, `team`, `custom`) as the intended command shape, but per [specs/features.md](./features.md) only `match` is MVP scope — `player`, `team`, and `custom` are V1.5. The `generate` command MUST accept all four values at the argument-parsing level (so the interface doesn't need to change later), but for MVP MUST reject `player`/`team`/`custom` with a clear "not yet implemented — planned for V1.5" error rather than attempting to run them or crashing unhandled.

**Player/team matching**: `--player`/`--team` match **exactly** (case-sensitive, exact string) against the `player`/`team` values Module 4's OCR wrote to the database — there is no fuzzy matching, alias table, or player-roster normalization in MVP or V1.5. This is a known limitation, not an oversight: OCR misreads or naming variants (e.g., "V Kohli" vs. "Virat Kohli") will cause a filter to silently return zero clips rather than fail loudly. Use `cvip inspect-db` to see the exact strings a given match's database actually contains before filtering by them.

## Command Overview

```bash
cvip analyze input_video.mp4 --config config/default.yaml
cvip generate match_id --template match --output output/match_highlights.mp4
cvip generate match_id --template player --player "Virat Kohli" --output output/player.mp4
cvip export-timeline match_id --format json --output output/timeline.json
cvip inspect-db data/matches/match_id.sqlite
```

---

## 1. Analyze Match

```bash
cvip analyze input_video.mp4 --config config/default.yaml
```

### Description

Runs the full one-time match analysis pipeline.

This command may perform:

- Video metadata extraction
- Frame sampling
- Scene detection
- Replay detection
- Scoreboard OCR
- Event detection
- Event ranking
- Event database creation
- Timeline export

### Required Input

- Path to an MP4 or MKV cricket broadcast.

### Optional Arguments

```bash
--config config/default.yaml
--output-db data/matches/match_id.sqlite
--timeline output/timeline.json
--debug-crops output/debug/scoreboard_crops
--force
```

If `--output-db` is omitted, the database filename defaults to the first 12 hex characters of the Video Loader's `file_hash` (FR-014) — e.g. `data/matches/a1b2c3d4e5f6.sqlite` — so that re-running `analyze` on the exact same file is a simple, registry-free file-existence check (see `specs/technical_plan.md`'s `matches` table). Supplying a friendly `--output-db` name instead (as in the examples throughout this document) is supported, but duplicate-analysis detection then requires scanning existing databases' `file_hash` columns rather than a filename check — see the Database Schema note on this tradeoff.

### Outputs

- SQLite event database
- Timeline JSON
- Replay index
- Scoreboard timeline
- Analysis logs

### Rules

- Must run fully offline.
- Must not require a GPU.
- Must fail fast if FFmpeg or Tesseract is missing.
- Must persist enough data to avoid reprocessing the same video.
- Must attach confidence scores to detected events.

---

## 2. Generate Highlights (MVP)

```bash
cvip generate match_id --template match --output output/match_highlights.mp4
```

### Description

Generates a highlight video from previously analyzed event data.

This command must read from the event database and must not rerun expensive analysis.

### Required Input

- Match ID or path to match database.
- Highlight template name.
- Output path.

### Optional Arguments

```bash
--template match
--output output/match_highlights.mp4
--include-replays
--min-importance 70
--max-duration 900
--start-over 0
--end-over 20
--team India
--player "Virat Kohli"
--event-type SIX
```

`--start-over`/`--end-over` are whole-over integers (e.g., `--start-over 15 --end-over 20` means "overs 15 through 20"), not decimals — cricket's "over.ball" notation (e.g. "18.4") is not a real number, so the database stores `over_number`/`ball_in_over` as separate integers (see `specs/technical_plan.md` Database Schema) and this filter only operates at over granularity, not ball granularity.

### Outputs

- Final MP4 highlight video
- Optional clip manifest JSON

### Rules

- Must not run OCR.
- Must not run replay detection.
- Must not reprocess the source video.
- Must use stored event data.
- Must merge overlapping clips.
- Must avoid duplicate clips.
- Must preserve original resolution where possible.

---

## 3. Generate Player Highlights (V1.5)

```bash
cvip generate match_id --template player --player "Virat Kohli" --output output/player.mp4
```

### Description

Generates highlights for a selected player.

### Required Arguments

```bash
--template player
--player "Player Name"
--output output/player.mp4
```

### Optional Arguments

```bash
--batting
--bowling
--fielding
--complete
--include-replays
--min-importance 60
```

### Example

```bash
cvip generate match_001 --template player --player "Virat Kohli" --batting --output output/kohli_batting.mp4
```

---

## 4. Generate Team Highlights (V1.5)

```bash
cvip generate match_id --template team --team India --output output/india.mp4
```

### Description

Generates highlights involving a selected team.

### Required Arguments

```bash
--template team
--team India
--output output/india.mp4
```

### Optional Arguments

```bash
--include-replays
--min-importance 70
--event-type WICKET
--event-type SIX
```

---

## 5. Generate Event-Type Highlights (V1.5)

```bash
cvip generate match_id --template custom --event-type SIX --output output/sixes.mp4
```

### Description

Generates highlights for one or more selected event types.

### Examples

```bash
cvip generate match_001 --template custom --event-type SIX --output output/all_sixes.mp4
```


```bash
cvip generate match_001 --template custom --event-type WICKET --event-type FOUR --event-type SIX --output output/key_events.mp4
```

---

## 6. Export Timeline

```bash
cvip export-timeline match_id --format json --output output/timeline.json
```

### Description

Exports the analyzed event timeline for debugging, search, or external tooling.

### Supported Formats

```bash
--format json
--format csv
```

### Outputs

- JSON timeline
- CSV event list

JSON field names use `snake_case` (e.g., `event_type`, `clip_start_seconds`), matching the database schema — not the `camelCase` used in the PRD's illustrative event example (PRD Section 9), which is documentation-only, not a field-naming mandate.

### Example

```bash
cvip export-timeline match_001 --format json --output output/match_001_timeline.json
```

---

## 7. Inspect Database

```bash
cvip inspect-db data/matches/match_id.sqlite
```

### Description

Prints summary information about an analyzed match database.

### Output Should Include

- Match ID
- Source video path
- Duration
- FPS
- Resolution
- Analysis timestamp
- Number of scoreboard samples
- Number of detected events
- Number of replay segments
- Event counts by type
- Average confidence by event type

### Example

```bash
cvip inspect-db data/matches/match_001.sqlite
```

---

## 8. Validate Environment

```bash
cvip doctor
```

### Description

Checks whether the local machine has the required runtime dependencies.

### Checks

- Python version
- FFmpeg availability
- Tesseract availability
- Required Python packages
- Writable data/output/log directories
- Offline-safe configuration

### Example Output

```text
CVIP Environment Check

Python: OK
FFmpeg: OK
Tesseract: OK
SQLite: OK
Data directory: OK
Output directory: OK
Logs directory: OK
Network runtime dependencies: None

Status: OK
```

---

## 9. Recommended Exit Codes

| Code | Meaning |
| ---- | ------- |
| 0 | Success |
| 1 | General failure |
| 2 | Invalid CLI arguments |
| 3 | Missing input file |
| 4 | Unsupported video format |
| 5 | Missing native dependency |
| 6 | OCR failure |
| 7 | Database failure |
| 8 | FFmpeg export failure |
| 9 | Analysis already exists and `--force` was not used |

---

## 10. Example MVP Workflow

```bash
cvip doctor
```


```bash
cvip analyze samples/match.mp4 --config config/default.yaml --output-db data/matches/match_001.sqlite
```


```bash
cvip inspect-db data/matches/match_001.sqlite
```


```bash
cvip export-timeline match_001 --format json --output output/match_001_timeline.json
```


```bash
cvip generate match_001 --template match --output output/match_001_highlights.mp4
```

---

## 11. Non-Goals for MVP CLI

The MVP CLI does not need to include:

- GUI controls
- Cloud upload
- Online model calls
- Automatic player face recognition
- Advanced fielding classification
- Commentary/audio analysis
- Live match processing

---

## 12. CLI Design Rules

- Commands must be deterministic.
- Commands must work offline.
- Commands must log each pipeline stage.
- Commands must fail fast with actionable errors.
- Highlight generation must never rerun match analysis.
- Every generated output should be reproducible from the event database and source video.
