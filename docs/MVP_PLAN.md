# CVIP MVP Plan

## MVP Objective
Build a CLI-based offline pipeline that analyzes one cricket broadcast once, detects core scoreboard-derived events, stores them in SQLite, and exports an MP4 highlight video.

## Phase 1: Foundation
- Create Python package structure
- Add config loader
- Add logging setup
- Add Pydantic models
- Add SQLite schema
- Add CLI skeleton

## Phase 2: Video Processing
- Load MP4/MKV
- Extract metadata
- Hash video file
- Sample frames once per second
- Save optional debug crops

## Phase 3: Scoreboard OCR
- Crop configurable scoreboard region
- Preprocess cropped frame
- Run Tesseract OCR
- Parse runs, wickets, overs, players
- Store raw text and confidence

## Phase 4: Event Detection
- Smooth OCR timeline
- Compare consecutive valid samples
- Detect FOUR, SIX, WICKET, FIFTY, CENTURY
- Assign confidence and importance

## Phase 5: Clip Generation
- Create event clip windows
- Apply 8s pre-roll and 12s post-roll
- Merge overlaps
- Exclude replay segments
- Generate FFmpeg concat list

## Phase 6: Export
- Stitch clips with FFmpeg
- Preserve source resolution
- Avoid re-encoding where possible
- Output MP4

## MVP Acceptance Criteria
- No internet required at runtime
- No GPU required
- No OCR during highlight generation
- Event database is reusable
- Basic tests pass
- Full pipeline works on a short sample video
