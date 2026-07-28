"""Integration tests for Replay Detection: real fixture files (reused from
Video Loader), full detect_replays() calls. See
specs/004-replay-detection/spec.md User Stories 1-3.
"""

from pathlib import Path

import cv2
import numpy as np
import pytest

from cvip.video.frame_extraction_errors import ExtractionError, ExtractionFailureReason
from cvip.video.frame_extraction_models import FrameContext
from cvip.video.loader import load_video
from cvip.video.models import ContainerFormat, LoadResult, MatchVideoSource
from cvip.video.replay_detection import detect_replays
from cvip.video.replay_detection_errors import ReplayDetectionError, ReplayDetectionFailureReason
from cvip.video.replay_detection_models import ReplayDetectionRequest
from cvip.video.scene_detection import detect_scenes
from cvip.video.scene_detection_models import BoundaryType, SceneBoundary, SceneDetectionRequest, SceneDetectionResult

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "video_loader"

DEFAULT_WEIGHTS = dict(
    logo_weight=0.35,
    scoreboard_weight=0.20,
    motion_weight=0.20,
    transition_weight=0.15,
    camera_angle_weight=0.10,
)

# Weights concentrated on the transition signal -- lets these controlled
# scenarios drive combined_confidence deterministically from just the Scene
# Detection boundary's own confidence, without needing to reverse-engineer
# the four self-computed signals' exact pixel-level arithmetic.
TRANSITION_HEAVY_WEIGHTS = dict(
    logo_weight=0.075,
    scoreboard_weight=0.075,
    motion_weight=0.075,
    transition_weight=0.70,
    camera_angle_weight=0.075,
)


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


def _dummy_load_result(file_hash="deadbeef", duration_seconds=100.0) -> LoadResult:
    source = MatchVideoSource(
        file_path="dummy.mp4",
        container_format=ContainerFormat.MP4,
        duration_seconds=duration_seconds,
        resolution=(1280, 720),
        frame_rate=25.0,
        frame_count=int(duration_seconds * 25.0),
        codec="h264",
        file_hash=file_hash,
    )
    return LoadResult.success(source)


def _solid_frame(value: int, size=(32, 32, 3)) -> np.ndarray:
    return np.full(size, value, dtype="uint8")


class _FakeFrameExtractor:
    def __init__(self, frame_contexts, error=None):
        self._frame_contexts = frame_contexts
        self._error = error

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def __iter__(self):
        yield from self._frame_contexts
        if self._error is not None:
            raise self._error


def _one_fps_frames(duration_seconds, source_video_id="deadbeef"):
    return [
        FrameContext(
            source_video_id=source_video_id, frame_index=i, timestamp_seconds=float(i), frame=_solid_frame(0)
        )
        for i in range(int(duration_seconds))
    ]


def _make_request(load_result, scene_result, weights=None, **overrides) -> ReplayDetectionRequest:
    fields = dict(
        load_result=load_result,
        scene_detection_result=scene_result,
        confidence_threshold=0.65,
        min_segment_seconds=3.0,
        scoreboard_region=(0.0, 0.0, 0.2, 0.1),
        logo_template_path=None,
        **(weights or DEFAULT_WEIGHTS),
    )
    fields.update(overrides)
    return ReplayDetectionRequest(**fields)


# --- US1: structural correctness against a real fixture, real Scene Detection


def test_detection_against_real_fixture_yields_valid_structural_result(mocker):
    load_result = _load("valid_short.mp4")
    scene_request = SceneDetectionRequest(load_result=load_result, scene_threshold=27.0)
    with detect_scenes(scene_request) as scene_detector:
        scene_result = scene_detector.run()

    request = _make_request(load_result, scene_result)
    emit_spy = mocker.patch("cvip.video.replay_detection.emit_diagnostics")

    with detect_replays(request) as detector:
        result = detector.run()

    starts = [s.start_seconds for s in result.segments]
    assert starts == sorted(starts)
    ids = [s.replay_id for s in result.segments]
    assert len(ids) == len(set(ids))
    for segment in result.segments:
        assert 0.0 <= segment.confidence <= 1.0
    assert result.total_segments == len(result.segments)
    assert emit_spy.call_count == 1


