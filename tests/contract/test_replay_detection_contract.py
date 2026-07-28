"""Contract tests for the Replay Detection module boundary.

Asserts `detect_replays()` matches the shape defined in
specs/004-replay-detection/contracts/replay_detection_contract.md -- always
returns a ReplayDetector (context manager, with .run() and .cancel()), and a
non-validated LoadResult is rejected without any frame access. Behavior
correctness is covered by tests/integration/ and tests/unit/; this file only
checks the contract shape.
"""

from pathlib import Path

import pytest

from cvip.video.errors import FailureReason
from cvip.video.loader import load_video
from cvip.video.models import LoadResult
from cvip.video.replay_detection import detect_replays
from cvip.video.replay_detection_errors import ReplayDetectionError, ReplayDetectionFailureReason
from cvip.video.replay_detection_models import ReplayDetectionRequest
from cvip.video.scene_detection_models import SceneDetectionResult

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "video_loader"

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


def _make_request(load_result, scene_result, **overrides) -> ReplayDetectionRequest:
    fields = dict(
        load_result=load_result,
        scene_detection_result=scene_result,
        confidence_threshold=0.65,
        min_segment_seconds=3.0,
        scoreboard_region=(0.0, 0.0, 0.2, 0.1),
        logo_template_path=None,
        **DEFAULT_WEIGHTS,
    )
    fields.update(overrides)
    return ReplayDetectionRequest(**fields)


def test_detect_replays_returns_replay_detector_shape():
    path = _require_fixture("valid_short.mp4")
    load_result = load_video(str(path))
    scene_result = SceneDetectionResult(source_video_id=load_result.source.file_hash)
    request = _make_request(load_result, scene_result)

    detector = detect_replays(request)

    assert hasattr(detector, "__enter__") and hasattr(detector, "__exit__")
    assert callable(getattr(detector, "run", None))
    assert callable(getattr(detector, "cancel", None))


def test_detect_replays_rejects_unvalidated_source_without_file_access(mocker):
    failed_result = LoadResult.failure(FailureReason.FILE_NOT_FOUND, "does not exist")
    scene_result = SceneDetectionResult(source_video_id="irrelevant")
    request = _make_request(failed_result, scene_result)

    mock_extract = mocker.patch("cvip.video.replay_detection.extract_frames")

    with pytest.raises(ReplayDetectionError) as exc_info:
        with detect_replays(request) as detector:
            detector.run()

    assert exc_info.value.reason == ReplayDetectionFailureReason.SOURCE_NOT_VALIDATED
    mock_extract.assert_not_called()
