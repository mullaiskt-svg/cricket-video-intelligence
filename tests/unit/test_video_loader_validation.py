"""Unit tests for Video Loader validation/error-classification logic and the
sampled file-hash implementation. See specs/001-video-loader/spec.md FR-012,
FR-014 and contracts/video_loader_contract.md's error taxonomy ordering.
"""

import builtins
import socket
from pathlib import Path
from unittest import mock

import numpy as np
import pytest

from cvip.video.errors import FailureReason
from cvip.video.hashing import compute_file_hash
from cvip.video.loader import load_video
from cvip.video.metadata import identify_codec
from cvip.video.models import LoadStatus

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "video_loader"


def _require_fixture(name: str) -> Path:
    path = FIXTURES_DIR / name
    if not path.exists():
        pytest.skip(
            f"Fixture {name} not found -- run "
            "`python tests/fixtures/video_loader/generate_fixtures.py` first."
        )
    return path


# --- FR-012: decoded frame resolution wins over container header ----------


def test_decoded_frame_resolution_wins_over_header_mismatch(mocker, tmp_path):
    """cv2.VideoCapture reports one size via .get(), but the actual decoded
    frame has a different shape -- the frame's shape must be what's reported."""
    # A real (empty) file so the existence/format/lock checks pass normally;
    # only decoding itself is mocked.
    fake_path = tmp_path / "fake.mp4"
    fake_path.write_bytes(b"")

    fake_frame = np.zeros((480, 640, 3), dtype="uint8")  # actual: 640x480

    mock_capture = mock.MagicMock()
    mock_capture.isOpened.return_value = True
    mock_capture.read.return_value = (True, fake_frame)

    def fake_get(prop):
        import cv2

        # Header claims a mismatched 1920x1080
        if prop == cv2.CAP_PROP_FRAME_WIDTH:
            return 1920
        if prop == cv2.CAP_PROP_FRAME_HEIGHT:
            return 1080
        if prop == cv2.CAP_PROP_FPS:
            return 25.0
        if prop == cv2.CAP_PROP_FRAME_COUNT:
            return 125
        return 0

    mock_capture.get.side_effect = fake_get

    mocker.patch("cv2.VideoCapture", return_value=mock_capture)
    mocker.patch("cvip.video.metadata.identify_codec", return_value="h264")
    mocker.patch("cvip.video.hashing.compute_file_hash", return_value="deadbeef")

    result = load_video(str(fake_path))

    assert result.status == LoadStatus.SUCCESS
    assert result.source.resolution == (640, 480)


def test_first_frame_decode_failure_is_corrupted(mocker, tmp_path):
    """isOpened() is True but read() fails -- the truncated/corrupted-file
    case that isOpened() alone can't catch (research.md)."""
    fake_path = tmp_path / "fake.mp4"
    fake_path.write_bytes(b"")

    mock_capture = mock.MagicMock()
    mock_capture.isOpened.return_value = True
    mock_capture.read.return_value = (False, None)
    mocker.patch("cv2.VideoCapture", return_value=mock_capture)

    result = load_video(str(fake_path))

    assert result.status == LoadStatus.FAILURE
    assert result.failure_reason == FailureReason.CORRUPTED_OR_UNDECODABLE


def test_unusable_frame_rate_is_corrupted(mocker, tmp_path):
    """A decodable first frame but a zero/negative frame rate or frame count
    is still not a usable video (contract's error taxonomy 'unusable frame
    rate, duration, or frame count' example)."""
    fake_path = tmp_path / "fake.mp4"
    fake_path.write_bytes(b"")

    fake_frame = np.zeros((480, 640, 3), dtype="uint8")
    mock_capture = mock.MagicMock()
    mock_capture.isOpened.return_value = True
    mock_capture.read.return_value = (True, fake_frame)
    mock_capture.get.return_value = 0  # FPS and frame count both report 0
    mocker.patch("cv2.VideoCapture", return_value=mock_capture)

    result = load_video(str(fake_path))

    assert result.status == LoadStatus.FAILURE
    assert result.failure_reason == FailureReason.CORRUPTED_OR_UNDECODABLE


def test_codec_identification_failure_is_corrupted(mocker, tmp_path):
    """If ffprobe can't identify a codec, the file is treated as undecodable
    even though OpenCV itself decoded a frame."""
    fake_path = tmp_path / "fake.mp4"
    fake_path.write_bytes(b"")

    fake_frame = np.zeros((480, 640, 3), dtype="uint8")
    mock_capture = mock.MagicMock()
    mock_capture.isOpened.return_value = True
    mock_capture.read.return_value = (True, fake_frame)
    mock_capture.get.return_value = 25.0
    mocker.patch("cv2.VideoCapture", return_value=mock_capture)
    mocker.patch(
        "cvip.video.metadata.identify_codec", side_effect=ValueError("no codec")
    )

    result = load_video(str(fake_path))

    assert result.status == LoadStatus.FAILURE
    assert result.failure_reason == FailureReason.CORRUPTED_OR_UNDECODABLE


def test_nan_frame_rate_is_rejected_not_silently_accepted(mocker, tmp_path):
    """A NaN FPS must be rejected, not silently produce a 'successful' load
    with a NaN duration -- `nan <= 0` is False in Python, so the guard must
    use `not (x > 0)`, not `x <= 0` (see loader.py's comment)."""
    fake_path = tmp_path / "fake.mp4"
    fake_path.write_bytes(b"")

    fake_frame = np.zeros((480, 640, 3), dtype="uint8")
    mock_capture = mock.MagicMock()
    mock_capture.isOpened.return_value = True
    mock_capture.read.return_value = (True, fake_frame)
    mock_capture.get.return_value = float("nan")
    mocker.patch("cv2.VideoCapture", return_value=mock_capture)

    result = load_video(str(fake_path))

    assert result.status == LoadStatus.FAILURE
    assert result.failure_reason == FailureReason.CORRUPTED_OR_UNDECODABLE


