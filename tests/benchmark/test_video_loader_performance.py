"""Performance test for Video Loader: SC-001 (<=10s) and SC-005 (<=200MB)
against the multi-hour synthetic fixture. See quickstart.md Scenario 3.
"""

import time
from pathlib import Path

import psutil
import pytest

from cvip.video.loader import load_video
from cvip.video.models import LoadStatus

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "video_loader"
SC_001_MAX_SECONDS = 10.0
SC_005_MAX_MEMORY_MB = 200.0


def test_load_video_meets_sc001_and_sc005_on_multi_hour_fixture():
    path = FIXTURES_DIR / "multi_hour.mp4"
    if not path.exists():
        pytest.skip(
            "multi_hour.mp4 fixture not found -- run "
            "`python tests/fixtures/video_loader/generate_fixtures.py` first."
        )

    process = psutil.Process()
    baseline_mb = process.memory_info().rss / (1024 * 1024)

    start = time.perf_counter()
    result = load_video(str(path))
    elapsed = time.perf_counter() - start

    peak_mb = process.memory_info().rss / (1024 * 1024)
    attributable_mb = peak_mb - baseline_mb

    assert result.status == LoadStatus.SUCCESS
    assert elapsed <= SC_001_MAX_SECONDS, (
        f"load_video() took {elapsed:.2f}s, exceeding the SC-001 {SC_001_MAX_SECONDS}s budget"
    )
    assert attributable_mb <= SC_005_MAX_MEMORY_MB, (
        f"load_video() attributable memory {attributable_mb:.1f}MB exceeds the "
        f"SC-005 {SC_005_MAX_MEMORY_MB}MB budget"
    )
    # Confirm this is genuinely a multi-hour file, not accidentally a short one.
    assert result.source.duration_seconds > 3600