# --- US1: threshold application ----------------------------------------------


def test_replay_transition_segment_meeting_threshold_is_reported(mocker):
    boundary = SceneBoundary(
        boundary_id=0, timestamp_seconds=10.0, boundary_type=BoundaryType.REPLAY_TRANSITION, confidence=1.0
    )
    load_result = _dummy_load_result(duration_seconds=20.0)
    scene_result = SceneDetectionResult(source_video_id=load_result.source.file_hash, boundaries=[boundary])
    frames = _one_fps_frames(20.0)
    mocker.patch("cvip.video.replay_detection.extract_frames", return_value=_FakeFrameExtractor(frames))

    request = _make_request(load_result, scene_result, weights=TRANSITION_HEAVY_WEIGHTS)

    with detect_replays(request) as detector:
        result = detector.run()

    assert any(s.start_seconds == pytest.approx(10.0) for s in result.segments)


def test_ordinary_cut_segment_below_threshold_is_not_reported(mocker):
    boundary = SceneBoundary(
        boundary_id=0, timestamp_seconds=10.0, boundary_type=BoundaryType.ORDINARY_CUT, confidence=0.9
    )
    load_result = _dummy_load_result(duration_seconds=20.0)
    scene_result = SceneDetectionResult(source_video_id=load_result.source.file_hash, boundaries=[boundary])
    frames = _one_fps_frames(20.0)
    mocker.patch("cvip.video.replay_detection.extract_frames", return_value=_FakeFrameExtractor(frames))

    request = _make_request(load_result, scene_result, weights=TRANSITION_HEAVY_WEIGHTS)

    with detect_replays(request) as detector:
        result = detector.run()

    assert result.segments == ()


def test_replay_transition_pulled_below_threshold_by_other_signals_is_not_reported(mocker):
    """US1 Acceptance Scenarios 2-3: a segment Scene Detection flagged
    REPLAY_TRANSITION is still rejected when the other (neutral, cold-start)
    signals pull the combined confidence below threshold under the default,
    non-transition-dominant weight distribution."""
    boundary = SceneBoundary(
        boundary_id=0, timestamp_seconds=10.0, boundary_type=BoundaryType.REPLAY_TRANSITION, confidence=1.0
    )
    load_result = _dummy_load_result(duration_seconds=20.0)
    scene_result = SceneDetectionResult(source_video_id=load_result.source.file_hash, boundaries=[boundary])
    frames = _one_fps_frames(20.0)
    mocker.patch("cvip.video.replay_detection.extract_frames", return_value=_FakeFrameExtractor(frames))

    request = _make_request(load_result, scene_result, weights=DEFAULT_WEIGHTS)

    with detect_replays(request) as detector:
        result = detector.run()

    assert result.segments == ()


# --- US1: minimum-duration filtering -----------------------------------------


def test_segment_shorter_than_minimum_duration_is_never_reported(mocker):
    boundary = SceneBoundary(
        boundary_id=0, timestamp_seconds=10.0, boundary_type=BoundaryType.REPLAY_TRANSITION, confidence=1.0
    )
    load_result = _dummy_load_result(duration_seconds=20.0)
    scene_result = SceneDetectionResult(source_video_id=load_result.source.file_hash, boundaries=[boundary])
    frames = _one_fps_frames(20.0)
    mocker.patch("cvip.video.replay_detection.extract_frames", return_value=_FakeFrameExtractor(frames))

    # The segment [10.0, 20.0) is 10s long -- well above a 3s minimum, so use
    # a second boundary right after it to shrink it to 1s, below the minimum.
    boundary2 = SceneBoundary(
        boundary_id=1, timestamp_seconds=11.0, boundary_type=BoundaryType.ORDINARY_CUT, confidence=0.9
    )
    scene_result = SceneDetectionResult(
        source_video_id=load_result.source.file_hash, boundaries=[boundary, boundary2]
    )

    request = _make_request(
        load_result, scene_result, weights=TRANSITION_HEAVY_WEIGHTS, min_segment_seconds=3.0
    )

    with detect_replays(request) as detector:
        result = detector.run()

    assert not any(s.start_seconds == pytest.approx(10.0) for s in result.segments)


