"""Contract tests for the Scoreboard OCR module boundary.

Asserts `extract_scoreboard()` matches the shape defined in
specs/005-scoreboard-ocr/contracts/scoreboard_ocr_contract.md -- always
returns a ScoreboardOcrExtractor (context manager, with .run() and
.cancel()), and a non-validated LoadResult is rejected without any frame
access. Behavior correctness is covered by tests/integration/ and
tests/unit/; this file only checks the contract shape.
"""

from pathlib import Path

import pytest

from cvip.video.errors import FailureReason
from cvip.video.loader import load_video
from cvip.video.models import LoadResult
from cvip.video.scoreboard_ocr import extract_scoreboard
from cvip.video.scoreboard_ocr_errors import ScoreboardOcrError, ScoreboardOcrFailureReason
from cvip.video.scoreboard_ocr_models import ScoreboardOcrRequest

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "video_loader"

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


def test_extract_scoreboard_returns_extractor_shape():
    path = _require_fixture("valid_short.mp4")
    load_result = load_video(str(path))

    request = ScoreboardOcrRequest(load_result=load_result, **DEFAULT_REQUEST_KWARGS)

    extractor = extract_scoreboard(request)

    assert hasattr(extractor, "__enter__") and hasattr(extractor, "__exit__")
    assert callable(getattr(extractor, "run", None))
    assert callable(getattr(extractor, "cancel", None))


def test_extract_scoreboard_rejects_unvalidated_source_without_file_access(mocker):
    failed_result = LoadResult.failure(FailureReason.FILE_NOT_FOUND, "does not exist")
    request = ScoreboardOcrRequest(load_result=failed_result, **DEFAULT_REQUEST_KWARGS)

    mock_extract = mocker.patch("cvip.video.scoreboard_ocr.extract_frames")

    with pytest.raises(ScoreboardOcrError) as exc_info:
        with extract_scoreboard(request) as extractor:
            extractor.run()

    assert exc_info.value.reason == ScoreboardOcrFailureReason.SOURCE_NOT_VALIDATED
    mock_extract.assert_not_called()
