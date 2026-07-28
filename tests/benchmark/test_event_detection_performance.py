"""Benchmark test for Event Detection: SC-004 (<1 minute for a full match's
~12,600 cleaned samples). Deselected by default -- run explicitly with
`pytest -m benchmark` (see pyproject.toml).
"""

import time

import pytest

from cvip.events.detection import detect_events
from cvip.events.models import EventDetectionRequest
from cvip.video.ocr_timeline_smoother_models import CleanedScoreboardSample, OCRTimelineSmootherResult
from cvip.video.replay_detection_models import ReplayDetectionResult, ReplaySegment
from cvip.video.scoreboard_ocr_models import ScoreboardOcrResult, ScoreboardSample

pytestmark = pytest.mark.benchmark

TOTAL_SAMPLES = 12_600  # ~3.5 hours at 1 sample/second (technical_plan.md)
BUDGET_SECONDS = 60.0
_RANKING = {"FOUR": 60, "SIX": 80, "WICKET": 95, "TEAM_MILESTONE": 65}


def _synthetic_cleaned_and_raw(total: int):
    cleaned = []
    raw = []
    for i in range(total):
        over_number = i // 6
        ball_in_over = i % 6
        runs = min(i // 2, 400)  # occasional 4s/6s via the modulo pattern below
        wickets = min(i // 600, 9)
        cleaned.append(
            CleanedScoreboardSample(
                timestamp_seconds=float(i),
                runs=runs,
                wickets=wickets,
                over_number=over_number,
                ball_in_over=ball_in_over,
                batter="Smith*",
                non_striker="Jones",
                bowler="Patel",
                run_rate=round(runs / max(over_number, 1), 2),
            )
        )
        raw.append(
            ScoreboardSample(
                timestamp_seconds=float(i),
                runs=runs,
                wickets=wickets,
                over_number=over_number,
                ball_in_over=ball_in_over,
                batter="Smith*",
                non_striker="Jones",
                bowler="Patel",
                run_rate=round(runs / max(over_number, 1), 2),
                raw_text="",
                ocr_confidence=1.0,
                parse_confidence=1.0,
            )
        )
    return cleaned, raw


def test_detecting_events_across_a_full_match_completes_within_one_minute():
    cleaned, raw = _synthetic_cleaned_and_raw(TOTAL_SAMPLES)
    replay_segments = tuple(
        ReplaySegment(replay_id=i, start_seconds=float(i * 500), end_seconds=float(i * 500 + 10), confidence=0.9)
        for i in range(20)
    )

    request = EventDetectionRequest(
        cleaned_timeline=OCRTimelineSmootherResult(
            source_video_id="deadbeef", samples=tuple(cleaned), total_samples=len(cleaned)
        ),
        raw_ocr_result=ScoreboardOcrResult(
            source_video_id="deadbeef", samples=tuple(raw), total_samples=len(raw)
        ),
        replay_result=ReplayDetectionResult(
            source_video_id="deadbeef", segments=replay_segments, total_segments=len(replay_segments)
        ),
        team_milestone_interval=50,
        ranking=_RANKING,
    )

    start = time.perf_counter()
    with detect_events(request) as runner:
        result = runner.run()
    elapsed = time.perf_counter() - start

    assert elapsed < BUDGET_SECONDS, f"detection took {elapsed:.1f}s, over the {BUDGET_SECONDS}s budget (SC-004)"
    assert result.total_events >= 0
