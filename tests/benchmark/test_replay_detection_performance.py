"""Performance tests for Replay Detection: SC-004 (time budget). See
quickstart.md Scenario 3.
"""

import time
from pathlib import Path

import pytest

from cvip.video.loader import load_video
from cvip.video.models import LoadStatus
from cvip.video.replay_detection import detect_replays
from cvip.video.replay_detection_models import ReplayDetectionRequest
from cvip.video.scene_detection import detect_scenes
from cvip.video.scene_detection_models import SceneDetectionRequest

pytestmark = pytest.mark.benchmark

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "video_loader"

# The platform's documented ~2-5 minute budget share for this module
# (specs/technical_plan.md Performance Targets); use the upper bound as the
# hard ceiling.
SC_004_MAX_SECONDS = 5 * 60

DEFAULT_WEIGHTS = dict(
    logo_weight=0.35,
    scoreboard_weight=0.20,
    motion_weight=0.20,
    transition_weight=0.15,
    camera_angle_weight=0.10,
)


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

    scene_request = SceneDetectionRequest(load_result=load_result, scene_threshold=27.0)
    with detect_scenes(scene_request) as scene_detector:
        scene_result = scene_detector.run()

    request = ReplayDetectionRequest(
        load_result=load_result,
        scene_detection_result=scene_result,
        confidence_threshold=0.65,
        min_segment_seconds=3.0,
        scoreboard_region=(0.0, 0.0, 0.2, 0.1),
        logo_template_path=None,
        **DEFAULT_WEIGHTS,
    )

    start = time.perf_counter()
    with detect_replays(request) as detector:
        detector.run()
    elapsed = time.perf_counter() - start

    assert elapsed <= SC_004_MAX_SECONDS, (
        f"detection took {elapsed:.1f}s, over the {SC_004_MAX_SECONDS}s budget ceiling"
    )