# --- US1: no replay footage at all -------------------------------------------


def test_video_with_no_strong_signal_yields_empty_segment_list(mocker):
    boundary = SceneBoundary(
        boundary_id=0, timestamp_seconds=10.0, boundary_type=BoundaryType.ORDINARY_CUT, confidence=0.9
    )
    load_result = _dummy_load_result(duration_seconds=20.0)
    scene_result = SceneDetectionResult(source_video_id=load_result.source.file_hash, boundaries=[boundary])
    frames = _one_fps_frames(20.0)
    mocker.patch("cvip.video.replay_detection.extract_frames", return_value=_FakeFrameExtractor(frames))

    request = _make_request(load_result, scene_result, weights=DEFAULT_WEIGHTS)

    with detect_replays(request) as detector:
        result = detector.run()

    assert result.segments == ()
    assert result.total_segments == 0
    assert result.total_replay_duration == 0.0


# --- US1: determinism ---------------------------------------------------------


def test_repeated_runs_produce_identical_segment_sequences(mocker):
    boundaries = [
        SceneBoundary(boundary_id=0, timestamp_seconds=5.0, boundary_type=BoundaryType.REPLAY_TRANSITION, confidence=1.0),
        SceneBoundary(boundary_id=1, timestamp_seconds=15.0, boundary_type=BoundaryType.ORDINARY_CUT, confidence=0.9),
    ]

    def run_once():
        load_result = _dummy_load_result(duration_seconds=25.0)
        scene_result = SceneDetectionResult(source_video_id=load_result.source.file_hash, boundaries=boundaries)
        frames = _one_fps_frames(25.0)
        mocker.patch("cvip.video.replay_detection.extract_frames", return_value=_FakeFrameExtractor(frames))
        request = _make_request(load_result, scene_result, weights=TRANSITION_HEAVY_WEIGHTS)
        with detect_replays(request) as detector:
            result = detector.run()
        return [(s.replay_id, s.start_seconds, s.end_seconds, s.confidence) for s in result.segments]

    first = run_once()
    second = run_once()
    third = run_once()

    assert first == second == third
    assert len(first) >= 1


# --- US2: result is self-contained -------------------------------------------


def test_result_source_video_id_matches_the_video_file_hash(mocker):
    load_result = _dummy_load_result(file_hash="cafef00d", duration_seconds=10.0)
    scene_result = SceneDetectionResult(source_video_id=load_result.source.file_hash)
    frames = _one_fps_frames(10.0)
    mocker.patch("cvip.video.replay_detection.extract_frames", return_value=_FakeFrameExtractor(frames))

    request = _make_request(load_result, scene_result)

    with detect_replays(request) as detector:
        result = detector.run()

    assert result.source_video_id == "cafef00d"


# --- US3: single forward pass, no backward seek ------------------------------


def test_single_forward_pass_no_backward_seek(mocker):
    real_video_capture_cls = cv2.VideoCapture
    seek_positions = []

    class _SpyCapture:
        def __init__(self, path):
            self._real = real_video_capture_cls(path)

        def isOpened(self):
            return self._real.isOpened()

        def set(self, prop, value):
            if prop == cv2.CAP_PROP_POS_FRAMES:
                seek_positions.append(int(value))
            return self._real.set(prop, value)

        def read(self):
            return self._real.read()

        def get(self, prop):
            return self._real.get(prop)

        def release(self):
            return self._real.release()

    mocker.patch("cv2.VideoCapture", side_effect=_SpyCapture)

    load_result = _load("valid_short.mp4")
    scene_result = SceneDetectionResult(source_video_id=load_result.source.file_hash)
    request = _make_request(load_result, scene_result)

    with detect_replays(request) as detector:
        detector.run()

    # The Frame Extraction Service performs a one-time O(1) two-point
    # calibration probe (seek to frame 0, then to the last frame) before the
    # real FIXED_INTERVAL extraction pass begins (frame_extraction.py's
    # `_calibrate_effective_fps`) -- a documented, already-accepted behavior
    # of Module 1a itself, not a re-decode of anything this feature already
    # processed. The guarantee this test actually checks (FR-019/SC-005) is
    # that the real extraction pass itself never seeks backward or repeats.
    assert len(seek_positions) > 2
    extraction_seeks = seek_positions[2:]
    assert extraction_seeks == sorted(extraction_seeks)
    assert len(extraction_seeks) == len(set(extraction_seeks))


