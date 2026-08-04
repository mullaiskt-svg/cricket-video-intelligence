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

**Confirmed, third distinct format found (second independent match, WILD WANDERERS VS PHOENIX FIREHAWKS.mp4, 4K/vp9)**: neither the original `GenericBroadcastParser` nor `ClubBroadcastParser` (`specs/011-club-broadcast-overlay-support/`) recognizes this broadcast's overlay — `runs`/`wickets` came back `None` on every sampled reading (verified against a raw-OCR dump of a 30s sample). Visually, the score (`12-0`) and the over/ball/total token (`1.0 (20)`) are two separate on-screen tokens (not compound-joined like the club format's `0-0/0.0(20)`), and the score itself uses a hyphen separator rather than either previously-handled convention. This is exactly the "a third, still-different overlay style" case `specs/011-club-broadcast-overlay-support/spec.md`'s own Edge Cases section already anticipated falling through to `PLAYER_PARSE_FAILED`/unparsed-numeric-fields — confirmed here to also mean **zero usable score data and therefore zero detectable Event Detection output** from this broadcast as things stand. Not yet scoped as a spec; would be comparable effort to specs/011's own amendment.

**Resolved, third format now recognized (`SeparateTokenBroadcastParser`, `specs/005-scoreboard-ocr/spec.md`'s Parser Extension Architecture amendment, PR #13)**: the "zero usable score data" finding above no longer holds. `SeparateTokenBroadcastParser` recognizes this exact token shape (bare hyphen-separated score, separate over/ball + total-overs tokens) and, after three further rounds of real-frame-driven OCR-recovery fixes on top of it (regex noise tolerance; fused over.ball/total-overs token recovery; bare-sibling-paren recovery — all in the same spec amendment), accounts for 46.5% of raw samples on this same match (up from 0%). This risk is *downgraded, not closed*: `generic_broadcast` (unparsed) still accounts for the majority of samples (51.2%), and a full real-match re-run found that raw-yield improvement alone did **not** move end-to-end recall against ground truth (flat at 14.0%) — see spec 005's "Combined End-to-End Impact" section for the honest before/after numbers. OCR extraction remains this platform's dominant, isolated pipeline bottleneck; treat this specific "third format" sub-risk as addressed, but the broader R1 risk as still active.

**Accepted ceiling, ground-truth-anchored root cause complete (`ground_truth_v2/`, 2026-08-04)**: a fourth investigation round pivoted from evenly-spread sampling (three rounds, diminishing returns — see above) to anchoring directly on the 57 known ground-truth event timestamps. Result: **signal is present near essentially every real event (0/48 misses have no nearby OCR reading at all)** — the "OCR never captures the moment" framing behind all three prior rounds was wrong. Tracing all 48 misses through the real `detect_state_transitions()`/anomaly-guardrail logic isolated two dominant, structural causes: (1) large multi-over gaps between validated readings collapse several real deliveries into one bracketing state-transition comparison (18/48); (2) a single severely-corrupted 45-minute reading span correctly triggers the anomaly guardrail and discards 10 real events bracketed around it. A follow-up visual finding (a second-innings "TARGET" chase overlay + a distinct "EXTRAS/OVERS/TOTAL" stats card, neither recognized by any current parser, causing digit misreads and per-frame score/over fragmentation) was confirmed real but **scoped and found narrow** — only ~1/48 misses are attributable to it, so no parser work was done for it. **Decision: recall (~14.0%) on this match is accepted as a structural ceiling, not pursued further for now.** Closing the two dominant causes would require an architecture change (denser OCR sampling/frequency, not another parser fix) — worth its own dedicated spec if OCR work resumes, not a quick follow-up.

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

**Confirmed, severely worse at 4K (second independent match, WILD WANDERERS VS PHOENIX FIREHAWKS.mp4, 3840x2160/vp9, 3h10m)**: a full end-to-end pipeline run against this video was attempted and had to be killed after Scene Detection alone ran for **~10 hours without finishing** (a 3-4 hour match is expected to complete the *entire* pipeline in 40 minutes). A controlled 60-second benchmark clip (re-encoded to `h264`, isolating resolution from the `vp9`-vs-`h264` codec question) measured **958.4s of processing for 60s of video -- 1.88 fps**, a ~13.6x slowdown versus the 25.6 fps measured on 720p footage above. This is worse than the ~9x pixel-count ratio (3840x2160 vs 1280x720) alone would predict, suggesting `AdaptiveDetector`'s own per-frame cost (or `cv2.absdiff`'s) scales worse than linearly with resolution, not just proportionally. **The platform as currently implemented cannot process 4K source material within the constitution's performance budget, or arguably within any practical budget** -- no fix attempted; this needs either a documented resolution ceiling/rejection, a downsampling step before Scene Detection, or its own dedicated investigation before 4K sources can be considered supported.

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
