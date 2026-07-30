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

**Confirmed via real-video validation** (`specs/011-club-broadcast-overlay-support/`, against First8Overs.mp4), three compounding problems, one fixed:
1. **Fixed**: `config/default.yaml`'s original weights (`logo=0.35`) plus `confidence_threshold=0.65` left a maximum achievable combined confidence of 0.50-0.65 depending on scenario whenever no logo template is configured (the common case) and Scene Detection's `REPLAY_TRANSITION` heuristic doesn't fire (e.g. a hard, non-ramping cut) — detection was mathematically unreachable, not merely insensitive. Weights rebalanced (`logo=0.15, scoreboard=0.25, motion=0.25, transition=0.20, camera_angle=0.15`), threshold lowered to `0.50` — see `config/default.yaml`'s own comment and `specs/004-replay-detection/spec.md`'s Assumptions.
2. **Fixed**: Scene Detection's `ContentDetector` (a single fixed cut-score threshold, `scene_threshold=27.0` — PySceneDetect's own generic library default, never validated against real footage) could not be made to work at all: the content-difference score's own scale varies enormously within one match (~5.7 max during calm pre-match footage vs. ~95-97 during active play), so no single fixed number was simultaneously correct for both regimes. Replaced with PySceneDetect's `AdaptiveDetector` (a rolling, self-normalizing comparison against each frame's own neighborhood, not a global constant) — `scene_threshold` now maps to its `min_content_val` noise floor, recalibrated `27.0` → `8.0`; the ratio parameter (`adaptive_threshold`) stays at PySceneDetect's own published default. Validated across 7 real-footage scenarios (opening, early/middle/death overs, innings transition, a known wicket/replay window, camera-movement contrast) — see `specs/003-scene-detection/spec.md` Assumptions for the full rationale, including why automatic per-video calibration was evaluated and deliberately deferred rather than built speculatively.
3. **Still open, secondary**: the Live-Action Baseline Tracker needs 3 prior confirmed-live segments before it stops returning neutral (0.5) placeholder scores for scoreboard/motion/camera-angle deviation. Boundaries are now far more numerous (0-13 per 3-minute sample, vs. 1-3 per 15 minutes before), which should let the baseline warm up much sooner in practice — but this has not been independently re-verified end-to-end (i.e., re-running Replay Detection itself against the new, denser Scene Detection output to confirm a real replay segment now gets correctly flagged). Worth confirming before considering R2 fully closed.

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

**Confirmed, partially fixed (real-video validation, `specs/011-club-broadcast-overlay-support/`)**: Scene Detection (Module 2) uses `SamplingMode.FULL` (every frame at native rate, not 1 FPS) and was measured at 7.5 fps on real 720p/30fps footage — ~159 minutes extrapolated for a single 40-minute match, before any other pipeline stage. Root cause: the Frame Extraction Service's `_retrieve_frame()` re-seeked (`cap.set(CAP_PROP_POS_FRAMES, ...)`) before every read, even for consecutive frames -- invisible to Scene Detection's own benchmark, which uses a synthetic 320x240/10fps solid-black fixture (`multi_hour.mp4`) that doesn't exercise real seek/decode cost. Fixed in `src/cvip/video/frame_extraction.py` by skipping the redundant seek for sequential reads: 3.4x improvement (7.5 -> 25.6 fps), extrapolated full-match time down to ~46.5 minutes for Scene Detection alone. **Still likely over the 40-minute whole-pipeline budget on its own** -- the remaining per-frame cost (PySceneDetect's `ContentDetector`, or native H.264 decode cost at full frame rate) was not further profiled; needs its own follow-up investigation before this risk can be considered closed. Also flagged: **benchmark fixtures across this codebase should be checked for the same synthetic-content blind spot** (cheap-to-decode, low-res/low-motion content passing a time budget that real broadcast footage would not).

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