def test_unexpected_cv2_exception_is_corrupted_not_raised(mocker, tmp_path):
    """load_video() must never raise, even if OpenCV itself raises rather
    than returning a falsy status for a sufficiently malformed file."""
    fake_path = tmp_path / "fake.mp4"
    fake_path.write_bytes(b"")

    mocker.patch("cv2.VideoCapture", side_effect=RuntimeError("boom"))

    result = load_video(str(fake_path))

    assert result.status == LoadStatus.FAILURE
    assert result.failure_reason == FailureReason.CORRUPTED_OR_UNDECODABLE


def test_missing_ffprobe_produces_actionable_detail_message(mocker, tmp_path):
    """A missing ffprobe binary is a native-dependency problem (see
    docs/DEPENDENCIES.md), not a per-file corruption issue -- the detail
    message must say so distinctly, even though it still maps to
    CORRUPTED_OR_UNDECODABLE (the contract's taxonomy has no dedicated
    'missing dependency' value)."""
    fake_path = tmp_path / "fake.mp4"
    fake_path.write_bytes(b"")

    fake_frame = np.zeros((480, 640, 3), dtype="uint8")
    mock_capture = mock.MagicMock()
    mock_capture.isOpened.return_value = True
    mock_capture.read.return_value = (True, fake_frame)
    mock_capture.get.return_value = 25.0
    mocker.patch("cv2.VideoCapture", return_value=mock_capture)
    mocker.patch(
        "cvip.video.metadata.identify_codec",
        side_effect=FileNotFoundError("[WinError 2] ffprobe not found"),
    )

    result = load_video(str(fake_path))

    assert result.status == LoadStatus.FAILURE
    assert result.failure_reason == FailureReason.CORRUPTED_OR_UNDECODABLE
    assert "ffprobe" in result.failure_detail
    assert "PATH" in result.failure_detail


def test_identify_codec_raises_when_ffprobe_finds_no_video_stream(mocker):
    fake_completed = mock.MagicMock()
    fake_completed.stdout = '{"streams": []}'
    mocker.patch("subprocess.run", return_value=fake_completed)

    with pytest.raises(ValueError):
        identify_codec("irrelevant.mp4")


# --- FR-014: sampled file hash ---------------------------------------------


def _make_file(path: Path, size_bytes: int) -> None:
    with open(path, "wb") as f:
        if size_bytes > 0:
            f.seek(size_bytes - 1)
            f.write(b"\0")


def _count_bytes_read(fn) -> int:
    total = [0]
    real_open = builtins.open

    def counting_open(*args, **kwargs):
        f = real_open(*args, **kwargs)
        real_read = f.read

        def counting_read(size=-1, *a, **kw):
            data = real_read(size, *a, **kw)
            total[0] += len(data)
            return data

        f.read = counting_read
        return f

    with mock.patch("builtins.open", counting_open):
        fn()
    return total[0]


def test_compute_file_hash_is_deterministic(tmp_path):
    path = tmp_path / "sample.bin"
    _make_file(path, 4096)

    first = compute_file_hash(str(path))
    second = compute_file_hash(str(path))

    assert first == second


def test_compute_file_hash_differs_for_different_content(tmp_path):
    path_a = tmp_path / "a.bin"
    path_b = tmp_path / "b.bin"
    path_a.write_bytes(b"a" * 4096)
    path_b.write_bytes(b"b" * 4096)

    assert compute_file_hash(str(path_a)) != compute_file_hash(str(path_b))


def test_compute_file_hash_reads_bounded_bytes_regardless_of_file_size(tmp_path):
    small = tmp_path / "small.bin"
    large = tmp_path / "large.bin"
    _make_file(small, 2 * 1024 * 1024)  # 2 MiB
    _make_file(large, 100 * 1024 * 1024)  # 100 MiB

    small_bytes_read = _count_bytes_read(lambda: compute_file_hash(str(small)))
    large_bytes_read = _count_bytes_read(lambda: compute_file_hash(str(large)))

    assert small_bytes_read == large_bytes_read
    # 1 MiB prefix + 1 MiB suffix, generous slack for implementation details
    assert small_bytes_read <= 3 * 1024 * 1024


# --- FR-004/FR-005: deterministic failure-reason classification order -----


def test_classification_order_directory_before_format_check():
    """A directory has no extension to check -- must classify as
    FILE_NOT_FOUND, not fall through to a format/decode check."""
    result = load_video(str(FIXTURES_DIR))
    assert result.failure_reason == FailureReason.FILE_NOT_FOUND


def test_classification_order_existence_checked_before_format():
    """Per the contract's documented order (existence -> format -> lock ->
    decode), a nonexistent path is FILE_NOT_FOUND even when its extension is
    also unsupported -- existence wins, not format."""
    result = load_video(str(FIXTURES_DIR / "does_not_exist.avi"))
    assert result.failure_reason == FailureReason.FILE_NOT_FOUND


# --- FR-009: offline -- no network calls -----------------------------------


def test_load_video_makes_no_network_calls(mocker):
    def _fail_if_called(*args, **kwargs):
        raise AssertionError("load_video() must not create network sockets")

    mocker.patch.object(socket, "socket", side_effect=_fail_if_called)

    path = _require_fixture("valid_short.mp4")
    result = load_video(str(path))

    assert result.status == LoadStatus.SUCCESS
