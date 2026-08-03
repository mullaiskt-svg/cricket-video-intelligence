# Quickstart: Club Broadcast Overlay Support

Validates that Scoreboard OCR now produces usable readings from the club-cricket broadcast overlay, without regressing the original format. Two levels: a fast synthetic check (no video/Tesseract needed) and a real-fixture end-to-end check (needs the actual match recording).

## Prerequisites

- Repo checked out on `011-club-broadcast-overlay-support`, `src/cvip/video/scoreboard_ocr.py` amended per plan.md/research.md/data-model.md.
- `pip install -r requirements.txt` (Tesseract + `pytesseract`, already a documented prerequisite — `docs/DEPENDENCIES.md`).

## 1. Synthetic parser validation (fast, no fixture required)

Exercises `_select_parser()`/`GenericBroadcastParser`/`ClubBroadcastParser` (research.md Decision 5) directly against literal token lists built from this feature's own raw evidence (research.md), without needing OCR or a real video.

```sh
pytest tests/unit/test_scoreboard_ocr_validation.py -k "compound or best_effort or club_broadcast" -v
```

**Expected outcomes**:
- A reading built from tokens equivalent to `["MAHESH", "0", "(0)", "SAI", "KRISHNA", "0(0)", "Chai", "Cricket", "Club", "_0-0/0.0(20)", "BHARATH", "0-0(0)"]` parses to `runs=0, wickets=0, over_number=0, ball_in_over=0, batter="MAHESH", non_striker="SAI KRISHNA", bowler="BHARATH"`, and validates successfully (`parse_confidence > 0`).
- The team-name tokens (`"Chai"`, `"Cricket"`, `"Club"`) are **not** captured into any of `batter`/`non_striker`/`bowler`.
- A reading built from the original format's tokens (e.g. `["123/4", "12.3", "B:", "SMITH", "JONES*"]`) still parses identically to its pre-amendment result — re-run the *existing* (unmodified) test cases in this file and confirm they still pass unchanged.
- A reading with no recognizable name adjacent to any stats-marker still resolves to `batter=None` and `ValidationFailureReason.PLAYER_PARSE_FAILED` (FR-008) — the amendment adds a second successful path, not a more permissive one.

## 2. Full regression suite (proves FR-002 non-regression)

```sh
pytest tests/contract/test_scoreboard_ocr_contract.py tests/unit/test_scoreboard_ocr_validation.py -v
```

**Expected outcome**: every pre-existing test still passes, unmodified, alongside the new cases from step 1.

## 3. Real-fixture end-to-end check (optional, needs the real video)

Requires a short clip of the actual club-broadcast overlay (not committed to the repo — `*.mp4` is gitignored, matching the Video Stitcher fixture precedent). If unavailable, skip this step; steps 1-2 are sufficient to merge.

```sh
python - <<'PY'
from cvip.video.loader import load_video
from cvip.video.frame_extraction import extract_frames
from cvip.video.scoreboard_ocr import extract_scoreboard
from cvip.video.scoreboard_ocr_models import ScoreboardOcrRequest

load_result = load_video("path/to/short_club_broadcast_clip.mp4")
request = ScoreboardOcrRequest(
    load_result=load_result,
    scoreboard_region=(0.05, 0.82, 0.90, 0.15),
    preprocess_grayscale=True,
    preprocess_threshold=True,
    preprocess_upscale=2,
    min_confidence=0.70,
)
with extract_scoreboard(request) as extractor:
    result = extractor.run()

non_null_batter = sum(1 for s in result.samples if s.batter is not None)
print(f"{non_null_batter}/{result.total_samples} samples have a non-null batter")
print(result.samples[0])
PY
```

**Expected outcome**: a majority of samples (matching SC-002's target from spec.md) have non-null `runs`/`wickets`/`over_number`/`ball_in_over` and a non-null `batter`, where before this amendment every sample from this overlay would have had `parse_confidence = 0.0` via `PLAYER_PARSE_FAILED`.

## 4. Downstream check, synthetic (SC-005 — mandatory, no real video needed)

```sh
pytest tests/integration/test_scoreboard_ocr_e2e.py -k "event_detection or sc_005" -v
```

This is tasks.md T034: a deterministic timeline built directly from `ClubBroadcastParser` output (no OCR, no video, no fixture) fed into `detect_events()`, asserting at least one `FOUR`/`SIX`/`WICKET` event is produced. Unlike the analysis-report's original framing, this check is **not optional** — SC-005 is a mandatory success criterion and this is its always-run proof.

## 5. Downstream check, real recording (optional, needs the real video and Event Detection wired up)

If `specs/007-event-detection/` is available in this checkout *and* step 3 ran against the real fixture, feed step 3's `result` into `detect_events()` and confirm at least one `FOUR`/`SIX`/`WICKET` event is detected from the real recording's runs/wickets deltas — proving the amendment actually unblocks the platform's original "shortcut script" goal (generate real highlights from `First8Overs.mp4`), not just that the parser produces prettier intermediate values on synthetic data. This is additive to step 4, not a replacement for it (tasks.md T036).