# --- US3: mid-run failures, each with exactly one diagnostics record --------


def test_source_unavailable_mid_run_raises_specific_reason_with_one_diagnostics(mocker):
    load_result = _dummy_load_result(duration_seconds=20.0)
    scene_result = SceneDetectionResult(source_video_id=load_result.source.file_hash)
    frames = _one_fps_frames(20.0)[:5]
    mocker.patch(
        "cvip.video.replay_detection.extract_frames",
        return_value=_FakeFrameExtractor(
            frames, error=ExtractionError(ExtractionFailureReason.SOURCE_UNAVAILABLE_MID_RUN, "gone")
        ),
    )
    emit_spy = mocker.patch("cvip.video.replay_detection.emit_diagnostics")

    request = _make_request(load_result, scene_result)

    with pytest.raises(ReplayDetectionError) as exc_info:
        with detect_replays(request) as detector:
            detector.run()

    assert exc_info.value.reason == ReplayDetectionFailureReason.SOURCE_UNAVAILABLE_MID_RUN
    assert emit_spy.call_count == 1


def test_decode_failure_mid_run_raises_specific_reason_with_one_diagnostics(mocker):
    load_result = _dummy_load_result(duration_seconds=20.0)
    scene_result = SceneDetectionResult(source_video_id=load_result.source.file_hash)
    frames = _one_fps_frames(20.0)[:5]
    mocker.patch(
        "cvip.video.replay_detection.extract_frames",
        return_value=_FakeFrameExtractor(
            frames, error=ExtractionError(ExtractionFailureReason.DECODE_FAILURE_MID_RUN, "bad frame")
        ),
    )
    emit_spy = mocker.patch("cvip.video.replay_detection.emit_diagnostics")

    request = _make_request(load_result, scene_result)

    with pytest.raises(ReplayDetectionError) as exc_info:
        with detect_replays(request) as detector:
            detector.run()

    assert exc_info.value.reason == ReplayDetectionFailureReason.DECODE_FAILURE_MID_RUN
    assert emit_spy.call_count == 1


# --- US3: invalid Scene Detection result, exactly one diagnostics record ----


def test_mismatched_scene_detection_result_rejected_with_one_diagnostics(mocker):
    load_result = _dummy_load_result(file_hash="aaaa", duration_seconds=20.0)
    scene_result = SceneDetectionResult(source_video_id="totally-different-video")
    mock_extract = mocker.patch("cvip.video.replay_detection.extract_frames")
    emit_spy = mocker.patch("cvip.video.replay_detection.emit_diagnostics")

    request = _make_request(load_result, scene_result)

    with pytest.raises(ReplayDetectionError) as exc_info:
        with detect_replays(request) as detector:
            detector.run()

    assert exc_info.value.reason == ReplayDetectionFailureReason.INVALID_SCENE_DETECTION_RESULT
    mock_extract.assert_not_called()
    assert emit_spy.call_count == 1


def test_malformed_boundaries_list_rejected_with_one_diagnostics(mocker):
    """PR review finding: a SceneDetectionResult that matches this video's
    source_video_id but has a malformed boundary list (here, `boundaries`
    itself is None) must still be rejected with
    INVALID_SCENE_DETECTION_RESULT before any frame is processed, rather
    than reaching _build_candidate_segments() and raising an untyped
    exception."""
    load_result = _dummy_load_result(duration_seconds=20.0)
    scene_result = SceneDetectionResult(source_video_id=load_result.source.file_hash, boundaries=None)
    mock_extract = mocker.patch("cvip.video.replay_detection.extract_frames")
    emit_spy = mocker.patch("cvip.video.replay_detection.emit_diagnostics")

    request = _make_request(load_result, scene_result)

    with pytest.raises(ReplayDetectionError) as exc_info:
        with detect_replays(request) as detector:
            detector.run()

    assert exc_info.value.reason == ReplayDetectionFailureReason.INVALID_SCENE_DETECTION_RESULT
    mock_extract.assert_not_called()
    assert emit_spy.call_count == 1


