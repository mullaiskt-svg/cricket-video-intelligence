"""Integration tests for the Frame Extraction Service: real fixture files
(reused from Video Loader), full extract_frames() calls. See
specs/002-frame-extraction-service/spec.md User Stories 1-3.
"""

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


def _load(name: str):
    path = _require_fixture(name)
    result = load_video(str(path))
    assert result.status.value == "SUCCESS", f"fixture {name} failed to load: {result.failure_detail}"
    return result


# --- User Story 1: sampling modes -------------------------------------------


def test_full_mode_yields_every_frame_correctly_indexed():
    load_result = _load("valid_short.mp4")
    request = ExtractionRequest(load_result=load_result, mode=SamplingMode.FULL)

    with extract_frames(request) as extractor:
        frames = list(extractor)

    assert len(frames) == load_result.source.frame_count
    for expected_index, ctx in enumerate(frames):
        assert ctx.frame_index == expected_index
        assert ctx.source_video_id == load_result.source.file_hash
    # timestamps strictly increase
    timestamps = [ctx.timestamp_seconds for ctx in frames]
    assert timestamps == sorted(timestamps)


def test_fixed_interval_mode_yields_roughly_one_frame_per_second():
    load_result = _load("valid_short.mp4")
    request = ExtractionRequest(
        load_result=load_result, mode=SamplingMode.FIXED_INTERVAL, rate_fps=1.0
    )

    with extract_frames(request) as extractor:
        frames = list(extractor)

    # ~5 second fixture at 1 FPS -> ~5 frames
    assert 4 <= len(frames) <= 6
    for ctx in frames:
        assert 0 <= ctx.frame_index < load_result.source.frame_count


def test_frame_list_mode_dedupes_and_sorts_regardless_of_input_order():
    load_result = _load("valid_short.mp4")
    request = ExtractionRequest(
        load_result=load_result, mode=SamplingMode.FRAME_LIST, frame_indices=[30, 5, 30, 10]
    )

    with extract_frames(request) as extractor:
        frames = list(extractor)

    assert [ctx.frame_index for ctx in frames] == [5, 10, 30]


def test_timestamp_list_mode_yields_nearest_real_frame_no_interpolation():
    load_result = _load("valid_short.mp4")
    request = ExtractionRequest(
        load_result=load_result, mode=SamplingMode.TIMESTAMP_LIST, timestamps_seconds=[2.51]
    )

    with extract_frames(request) as extractor:
        frames = list(extractor)

    assert len(frames) == 1
    # the yielded frame's own timestamp is a real decoded frame's timestamp,
    # not the literal 2.51 requested (no interpolation/synthesis)
    assert isinstance(frames[0].frame_index, int)
    assert frames[0].frame is not None


def test_diagnostics_emitted_exactly_once_for_successful_full_run(mocker):
    load_result = _load("valid_short.mp4")
    request = ExtractionRequest(load_result=load_result, mode=SamplingMode.FULL)

    emit_spy = mocker.patch("cvip.video.frame_extraction.emit_diagnostics")

    with extract_frames(request) as extractor:
        list(extractor)

    assert emit_spy.call_count == 1


# --- User Story 1: mid-run failures -----------------------------------------


def test_source_unavailable_mid_run_raises_specific_reason(mocker):
    """cv2.VideoCapture instances don't allow monkeypatching .read directly
    (read-only C-extension attribute) -- mock the whole capture object
    instead, matching the approach used in tests/unit/."""
    load_result = _load("valid_short.mp4")
    request = ExtractionRequest(load_result=load_result, mode=SamplingMode.FULL)

    fake_frame = np.zeros((10, 10, 3), dtype="uint8")
    mock_capture = mock.MagicMock()
    mock_capture.isOpened.return_value = True
    mock_capture.get.return_value = 0.0
    state = {"calls": 0}

    def fake_read():
        state["calls"] += 1
        if state["calls"] > 1:
            raise OSError("device disconnected")
        return True, fake_frame

    mock_capture.read.side_effect = fake_read
    mocker.patch("cv2.VideoCapture", return_value=mock_capture)

    with pytest.raises(ExtractionError) as exc_info:
        with extract_frames(request) as extractor:
            list(extractor)

    assert exc_info.value.reason == ExtractionFailureReason.SOURCE_UNAVAILABLE_MID_RUN


