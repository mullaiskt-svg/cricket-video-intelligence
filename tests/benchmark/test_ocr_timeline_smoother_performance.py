"""Benchmark test for the OCR Timeline Smoother: SC-008 (<1 minute for a
full match's ~12,600 samples). Deselected by default -- run explicitly with
`pytest -m benchmark` (see pyproject.toml).
"""

import time

import pytest

from cvip.video.ocr_timeline_smoother import smooth_timeline
from cvip.video.ocr_timeline_smoother_models import OCRTimelineSmootherRequest
from cvip.video.scoreboard_ocr_models import ScoreboardOcrResult, ScoreboardSample

pytestmark = pytest.mark.benchmark

TOTAL_SAMPLES = 12_600  # ~3.5 hours at 1 sample/second (technical_plan.md)
BUDGET_SECONDS = 60.0


def _synthetic_samples(total: int):
    samples = []
    for i in range(total):
        if i % 97 == 0:  # occasional unusable stretch to exercise gap-fill
            samples.append(
                ScoreboardSample(
                    timestamp_seconds=float(i),
                    runs=None,
                    wickets=None,
                    over_number=None,
                    ball_in_over=None,
                    batter=None,
                    non_striker=None,
                    bowler=None,
                    run_rate=None,
                    raw_text="",
                    ocr_confidence=0.0,
                    parse_confidence=0.0,
                )
            )
            continue
        over_number = i // 6
        ball_in_over = (i % 6) + 1
        samples.append(
            ScoreboardSample(
                timestamp_seconds=float(i),
                runs=min(i // 4, 400),
                wickets=min(i // 500, 10),
                over_number=over_number,
                ball_in_over=ball_in_over,
                batter="Smith*",
                non_striker="Jones",
                bowler="Patel",
                run_rate=round(min(i // 4, 400) / max(over_number, 1), 2),
                raw_text="",
                ocr_confidence=1.0,
                parse_confidence=1.0,
            )
        )
    return samples


def test_smoothing_a_full_match_completes_within_one_minute():
    samples = _synthetic_samples(TOTAL_SAMPLES)
    result_container = ScoreboardOcrResult(
        source_video_id="deadbeef", samples=tuple(samples), total_samples=len(samples)
    )
    request = OCRTimelineSmootherRequest(scoreboard_ocr_result=result_container, outlier_window=2)

    start = time.perf_counter()
    with smooth_timeline(request) as runner:
        result = runner.run()
    elapsed = time.perf_counter() - start

    assert result.total_samples == TOTAL_SAMPLES
    assert elapsed < BUDGET_SECONDS, f"smoothing took {elapsed:.1f}s, over the {BUDGET_SECONDS}s budget (SC-008)"
