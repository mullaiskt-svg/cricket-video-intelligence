# Product Requirements Document (PRD)

# Cricket Video Intelligence Platform (CVIP)

**Version:** 1.0  
**Status:** Draft  
**Target Platform:** Windows Desktop (Offline)  
**Primary Language:** Python 3.11+

---

# 1. Vision

Develop an offline AI-powered **Cricket Video Intelligence Platform (CVIP)** that analyzes an entire cricket match broadcast once, builds a structured event database, and allows users to generate multiple customized highlight videos without reprocessing the original video.

Unlike a traditional highlight generator, CVIP should function as a **video intelligence engine**, enabling users to search, filter, analyze, and export cricket moments based on different criteria.

---

# 2. Objectives

The platform should:

- Analyze a cricket match only once.
- Detect and classify important cricket events.
- Automatically remove replay footage.
- Build a searchable event database.
- Generate unlimited highlight videos from the indexed events.
- Execute completely offline.
- Run efficiently on low-end consumer hardware.
- Be modular and extensible for future AI capabilities.

---

# 3. Target Hardware

Minimum Supported Hardware

- Intel Core i3-1115G4
- 8 GB RAM
- Intel UHD Graphics
- Windows 11
- SSD Recommended

The application should **not require a dedicated GPU**.

---

# 4. Constraints

## Input

- MP4 / MKV cricket broadcast
- 3–4 hour duration
- 720p / 1080p
- No audio
- Broadcast contains replay footage
- Live scoreboard visible during gameplay

## Output

Generate one or more highlight videos based on user-selected criteria.

---

# 5. Product Workflow

```text
                Match Video
                     │
                     ▼
         Video Intelligence Engine
                     │
 ┌─────────────────────────────────────┐
 │ Video Processing                    │
 │ Replay Detection                    │
 │ OCR Engine                          │
 │ Event Detection                     │
 │ Event Classification                │
 │ Event Indexing                      │
 └─────────────────────────────────────┘
                     │
                     ▼
          Event Intelligence Database
                     │
     ┌───────────────┼────────────────┐
     │               │                │
     ▼               ▼                ▼
Search UI     Highlight Builder    Analytics
                     │
                     ▼
            Export Highlight Videos
```

---

# 6. Processing Pipeline

## Phase 1 – Match Analysis (One-Time)

Analyze the complete match and build the event database.

Output

- Event Database
- Timeline JSON
- Replay Index
- Scoreboard Timeline
- Player Timeline (Future)

Once completed, this phase should never be executed again for the same match.

---

## Phase 2 – Highlight Generation

Users select the type of highlight they want.

The system retrieves matching clips from the event database and stitches them together.

No OCR, replay detection, or AI processing should occur during this phase.

---

# 7. Functional Modules

## Module 1 – Video Loader

Responsibilities

- Load video
- Read metadata
- Detect FPS
- Detect resolution
- Detect duration

---

## Module 2 – Scene Detection

Responsibilities

- Detect scene changes
- Detect camera transitions
- Detect replay transitions

Technology

- PySceneDetect
- OpenCV

---

## Module 3 – Replay Detection

Automatically identify replay footage.

Detection methods

- Replay logo detection
- Scoreboard disappearance
- Slow-motion detection
- Camera angle changes
- Replay transition animations

Replay segments should be indexed but excluded from generated highlights unless explicitly requested.

---

## Module 4 – Scoreboard OCR

Read the scoreboard once every second.

Extract

- Runs
- Wickets
- Overs
- Batter
- Non-Striker
- Bowler
- Run Rate

OCR Region should be configurable through a configuration file.

---

## Module 5 – Event Detection

Compare consecutive OCR readings.

Detect

- Four
- Six
- Wicket
- Fifty
- Century
- Team Milestones

Store detected events in the event database.

---

## Module 6 – Fielding Detection

Detect visually significant fielding moments.

Examples

- Diving catch
- Running catch
- Boundary save
- Direct hit
- Diving stop
- Excellent throw
- Near run out

Version 1 should use lightweight computer vision heuristics.

Future versions may incorporate AI vision models.

---

## Module 7 – Event Ranking

Assign an importance score to every event.

Example

| Event | Score |
|--------|------:|
| Hat Trick | 100 |
| Match Winning Shot | 100 |
| Century | 95 |
| Wicket | 95 |
| Run Out | 90 |
| Catch | 85 |
| Six | 80 |
| Fifty | 75 |
| Great Fielding | 70 |
| Four | 60 |

These values should be configurable.

---

## Module 8 – Clip Generator

For each event

Default clip

- 8 seconds before event
- 12 seconds after event

Merge overlapping clips.

Avoid duplicate clips.

---

## Module 9 – Video Stitcher

Use FFmpeg to merge clips.

Maintain original resolution.

Avoid unnecessary re-encoding.

Generate MP4 output.

---

# 8. Event Categories

## Batting

- Four
- Six
- Single
- Double
- Triple
- Dot Ball
- Boundary Save
- Fifty
- Century
- Double Century (Future)

---

## Bowling

- Wicket
- Bowled
- LBW
- Caught
- Run Out
- Stumped
- Hit Wicket
- Maiden Over (Future)
- Hat Trick

---

## Fielding

- Diving Catch
- Running Catch
- Boundary Save
- Direct Hit
- Diving Stop
- Relay Throw
- Excellent Throw
- Near Run Out

---

## Match Events

