"""Unit tests for Frame Extraction Service internals: actual-timestamp
authority, offline/CPU-only behavior, and (later) progress/buffering.
See specs/002-frame-extraction-service/spec.md FR-004, FR-011, FR-012.
"""

import socket
from pathlib import Path
from unittest import mock

import numpy as np
import pytest

from cvip.video.frame_extraction import extract_frames
from cvip.video.frame_extraction_errors import ExtractionError, ExtractionFailureReason
from cvip.video.frame_extraction_models import ExtractionRequest, SamplingMode
from cvip.video.loader import load_video

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "video_loader"


def _require_fixture(name: str) -> Path:
    path = FIXTURES_DIR / name
    if not path.exists():
        pytest.skip(
            f"Fixture {name} not found -- run "
            "`python tests/fixtures/video_loader/generate_fixtures.py` first."
        )
    return path


def test_reported_timestamp_comes_from_actual_decoded_frame(mocker):
    """The seeked frame's real CAP_PROP_POS_MSEC must win over a naive
    frame_index / native_fps calculation -- this is what makes VFR sources
    work correctly (research.md)."""
    path = _require_fixture("valid_short.mp4")
    load_result = load_video(str(path))

    fake_frame = np.zeros((10, 10, 3), dtype="uint8")
    mock_capture = mock.MagicMock()
    mock_capture.isOpened.return_value = True
    mock_capture.read.return_value = (True, fake_frame)

    # Naive calc for frame_index=10 at 25fps would be 10/25=0.4s=400ms.
    # Report a deliberately inconsistent "actual" timestamp instead.
    def fake_get(prop):
        import cv2

        if prop == cv2.CAP_PROP_POS_FRAMES:
            return 11  # position after reading frame index 10
        if prop == cv2.CAP_PROP_POS_MSEC:
            return 9999.0  # deliberately NOT 400ms
        return 0

    mock_capture.get.side_effect = fake_get
    mocker.patch("cv2.VideoCapture", return_value=mock_capture)

    request = ExtractionRequest(
        load_result=load_result, mode=SamplingMode.FRAME_LIST, frame_indices=[10]
    )
    with extract_frames(request) as extractor:
        frames = list(extractor)

    assert len(frames) == 1
    assert frames[0].timestamp_seconds == pytest.approx(9.999)


def test_extraction_makes_no_network_calls(mocker):
    def _fail_if_called(*args, **kwargs):
        raise AssertionError("extraction must not create network sockets")

    mocker.patch.object(socket, "socket", side_effect=_fail_if_called)
    mocker.patch.object(socket, "create_connection", side_effect=_fail_if_called)

    path = _require_fixture("valid_short.mp4")
    load_result = load_video(str(path))
    request = ExtractionRequest(load_result=load_result, mode=SamplingMode.FULL)

    with extract_frames(request) as extractor:
        frames = list(extractor)

    assert len(frames) > 0


def test_no_pre_buffering_ahead_of_caller_consumption(mocker):
    """Exactly one frame is decoded per __next__() call -- the service must
    not decode/buffer future frames ahead of what the caller has consumed
    (FR-005)."""
    path = _require_fixture("valid_short.mp4")
    load_result = load_video(str(path))

    fake_frame = np.zeros((10, 10, 3), dtype="uint8")
    mock_capture = mock.MagicMock()
    mock_capture.isOpened.return_value = True
    mock_capture.read.return_value = (True, fake_frame)
    mock_capture.get.return_value = 0.0
    mocker.patch("cv2.VideoCapture", return_value=mock_capture)

    request = ExtractionRequest(load_result=load_result, mode=SamplingMode.FULL)
    extractor = extract_frames(request)

    with extractor:
        first_read_count_before = mock_capture.read.call_count
        next(extractor)
        assert mock_capture.read.call_count == first_read_count_before + 1

        next(extractor)
        assert mock_capture.read.call_count == first_read_count_before + 2


def test_progress_fields_update_correctly_during_iteration():
    """FR-007: processed_frames/processed_seconds/percent_complete must
    reflect exactly what has been yielded so far, and total_frames/
    total_duration_seconds must be known up-front (before the first
    frame is yielded)."""
    path = _require_fixture("valid_short.mp4")
    load_result = load_video(str(path))
    request = ExtractionRequest(load_result=load_result, mode=SamplingMode.FULL)

    with extract_frames(request) as extractor:
        assert extractor.progress.processed_frames == 0
        assert extractor.progress.percent_complete == 0.0

        total_frames = load_result.source.frame_count
        seen = 0
        for _ in extractor:
            seen += 1
            assert extractor.progress.processed_frames == seen
            assert extractor.progress.total_frames == total_frames
            assert extractor.progress.total_duration_seconds == pytest.approx(
                load_result.source.duration_seconds
            )
            expected_percent = min(100.0, (seen / total_frames) * 100.0)
            assert extractor.progress.percent_complete == pytest.approx(expected_percent)

        assert extractor.progress.processed_frames == total_frames
        assert extractor.progress.percent_complete == pytest.approx(100.0)