def test_malformed_boundary_entry_rejected_with_one_diagnostics(mocker):
    """PR review finding: a boundary entry missing a valid timestamp is
    malformed, not just a missing/mismatched result -- must also be
    rejected with INVALID_SCENE_DETECTION_RESULT."""

    class _BrokenBoundary:
        boundary_type = BoundaryType.ORDINARY_CUT
        confidence = 0.9
        # deliberately no timestamp_seconds attribute at all

    load_result = _dummy_load_result(duration_seconds=20.0)
    scene_result = SceneDetectionResult(
        source_video_id=load_result.source.file_hash, boundaries=[_BrokenBoundary()]
    )
    mock_extract = mocker.patch("cvip.video.replay_detection.extract_frames")
    emit_spy = mocker.patch("cvip.video.replay_detection.emit_diagnostics")

    request = _make_request(load_result, scene_result)

    with pytest.raises(ReplayDetectionError) as exc_info:
        with detect_replays(request) as detector:
            detector.run()

    assert exc_info.value.reason == ReplayDetectionFailureReason.INVALID_SCENE_DETECTION_RESULT
    mock_extract.assert_not_called()
    assert emit_spy.call_count == 1


# --- US3: invalid configuration, each independently, one diagnostics record -


def test_weight_sum_not_one_rejected_with_one_diagnostics(mocker):
    load_result = _dummy_load_result(duration_seconds=20.0)
    scene_result = SceneDetectionResult(source_video_id=load_result.source.file_hash)
    mock_extract = mocker.patch("cvip.video.replay_detection.extract_frames")
    emit_spy = mocker.patch("cvip.video.replay_detection.emit_diagnostics")

    bad_weights = dict(DEFAULT_WEIGHTS)
    bad_weights["logo_weight"] = 0.45  # sum now 1.1
    request = _make_request(load_result, scene_result, weights=bad_weights)

    with pytest.raises(ReplayDetectionError) as exc_info:
        with detect_replays(request) as detector:
            detector.run()

    assert exc_info.value.reason == ReplayDetectionFailureReason.INVALID_REPLAY_CONFIGURATION
    mock_extract.assert_not_called()
    assert emit_spy.call_count == 1


def test_threshold_out_of_range_rejected_with_one_diagnostics(mocker):
    load_result = _dummy_load_result(duration_seconds=20.0)
    scene_result = SceneDetectionResult(source_video_id=load_result.source.file_hash)
    mock_extract = mocker.patch("cvip.video.replay_detection.extract_frames")
    emit_spy = mocker.patch("cvip.video.replay_detection.emit_diagnostics")

    request = _make_request(load_result, scene_result, confidence_threshold=1.5)

    with pytest.raises(ReplayDetectionError) as exc_info:
        with detect_replays(request) as detector:
            detector.run()

    assert exc_info.value.reason == ReplayDetectionFailureReason.INVALID_REPLAY_CONFIGURATION
    mock_extract.assert_not_called()
    assert emit_spy.call_count == 1


def test_min_segment_seconds_negative_rejected_with_one_diagnostics(mocker):
    load_result = _dummy_load_result(duration_seconds=20.0)
    scene_result = SceneDetectionResult(source_video_id=load_result.source.file_hash)
    mock_extract = mocker.patch("cvip.video.replay_detection.extract_frames")
    emit_spy = mocker.patch("cvip.video.replay_detection.emit_diagnostics")

    request = _make_request(load_result, scene_result, min_segment_seconds=-1.0)

    with pytest.raises(ReplayDetectionError) as exc_info:
        with detect_replays(request) as detector:
            detector.run()

    assert exc_info.value.reason == ReplayDetectionFailureReason.INVALID_REPLAY_CONFIGURATION
    mock_extract.assert_not_called()
    assert emit_spy.call_count == 1