- Toss
- Team Entry
- Innings Start
- Drinks Break
- Strategic Timeout
- Innings Break
- Winning Shot
- Winning Wicket
- Match End
- Celebration
- Trophy Presentation

---

## Broadcast Events

- Replay
- Advertisement
- Ultra Edge
- Hawkeye
- DRS Review

---

# 9. Event Database

Every detected event should be stored.

Example

```json
{
  "eventId": 1456,
  "timestamp": "01:25:42",
  "innings": 2,
  "over": 18.4,
  "eventType": "SIX",
  "player": "Virat Kohli",
  "team": "India",
  "confidence": 0.98,
  "importance": 80,
  "clipStart": "01:25:34",
  "clipEnd": "01:25:54",
  "replay": false
}
```

---

# 10. Highlight Templates

The application should provide predefined highlight templates.

---

## Match Highlights

Include

- Wickets
- Sixes
- Important Fours
- Great Fielding
- Milestones
- Winning Moment
- Celebration

Target Duration

5–15 minutes

---

## Batting Highlights

Options

- Every scoring shot
- Boundaries
- Fours only
- Sixes only
- Milestones

---

## Bowling Highlights

Include

- Wickets
- Near Misses
- Dot Balls
- Best Deliveries

---

## Fielding Highlights

Include

- Catches
- Boundary Saves
- Direct Hits
- Diving Stops
- Relay Throws

---

## Player Highlights

User selects a player.

Examples

- Virat Kohli
- Rohit Sharma
- Jasprit Bumrah

Available options

- Batting
- Bowling
- Fielding
- Complete Match
- Custom

---

## Team Highlights

Generate

- India Highlights
- Australia Highlights

Include only events involving the selected team.

---

## Partnership Highlights

Generate all clips involving two selected batters.

Include

- Boundaries
- Running Between Wickets
- Milestones

---

## Innings Highlights

Generate

- First Innings
- Second Innings

---

## Over Highlights

Generate

- Individual Overs
- Powerplay
- Middle Overs
- Death Overs
- Super Over

---

## Milestones

Generate

- All Fifties
- All Centuries
- Team Milestones
- Partnerships

---

## End of Match

Generate

- Winning Shot
- Winning Wicket
- Team Celebration
- Handshakes
- Trophy Presentation

---

## Custom Highlight Builder

Users should be able to create custom highlight videos.

Selectable filters

### Event Types

- Four
- Six
- Wicket
- Catch
- Run Out
- Fielding
- Celebration

### Players

Single or multiple players.

### Teams

Single or multiple teams.

### Match Phase

- Powerplay
- Middle Overs
- Death Overs

### Innings

- First
- Second

### Over Range

Example

15–20

### Clip Duration

Configure

- Seconds before event
- Seconds after event

### Exclusions

- Replays
- Advertisements
- Dot Balls

---

# 11. Timeline Explorer

After analysis, present an interactive timeline.

Display

- Every detected event
- Replay markers
- Wickets
- Boundaries
- Milestones

Users should be able to

- Click an event
- Preview the clip
- Multi-select events
- Create highlight reels directly from the timeline

---

# 12. Search

Allow searching by

- Player
- Team
- Event Type
- Over
- Innings
- Score
- Time

Examples

- All sixes by Virat Kohli
- All wickets in Powerplay
- All catches by Australia
- Everything between Overs 15–20
- All boundaries after the 40th over

---

# 13. User Interface

Main Menu

- Analyze Match
- Event Timeline
- Search
- Generate Highlights
- Export

Generate Highlights

- Match Highlights
- Player Highlights
- Team Highlights
- Batting Highlights
- Bowling Highlights
- Fielding Highlights
- Innings Highlights
- Over Highlights
- Milestones
- End of Match
- Custom Builder

---

# 14. Outputs

Generate

- Match_Highlights.mp4
- All_Sixes.mp4
- All_Fours.mp4
- All_Wickets.mp4
- Player_Highlights.mp4
- Bowling_Highlights.mp4
- Fielding_Highlights.mp4
- Team_Highlights.mp4
- Powerplay.mp4
- Death_Overs.mp4
- Winning_Moments.mp4
- Custom_Highlights.mp4

Supporting Files

- event_database.db
- timeline.json
- scoreboard.csv
- replay_index.json
- logs/

---

# 15. Performance Requirements

For a 3-hour match

- Processing Time ≤ 40 minutes
- Memory Usage < 6 GB
- CPU Only
- No GPU Required
- Offline Execution

---

# 16. Non-Functional Requirements

- Modular architecture
- Configuration-driven
- Open-source dependencies only
- Offline-first design
- Extensible plugin architecture
- Detailed logging
- Resume interrupted processing
- Cross-platform architecture (Windows first)

---

# 17. Future Enhancements

- Ball Tracking
- Player Recognition
- Jersey Number Recognition
- Shot Classification
- Audio Analysis
- Commentary Understanding
- Multilingual Support
- Live Match Processing
- Cloud Acceleration
- AI-generated Match Summary
- AI-generated Commentary
- Automatic Social Media Reel Generation

---

# 18. Success Criteria

The platform is considered successful if it:

- Detects at least 95% of fours, sixes, and wickets.
- Removes at least 90% of replay footage automatically.
- Generates customized highlight videos without reprocessing the match.
- Produces multiple highlight types from a single event database.
- Processes a 3-hour match within 40 minutes on the target hardware.
- Operates entirely offline using open-source technologies.
- Provides an intuitive interface for searching, filtering, previewing, and exporting cricket highlights.