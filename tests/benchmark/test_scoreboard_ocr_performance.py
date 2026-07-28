"""Performance tests for Scoreboard OCR: SC-004 (time budget). See
quickstart.md Scenario 3.
"""

import time
from pathlib import Path

import pytest

from cvip.video.loader import load_video
from cvip.video.models import LoadStatus
from cvip.video.scoreboard_ocr import extract_scoreboard
from cvip.video.scoreboard_ocr_models import ScoreboardOcrRequest

pytestmark = pytest.mark.benchmark

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "video_loader"

# The platform's documented ~15-25 minute budget share for this module
# (specs/technical_plan.md Performance Targets); use the upper bound as the
# hard ceiling.
SC_004_MAX_SECONDS = 25 * 60

DEFAULT_REQUEST_KWARGS = dict(
    scoreboard_region=(0.05, 0.82, 0.90, 0.15),
    preprocess_grayscale=True,
    preprocess_threshold=True,
    preprocess_upscale=2,
    min_confidence=0.70,
)


def _require_fixture(name: str) -> Path:
    path = FIXTURES_DIR / name
    if not path.exists():
        pytest.skip(
            f"Fixture {name} not found -- run "
            "`python tests/fixtures/video_loader/generate_fixtures.py` first."
        )
    return path


def test_extraction_against_multi_hour_fixture_completes_within_budget():
    path = _require_fixture("multi_hour.mp4")
    load_result = load_video(str(path))
    assert load_result.status == LoadStatus.SUCCESS

    request = ScoreboardOcrRequest(load_result=load_result, **DEFAULT_REQUEST_KWARGS)

    start = time.perf_counter()
    with extract_scoreboard(request) as extractor:
        extractor.run()
    elapsed = time.perf_counter() - start

    assert elapsed <= SC_004_MAX_SECONDS, (
        f"extraction took {elapsed:.1f}s, over the {SC_004_MAX_SECONDS}s budget ceiling"
    )
