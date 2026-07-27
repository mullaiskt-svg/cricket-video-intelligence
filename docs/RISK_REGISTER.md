# CVIP Risk Register

## R1: Scoreboard OCR Reliability
Severity: High
Likelihood: High

Risk:
Different broadcasters use different scoreboard layouts, fonts, colors, overlays, and animations.

Impact:
Incorrect OCR can produce false events or missed events.

Mitigation:
- Configurable scoreboard region
- Per-broadcaster OCR profiles
- OCR confidence tracking
- Timeline smoothing
- Cricket-rule validation
- Manual fixture dataset

## R2: Replay Detection Accuracy
Severity: High
Likelihood: Medium

Risk:
Replay indicators vary by broadcaster and may not always include a visible logo.

Impact:
Generated highlights may include duplicate replay clips or exclude valid live footage.

Mitigation:
- Multi-signal replay confidence score
- Replay timeline stored separately
- User-configurable replay inclusion
- Manual override support

## R3: Performance on Low-End CPU
Severity: High
Likelihood: Medium

Risk:
Full-resolution frame processing and OCR may exceed the 40-minute target.

Impact:
System fails core performance requirement.

Mitigation:
- Sample frames at 1 FPS for OCR
- Crop before OCR
- Avoid full-frame processing when possible
- Cache intermediate artifacts
- Add benchmark suite early

## R4: Fielding Detection Complexity
Severity: Medium
Likelihood: High

Risk:
Fielding events are visually diverse and difficult to detect with simple heuristics.

Impact:
Delayed MVP if implemented too early.

Mitigation:
- Defer advanced fielding detection
- Focus MVP on scoreboard-derived events
- Add fielding as V1.5/V2

## R5: Native Dependency Setup
Severity: Medium
Likelihood: Medium

Risk:
pytesseract and ffmpeg-python require native Tesseract and FFmpeg binaries.

Impact:
Installation may fail even if pip dependencies install successfully.

Mitigation:
- Document native install steps
- Add startup dependency checks
- Fail fast with actionable errors