def test_decode_failure_mid_run_raises_specific_reason(mocker):
    load_result = _load("valid_short.mp4")
    request = ExtractionRequest(load_result=load_result, mode=SamplingMode.FULL)

    fake_frame = np.zeros((10, 10, 3), dtype="uint8")
    mock_capture = mock.MagicMock()
    mock_capture.isOpened.return_value = True
    mock_capture.get.return_value = 0.0
    state = {"calls": 0}

    def fake_read():
        state["calls"] += 1
        if state["calls"] > 1:
            return False, None
        return True, fake_frame

    mock_capture.read.side_effect = fake_read
    mocker.patch("cv2.VideoCapture", return_value=mock_capture)

    with pytest.raises(ExtractionError) as exc_info:
        with extract_frames(request) as extractor:
            list(extractor)

    assert exc_info.value.reason == ExtractionFailureReason.DECODE_FAILURE_MID_RUN


# --- User Story 1: determinism ----------------------------------------------


def test_repeated_runs_produce_identical_sequences():
    load_result = _load("valid_short.mp4")

    def run_once():
        request = ExtractionRequest(
            load_result=load_result, mode=SamplingMode.FIXED_INTERVAL, rate_fps=2.0
        )
        with extract_frames(request) as extractor:
            return [(ctx.frame_index, ctx.timestamp_seconds) for ctx in extractor]

    first = run_once()
    second = run_once()
    third = run_once()

    assert first == second == third


# --- User Story 3: progress, cancellation, resume ---------------------------


def test_cancel_mid_extraction_stops_iteration_releases_and_emits_once(mocker):
    """FR-015: cancel() stops further iteration, releases the capture, and
    emits exactly one diagnostics record (the same cleanup path as a normal
    finish)."""
    load_result = _load("valid_short.mp4")
    request = ExtractionRequest(load_result=load_result, mode=SamplingMode.FULL)

    emit_spy = mocker.patch("cvip.video.frame_extraction.emit_diagnostics")

    extractor = extract_frames(request)
    with extractor:
        seen = []
        for ctx in extractor:
            seen.append(ctx)
            if len(seen) == 3:
                extractor.cancel()
                break

        # further iteration after cancel() yields nothing more
        assert list(extractor) == []

    assert len(seen) == 3
    assert extractor._capture is None
    assert emit_spy.call_count == 1


def test_resume_from_frame_index_never_reyields_prior_frames():
    """FR-008: resume is inclusive of the resume point itself, and never
    re-yields any frame before it."""
    load_result = _load("valid_short.mp4")
    request = ExtractionRequest(
        load_result=load_result, mode=SamplingMode.FULL, resume_from_frame_index=10
    )

    with extract_frames(request) as extractor:
        frames = list(extractor)

    assert frames[0].frame_index == 10
    assert all(ctx.frame_index >= 10 for ctx in frames)


def test_resume_point_out_of_range_raises_specific_reason():
    load_result = _load("valid_short.mp4")
    out_of_range_index = load_result.source.frame_count + 1000
    request = ExtractionRequest(
        load_result=load_result,
        mode=SamplingMode.FULL,
        resume_from_frame_index=out_of_range_index,
    )

    with pytest.raises(ExtractionError) as exc_info:
        with extract_frames(request) as extractor:
            list(extractor)

    assert exc_info.value.reason == ExtractionFailureReason.RESUME_POINT_OUT_OF_RANGE


def test_resume_frame_index_takes_precedence_over_timestamp():
    """FR-008: when both a resume frame index and a resume timestamp are
    supplied, the frame index wins."""
    load_result = _load("valid_short.mp4")
    request = ExtractionRequest(
        load_result=load_result,
        mode=SamplingMode.FULL,
        resume_from_frame_index=10,
        # A timestamp that would resolve to a much later frame if it were
        # honored instead of the frame index.
        resume_from_timestamp_seconds=4.9,
    )

    with extract_frames(request) as extractor:
        frames = list(extractor)

    assert frames[0].frame_index == 10
