"""Contract tests for the Video Loader module boundary.

Asserts `load_video()` matches the shape defined in
specs/001-video-loader/contracts/video_loader_contract.md -- always returns a
LoadResult (never raises, never None), with the right field types on both the
success and failure paths. Behavior correctness (which fixture produces which
outcome) is covered by tests/integration/ and tests/unit/; this file only
checks the contract shape.
"""

from datetime import datetime
from pathlib import Path

import pytest

from cvip.video.errors import FailureReason
from cvip.video.loader import load_video
from cvip.video.models import ContainerFormat, LoadResult, LoadStatus, MatchVideoSource

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "video_loader"


def _require_fixture(name: str) -> Path:
    path = FIXTURES_DIR / name
    if not path.exists():
        pytest.skip(
            f"Fixture {name} not found -- run "
            "`python tests/fixtures/video_loader/generate_fixtures.py` first."
        )
    return path


def test_load_video_never_raises_for_expected_failure_inputs():
    """Missing file, unsupported format, corrupted file -- all represented as
    a FAILURE LoadResult, per the contract, not an exception."""
    for bad_path in (
        str(FIXTURES_DIR / "does_not_exist.mp4"),
        str(FIXTURES_DIR / "does_not_exist.avi"),
    ):
        result = load_video(bad_path)
        assert isinstance(result, LoadResult)


def test_success_result_shape():
    path = _require_fixture("valid_short.mp4")

    result = load_video(str(path))

    assert isinstance(result, LoadResult)
    assert result.status == LoadStatus.SUCCESS
    assert result.failure_reason is None
    assert result.failure_detail is None
    assert isinstance(result.timestamp, datetime)

    source = result.source
    assert isinstance(source, MatchVideoSource)
    assert isinstance(source.container_format, ContainerFormat)
    assert isinstance(source.duration_seconds, float)
    assert isinstance(source.resolution, tuple) and len(source.resolution) == 2
    assert isinstance(source.frame_rate, float)
    assert isinstance(source.frame_count, int)
    assert isinstance(source.codec, str) and source.codec
    assert isinstance(source.file_hash, str) and source.file_hash


def test_failure_result_shape():
    result = load_video(str(FIXTURES_DIR / "does_not_exist.mp4"))

    assert isinstance(result, LoadResult)
    assert result.status == LoadStatus.FAILURE
    assert result.source is None
    assert isinstance(result.failure_reason, FailureReason)
    assert isinstance(result.failure_detail, str) and result.failure_detail
    assert isinstance(result.timestamp, datetime)
