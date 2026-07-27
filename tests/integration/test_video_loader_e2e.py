"""Integration tests for the Video Loader: real fixture files, full load_video()
call, asserting on the returned LoadResult. See specs/001-video-loader/spec.md
User Stories 1 and 2, and quickstart.md Scenarios 1-2.
"""

import sys
from pathlib import Path

import pytest

from cvip.video.errors import FailureReason
from cvip.video.loader import load_video
from cvip.video.models import ContainerFormat, LoadStatus

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "video_loader"

# tests/fixtures/video_loader/ is not a package (see tasks.md T002 -- only
# contract/integration/unit/benchmark get __init__.py) so import its helper by
# path rather than as a dotted module.
if str(FIXTURES_DIR) not in sys.path:
    sys.path.insert(0, str(FIXTURES_DIR))


def _require_fixture(name: str) -> Path:
    path = FIXTURES_DIR / name
    if not path.exists():
        pytest.skip(
            f"Fixture {name} not found -- run "
            "`python tests/fixtures/video_loader/generate_fixtures.py` first."
        )
    return path


# --- User Story 1: valid videos load with correct metadata -----------------


def test_load_valid_mp4_succeeds_with_correct_metadata():
    path = _require_fixture("valid_short.mp4")

    result = load_video(str(path))

    assert result.status == LoadStatus.SUCCESS
    assert result.source is not None
    assert result.source.container_format == ContainerFormat.MP4
    assert 4.0 <= result.source.duration_seconds <= 6.0
    assert result.source.resolution == (640, 480)
    assert 20.0 <= result.source.frame_rate <= 30.0
    assert result.source.frame_count > 0
    assert result.source.codec
    assert result.source.file_hash


def test_load_valid_mkv_succeeds_with_correct_metadata():
    path = _require_fixture("valid_short.mkv")

    result = load_video(str(path))

    assert result.status == LoadStatus.SUCCESS
    assert result.source is not None
    assert result.source.container_format == ContainerFormat.MKV
    assert 4.0 <= result.source.duration_seconds <= 6.0
    assert result.source.resolution == (640, 480)


def test_file_hash_is_stable_across_repeated_loads():
    path = _require_fixture("valid_short.mp4")

    first = load_video(str(path))
    second = load_video(str(path))

    assert first.source.file_hash == second.source.file_hash


def test_file_hash_differs_between_distinct_files():
    mp4 = _require_fixture("valid_short.mp4")
    mkv = _require_fixture("valid_short.mkv")

    mp4_result = load_video(str(mp4))
    mkv_result = load_video(str(mkv))

    assert mp4_result.source.file_hash != mkv_result.source.file_hash


# --- User Story 2: invalid inputs are rejected with a specific reason ------


def test_nonexistent_path_is_file_not_found():
    result = load_video(str(FIXTURES_DIR / "does_not_exist.mp4"))

    assert result.status == LoadStatus.FAILURE
    assert result.failure_reason == FailureReason.FILE_NOT_FOUND
    assert result.source is None


def test_directory_path_is_file_not_found():
    result = load_video(str(FIXTURES_DIR))

    assert result.status == LoadStatus.FAILURE
    assert result.failure_reason == FailureReason.FILE_NOT_FOUND


def test_unsupported_extension_is_rejected():
    path = _require_fixture("unsupported.avi")

    result = load_video(str(path))

    assert result.status == LoadStatus.FAILURE
    assert result.failure_reason == FailureReason.UNSUPPORTED_FORMAT


def test_truncated_file_is_corrupted_or_undecodable():
    path = _require_fixture("corrupted.mp4")

    result = load_video(str(path))

    assert result.status == LoadStatus.FAILURE
    assert result.failure_reason == FailureReason.CORRUPTED_OR_UNDECODABLE


def test_zero_byte_file_is_corrupted_or_undecodable():
    path = _require_fixture("zero_byte.mp4")

    result = load_video(str(path))

    assert result.status == LoadStatus.FAILURE
    assert result.failure_reason == FailureReason.CORRUPTED_OR_UNDECODABLE


def test_locked_file_is_locked_or_inaccessible():
    from lock_helper import locked_file

    path = _require_fixture("valid_short.mp4")

    with locked_file(path):
        result = load_video(str(path))

    assert result.status == LoadStatus.FAILURE
    assert result.failure_reason == FailureReason.FILE_LOCKED_OR_INACCESSIBLE
