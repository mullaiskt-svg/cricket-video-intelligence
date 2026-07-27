# CVIP Feature Specification

## MVP Features

*(Match Analysis + Highlight Generation, per PRD Sections 6-9, 15, 18 — see [docs/MVP_PLAN.md](../docs/MVP_PLAN.md) for phase breakdown)*

**User Story:** As an analyst, I want to analyze a cricket match once and build a searchable event database.
**User Story:** As a viewer, I want to generate a highlight video from the database without reprocessing the match.

- Load MP4/MKV cricket broadcast (720p/1080p, 3-4 hours) [PRD Section 4]
- Extract video metadata
- Scene detection (camera/replay transitions) [PRD Module 2]
- Replay detection and exclusion — target ≥90% replay removal [PRD Module 3, Section 18]
- Sample scoreboard region once per second [PRD Module 4]
- OCR scoreboard text (runs, wickets, overs, batter, bowler) [PRD Module 4]
- Detect score deltas
- Detect fours, sixes, wickets, fifties, centuries — target ≥95% accuracy [PRD Section 18]
- Assign event importance score (0-100) [PRD Module 7]
- Store events (with confidence and importance) in SQLite [PRD Section 9]
- Generate clips with 8s pre-roll and 12s post-roll; merge overlapping clips [PRD Module 8]
- Export MP4 highlights with FFmpeg — no re-encoding, original resolution preserved [PRD Module 9]

**Performance targets** [PRD Section 15]: analysis completes in ≤40 min, highlight generation in <2 min, on target hardware, fully offline, no GPU.

## V1.5 Features

- Replay confidence scoring — multi-signal, beyond MVP's basic replay detection (see [docs/RISK_REGISTER.md](../docs/RISK_REGISTER.md) R2)
- Support 10+ highlight templates: Match, Player, Team, Batting, Bowling, Fielding, Innings, Over, Milestones, End of Match [PRD Section 10]
- Custom filter JSON (event type, player, team, over range) [PRD Section 12]

## V2 Features

**User Story:** As an analyst, I want to browse and search all events.

- Fielding detection (diving catches, boundary saves, direct hits, etc.) [PRD Module 6; deferred per [docs/RISK_REGISTER.md](../docs/RISK_REGISTER.md) R4]
- Interactive Timeline: display every detected event, click to preview a clip, multi-select for custom reels, show confidence scores [PRD Section 11]
- Search UI: search by player, team, event type, over, innings, score, time [PRD Section 12]
- Analytics dashboard
- Advanced broadcast-event detection (Ultra Edge, Hawkeye, DRS Review, etc.) [PRD Section 8]