def test_min_segment_seconds_non_finite_rejected_with_one_diagnostics(mocker):
    load_result = _dummy_load_result(duration_seconds=20.0)
    scene_result = SceneDetectionResult(source_video_id=load_result.source.file_hash)
    mock_extract = mocker.patch("cvip.video.replay_detection.extract_frames")
    emit_spy = mocker.patch("cvip.video.replay_detection.emit_diagnostics")

    request = _make_request(load_result, scene_result, min_segment_seconds=float("inf"))

    with pytest.raises(ReplayDetectionError) as exc_info:
        with detect_replays(request) as detector:
            detector.run()

    assert exc_info.value.reason == ReplayDetectionFailureReason.INVALID_REPLAY_CONFIGURATION
    mock_extract.assert_not_called()
    assert emit_spy.call_count == 1


# --- US3: cancellation ---------------------------------------------------------


def test_cancel_mid_detection_stops_cleanly_and_emits_once(mocker):
    boundary = SceneBoundary(
        boundary_id=0, timestamp_seconds=50.0, boundary_type=BoundaryType.REPLAY_TRANSITION, confidence=1.0
    )
    load_result = _dummy_load_result(duration_seconds=100.0)
    scene_result = SceneDetectionResult(source_video_id=load_result.source.file_hash, boundaries=[boundary])
    frames = _one_fps_frames(100.0)
    detector_holder = {}

    def frame_generator():
        for idx, frame_context in enumerate(frames):
            yield frame_context
            if idx == 10:
                detector_holder["detector"].cancel()

    mocker.patch(
        "cvip.video.replay_detection.extract_frames",
        return_value=_FakeFrameExtractor(frame_generator()),
    )
    emit_spy = mocker.patch("cvip.video.replay_detection.emit_diagnostics")

    request = _make_request(load_result, scene_result, weights=TRANSITION_HEAVY_WEIGHTS)

    with detect_replays(request) as detector:
        detector_holder["detector"] = detector
        result = detector.run()

    # Cancelled after 11 frames (well before the boundary at 50s), so the
    # only replay-eligible segment (which starts at 50s) is never reached.
    assert result.segments == ()
    assert emit_spy.call_count == 1


def test_cancel_inside_an_open_segment_truncates_reported_end_not_full_span(mocker):
    """PR review finding: cancelling partway through an in-flight candidate
    segment must not report the segment's full, original [start, end) span
    -- the footage after the cancellation point was never analyzed and must
    not be claimed as observed replay content. Mirrors the review's own
    example: a [50, 200) candidate cancelled at 60s must not be reported as
    ending at 200s."""
    boundary = SceneBoundary(
        boundary_id=0, timestamp_seconds=50.0, boundary_type=BoundaryType.REPLAY_TRANSITION, confidence=1.0
    )
    load_result = _dummy_load_result(duration_seconds=200.0)
    scene_result = SceneDetectionResult(source_video_id=load_result.source.file_hash, boundaries=[boundary])
    frames = _one_fps_frames(200.0)
    detector_holder = {}

    def frame_generator():
        for idx, frame_context in enumerate(frames):
            yield frame_context
            if idx == 60:  # last yielded frame has timestamp_seconds == 60.0
                detector_holder["detector"].cancel()

    mocker.patch(
        "cvip.video.replay_detection.extract_frames",
        return_value=_FakeFrameExtractor(frame_generator()),
    )

    request = _make_request(load_result, scene_result, weights=TRANSITION_HEAVY_WEIGHTS)

    with detect_replays(request) as detector:
        detector_holder["detector"] = detector
        result = detector.run()

    for segment in result.segments:
        assert segment.end_seconds <= 60.0, (
            f"segment end_seconds={segment.end_seconds} claims footage past the 60s "
            "cancellation point as observed replay content"
        )
    # The [50, 200) candidate's combined confidence (transition-heavy
    # weights, REPLAY_TRANSITION leading boundary) clears the threshold even
    # from partial evidence, so it should still be reported -- just
    # truncated to what was actually observed, not silently dropped.
    assert any(s.start_seconds == pytest.approx(50.0) and s.end_seconds == pytest.approx(60.0) for s in result.segments)