def test_no_gpu_specific_opencv_api_is_used():
    """Static check (FR-012): no cv2.cuda.* call anywhere in this module's
    source. CPU-only is otherwise satisfied by construction -- no GPU
    library is a dependency of this project at all."""
    source_dir = Path(__file__).parent.parent.parent / "src" / "cvip" / "video"
    for filename in ("frame_extraction.py", "frame_extraction_models.py", "frame_extraction_errors.py"):
        text = (source_dir / filename).read_text(encoding="utf-8")
        assert "cv2.cuda" not in text, f"{filename} must not use GPU-specific OpenCV APIs"
        assert "cuda" not in text.lower(), f"{filename} must not reference CUDA/GPU APIs"


# --- ExtractionRequest validation --------------------------------------------


def test_extraction_request_requires_mode_specific_field():
    with pytest.raises(ValueError, match="rate_fps is required"):
        ExtractionRequest(load_result=mock.MagicMock(), mode=SamplingMode.FIXED_INTERVAL)


def test_extraction_request_rejects_field_for_wrong_mode():
    with pytest.raises(ValueError, match="must not be set"):
        ExtractionRequest(load_result=mock.MagicMock(), mode=SamplingMode.FULL, rate_fps=1.0)


# --- target resolution edge cases --------------------------------------------


def test_source_unopenable_raises_source_unavailable(mocker):
    load_result = load_video(str(_require_fixture("valid_short.mp4")))

    mock_capture = mock.MagicMock()
    mock_capture.isOpened.return_value = False
    mocker.patch("cv2.VideoCapture", return_value=mock_capture)

    request = ExtractionRequest(load_result=load_result, mode=SamplingMode.FULL)
    with pytest.raises(ExtractionError) as exc_info:
        with extract_frames(request) as extractor:
            list(extractor)

    assert exc_info.value.reason == ExtractionFailureReason.SOURCE_UNAVAILABLE_MID_RUN


def test_non_positive_rate_fps_yields_no_frames():
    load_result = load_video(str(_require_fixture("valid_short.mp4")))
    request = ExtractionRequest(load_result=load_result, mode=SamplingMode.FIXED_INTERVAL, rate_fps=0.0)

    with extract_frames(request) as extractor:
        frames = list(extractor)

    assert frames == []


def test_out_of_range_frame_index_is_skipped_with_warning(mocker):
    load_result = load_video(str(_require_fixture("valid_short.mp4")))
    native_count = load_result.source.frame_count
    emit_spy = mocker.patch("cvip.video.frame_extraction.emit_diagnostics")

    request = ExtractionRequest(
        load_result=load_result,
        mode=SamplingMode.FRAME_LIST,
        frame_indices=[-1, native_count + 1000, 5],
    )
    with extract_frames(request) as extractor:
        frames = list(extractor)

    assert [ctx.frame_index for ctx in frames] == [5]
    diagnostics = emit_spy.call_args[0][0]
    assert any("out of range" in warning for warning in diagnostics.warnings)


def test_out_of_range_timestamp_is_skipped_with_warning(mocker):
    load_result = load_video(str(_require_fixture("valid_short.mp4")))
    emit_spy = mocker.patch("cvip.video.frame_extraction.emit_diagnostics")

    request = ExtractionRequest(
        load_result=load_result,
        mode=SamplingMode.TIMESTAMP_LIST,
        timestamps_seconds=[-1.0, 1_000_000.0, 2.0],
    )
    with extract_frames(request) as extractor:
        frames = list(extractor)

    assert len(frames) == 1
    diagnostics = emit_spy.call_args[0][0]
    assert any("out of range" in warning for warning in diagnostics.warnings)


def test_timestamps_rounding_to_same_frame_are_deduped():
    load_result = load_video(str(_require_fixture("valid_short.mp4")))

    request = ExtractionRequest(
        load_result=load_result,
        mode=SamplingMode.TIMESTAMP_LIST,
        timestamps_seconds=[2.0, 2.005],  # both round to the same native frame at 25fps
    )
    with extract_frames(request) as extractor:
        frames = list(extractor)

    assert len(frames) == 1


def test_resume_from_timestamp_only_resolves_to_frame_index():
    load_result = load_video(str(_require_fixture("valid_short.mp4")))

    request = ExtractionRequest(
        load_result=load_result, mode=SamplingMode.FULL, resume_from_timestamp_seconds=2.0
    )
    with extract_frames(request) as extractor:
        frames = list(extractor)

    expected_first_index = round(2.0 * load_result.source.frame_rate)
    assert frames[0].frame_index == expected_first_index


def test_get_failure_after_successful_read_raises_source_unavailable(mocker):
    """The second capture.get() call (retrieving actual index/timestamp)
    can also fail mid-run -- this must map to the same
    SOURCE_UNAVAILABLE_MID_RUN reason as a failure earlier in the read."""
    load_result = load_video(str(_require_fixture("valid_short.mp4")))

    fake_frame = np.zeros((10, 10, 3), dtype="uint8")
    mock_capture = mock.MagicMock()
    mock_capture.isOpened.return_value = True
    mock_capture.read.return_value = (True, fake_frame)
    mock_capture.get.side_effect = OSError("device disconnected")
    mocker.patch("cv2.VideoCapture", return_value=mock_capture)

    request = ExtractionRequest(load_result=load_result, mode=SamplingMode.FULL)
    with pytest.raises(ExtractionError) as exc_info:
        with extract_frames(request) as extractor:
            list(extractor)

    assert exc_info.value.reason == ExtractionFailureReason.SOURCE_UNAVAILABLE_MID_RUN
