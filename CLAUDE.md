# Cricket Video Intelligence Platform (CVIP)

## Project Overview
AI-powered offline cricket match analysis and highlight generation.

## Tech Stack
- Python 3.11+
- OpenCV for video processing
- FFmpeg for video stitching
- PySceneDetect for scene detection
- SQLite for event database
- Windows Desktop (Offline)

## Key Modules
1. Video Loader - Metadata detection
2. Scene Detection - PySceneDetect + OpenCV
3. Replay Detection - Logo/scoreboard detection
4. Scoreboard OCR - Extract match data
5. Event Detection - Batting, bowling, fielding events
6. Event Ranking - Importance scoring
7. Clip Generator - 8s before, 12s after events
8. Video Stitcher - FFmpeg merging

## Performance Target
- Process 3-hour match in ≤40 minutes
- < 6GB memory
- CPU-only (no GPU required)

## Success Criteria
- Detect ≥95% of fours, sixes, wickets
- Remove ≥90% of replay footage
- Run entirely offline

## Reference: Full PRD in /mnt/project/
