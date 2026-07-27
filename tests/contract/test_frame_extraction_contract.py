"""Contract tests for the Frame Extraction Service module boundary.

Asserts `extract_frames()` matches the shape defined in
specs/002-frame-extraction-service/contracts/frame_extraction_contract.md --
always returns a FrameExtractor (iterable, context manager, with .progress
and .cancel()), and a non-validated LoadResult is rejected without any file
access. Behavior correctness is covered by tests/integration/ and tests/unit/;
this file only checks the contract shape.
"""

from pathlib import Path

import pytest

from cvip.video.errors import FailureReason
from cvip.video.frame_extraction import extract_frames
from cvip.video.frame_extraction_errors import ExtractionError, ExtractionFailureReason
from cvip.video.frame_extraction_models import ExtractionRequest, SamplingMode
from cvip.video.loader import load_video
from cvip.video.models import LoadResult

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "video_loader"


def _require_fixture(name: str) -> Path:
    path = FIXTURES_DIR / name
    if not path.exists():
        pytest.skip(
            f"Fixture {name} not found -- run "
            "`python tests/fixtures/video_loader/generate_fixtures.py` first."
        )
    return path


def test_extract_frames_returns_frame_extractor_shape():
    path = _require_fixture("valid_short.mp4")
    load_result = load_video(str(path))
    request = ExtractionRequest(load_result=load_result, mode=SamplingMode.FULL)

    extractor = extract_frames(request)

    assert hasattr(extractor, "__iter__")
    assert hasattr(extractor, "__enter__") and hasattr(extractor, "__exit__")
    assert hasattr(extractor, "progress")
    assert callable(getattr(extractor, "cancel", None))


def test_extract_frames_rejects_unvalidated_source_without_file_access(mocker):
    failed_result = LoadResult.failure(FailureReason.FILE_NOT_FOUND, "does not exist")
    request = ExtractionRequest(load_result=failed_result, mode=SamplingMode.FULL)

    mock_capture = mocker.patch("cv2.VideoCapture")

    with pytest.raises(ExtractionError) as exc_info:
        with extract_frames(request) as extractor:
            list(extractor)

    assert exc_info.value.reason == ExtractionFailureReason.SOURCE_NOT_VALIDATED
    mock_capture.assert_not_called()
