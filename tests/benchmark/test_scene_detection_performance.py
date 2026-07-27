"""Performance tests for Scene Detection: SC-003 (time budget) and SC-004
(memory). See quickstart.md Scenario 3.
"""

import time
from pathlib import Path

import psutil
import pytest

from cvip.video.loader import load_video
from cvip.video.models import LoadStatus
from cvip.video.scene_detection import detect_scenes
from cvip.video.scene_detection_models import SceneDetectionRequest

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "video_loader"
SC_003_MAX_SECONDS = 20 * 60  # upper bound of the documented ~10-20 minute budget
SC_004_MAX_TOLERANCE_RATIO = 0.20  # peak memory for the long clip vs. the short one


def _require_fixture(name: str) -> Path:
    path = FIXTURES_DIR / name
    if not path.exists():
        pytest.skip(
            f"Fixture {name} not found -- run "
            "`python tests/fixtures/video_loader/generate_fixtures.py` first."
        )
    return path


def test_detection_against_multi_hour_fixture_completes_within_budget():
    path = _require_fixture("multi_hour.mp4")
    load_result = load_video(str(path))
    assert load_result.status == LoadStatus.SUCCESS

    request = SceneDetectionRequest(load_result=load_result, scene_threshold=27.0)

    start = time.perf_counter()
    with detect_scenes(request) as detector:
        detector.run()
    elapsed = time.perf_counter() - start

    assert elapsed <= SC_003_MAX_SECONDS, (
        f"detection took {elapsed:.1f}s, over the {SC_003_MAX_SECONDS}s budget ceiling"
    )


def _peak_memory_for_detection(fixture_name: str) -> float:
    path = _require_fixture(fixture_name)
    load_result = load_video(str(path))
    assert load_result.status == LoadStatus.SUCCESS

    process = psutil.Process()
    baseline_mb = process.memory_info().rss / (1024 * 1024)

    request = SceneDetectionRequest(load_result=load_result, scene_threshold=27.0)
    with detect_scenes(request) as detector:
        detector.run()

    peak_mb = process.memory_info().rss / (1024 * 1024)
    return peak_mb - baseline_mb


def test_peak_memory_does_not_scale_with_duration():
    short_mb = max(_peak_memory_for_detection("valid_short.mp4"), 1.0)
    multi_hour_mb = _peak_memory_for_detection("multi_hour.mp4")

    ratio_increase = (multi_hour_mb - short_mb) / short_mb
    assert ratio_increase <= SC_004_MAX_TOLERANCE_RATIO or multi_hour_mb <= 50.0, (
        f"multi-hour detection used {multi_hour_mb:.1f}MB vs {short_mb:.1f}MB for the short "
        f"clip ({ratio_increase:.0%} increase) -- memory appears to scale with duration"
    )
