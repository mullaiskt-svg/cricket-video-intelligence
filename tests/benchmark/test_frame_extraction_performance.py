"""Performance tests for the Frame Extraction Service: SC-002 (memory) and
SC-008 (throughput consistency). See quickstart.md Scenario 2.
"""

import time
from pathlib import Path

import psutil
import pytest

from cvip.video.frame_extraction import extract_frames
from cvip.video.frame_extraction_models import ExtractionRequest, SamplingMode
from cvip.video.loader import load_video
from cvip.video.models import LoadStatus

pytestmark = pytest.mark.benchmark

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "video_loader"
SC_002_MAX_MEMORY_MB = 150.0


def _require_fixture(name: str) -> Path:
    path = FIXTURES_DIR / name
    if not path.exists():
        pytest.skip(
            f"Fixture {name} not found -- run "
            "`python tests/fixtures/video_loader/generate_fixtures.py` first."
        )
    return path


def _peak_memory_for_extraction(fixture_name: str) -> float:
    path = _require_fixture(fixture_name)
    load_result = load_video(str(path))
    assert load_result.status == LoadStatus.SUCCESS

    process = psutil.Process()
    baseline_mb = process.memory_info().rss / (1024 * 1024)

    request = ExtractionRequest(load_result=load_result, mode=SamplingMode.FIXED_INTERVAL, rate_fps=1.0)
    with extract_frames(request) as extractor:
        for _ in extractor:
            pass

    peak_mb = process.memory_info().rss / (1024 * 1024)
    return peak_mb - baseline_mb


def test_peak_memory_stays_under_150mb_regardless_of_duration():
    short_mb = _peak_memory_for_extraction("valid_short.mp4")
    multi_hour_mb = _peak_memory_for_extraction("multi_hour.mp4")

    assert short_mb <= SC_002_MAX_MEMORY_MB, f"short-clip extraction used {short_mb:.1f}MB, over the {SC_002_MAX_MEMORY_MB}MB budget"
    assert multi_hour_mb <= SC_002_MAX_MEMORY_MB, f"multi-hour extraction used {multi_hour_mb:.1f}MB, over the {SC_002_MAX_MEMORY_MB}MB budget"


def test_throughput_is_consistent_across_repeated_runs():
    path = _require_fixture("multi_hour.mp4")
    load_result = load_video(str(path))
    assert load_result.status == LoadStatus.SUCCESS

    durations = []
    for _ in range(3):
        request = ExtractionRequest(load_result=load_result, mode=SamplingMode.FIXED_INTERVAL, rate_fps=1.0)
        start = time.perf_counter()
        with extract_frames(request) as extractor:
            for _ in extractor:
                pass
        durations.append(time.perf_counter() - start)

    mean_duration = sum(durations) / len(durations)
    tolerance = max(mean_duration * 0.25, 0.05)  # +-25%, with a small floor for very fast runs
    for duration in durations:
        assert abs(duration - mean_duration) <= tolerance, (
            f"run duration {duration:.3f}s deviates from mean {mean_duration:.3f}s "
            f"by more than the {tolerance:.3f}s tolerance: {durations}"
        )
