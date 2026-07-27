"""Contract tests for the Scene Detection module boundary.

Asserts `detect_scenes()` matches the shape defined in
specs/003-scene-detection/contracts/scene_detection_contract.md -- always
returns a SceneDetector (context manager, with .run() and .cancel()), and a
non-validated LoadResult is rejected without any frame access. Behavior
correctness is covered by tests/integration/ and tests/unit/; this file only
checks the contract shape.
"""

from pathlib import Path

import pytest

from cvip.video.errors import FailureReason
from cvip.video.loader import load_video
from cvip.video.models import LoadResult
from cvip.video.scene_detection import detect_scenes
from cvip.video.scene_detection_errors import SceneDetectionError, SceneDetectionFailureReason
from cvip.video.scene_detection_models import SceneDetectionRequest

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "video_loader"


def _require_fixture(name: str) -> Path:
    path = FIXTURES_DIR / name
    if not path.exists():
        pytest.skip(
            f"Fixture {name} not found -- run "
            "`python tests/fixtures/video_loader/generate_fixtures.py` first."
        )
    return path


def test_detect_scenes_returns_scene_detector_shape():
    path = _require_fixture("valid_short.mp4")
    load_result = load_video(str(path))
    request = SceneDetectionRequest(load_result=load_result, scene_threshold=27.0)

    detector = detect_scenes(request)

    assert hasattr(detector, "__enter__") and hasattr(detector, "__exit__")
    assert callable(getattr(detector, "run", None))
    assert callable(getattr(detector, "cancel", None))


def test_detect_scenes_rejects_unvalidated_source_without_file_access(mocker):
    failed_result = LoadResult.failure(FailureReason.FILE_NOT_FOUND, "does not exist")
    request = SceneDetectionRequest(load_result=failed_result, scene_threshold=27.0)

    mock_extract = mocker.patch("cvip.video.scene_detection.extract_frames")

    with pytest.raises(SceneDetectionError) as exc_info:
        with detect_scenes(request) as detector:
            detector.run()

    assert exc_info.value.reason == SceneDetectionFailureReason.SOURCE_NOT_VALIDATED
    mock_extract.assert_not_called()
