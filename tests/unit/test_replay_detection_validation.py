"""Unit tests for Replay Detection internals: signal computations,
weight/threshold validation, baseline-tracker logic. See
specs/004-replay-detection/spec.md FR-007, FR-009, FR-010, FR-014, FR-018,
FR-020, FR-021, FR-029.
"""

import socket
from pathlib import Path

import cv2
import numpy as np
import pytest

from cvip.video.frame_extraction_models import FrameContext
from cvip.video.loader import load_video
from cvip.video.models import ContainerFormat, LoadResult, MatchVideoSource
from cvip.video.replay_detection import LiveActionBaselineTracker, ReplayDetector, detect_replays
from cvip.video.replay_detection_models import ReplayDetectionRequest, ReplayDetectionResult, ReplaySegment
from cvip.video.scene_detection_models import BoundaryType, SceneBoundary, SceneDetectionResult

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


def _make_detector(**overrides) -> ReplayDetector:
    load_result = overrides.pop("load_result", None) or _dummy_load_result()
    scene_result = overrides.pop("scene_detection_result", None) or SceneDetectionResult(
        source_video_id=load_result.source.file_hash
    )
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
    request = ReplayDetectionRequest(**fields)
    return ReplayDetector(request)


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


# --- FR-009: weighted-combination arithmetic ---------------------------------


def test_combined_confidence_is_the_configured_weighted_sum():
    detector = _make_detector()
    boundary = SceneBoundary(
        boundary_id=0, timestamp_seconds=1.0, boundary_type=BoundaryType.REPLAY_TRANSITION, confidence=0.8
    )
    finalized = []

    evidence = detector._finalize_segment((0.0, 1.0, boundary), None, LiveActionBaselineTracker(), finalized)

    expected = 0.0 * 0.35 + 0.5 * 0.20 + 0.5 * 0.20 + 0.8 * 0.15 + 0.5 * 0.10
    assert evidence.combined_confidence == pytest.approx(expected)


# --- FR-007: transition signal is an exact, unmodified reuse ----------------


def test_transition_score_exactly_reuses_scene_detection_confidence():
    detector = _make_detector()
    boundary = SceneBoundary(
        boundary_id=0, timestamp_seconds=1.0, boundary_type=BoundaryType.REPLAY_TRANSITION, confidence=0.8231
    )

    evidence = detector._finalize_segment((0.0, 1.0, boundary), None, LiveActionBaselineTracker(), [])

    assert evidence.transition_score == 0.8231


def test_transition_score_is_zero_for_ordinary_cut():
    detector = _make_detector()
    boundary = SceneBoundary(
        boundary_id=0, timestamp_seconds=1.0, boundary_type=BoundaryType.ORDINARY_CUT, confidence=0.9
    )

    evidence = detector._finalize_segment((0.0, 1.0, boundary), None, LiveActionBaselineTracker(), [])

    assert evidence.transition_score == 0.0


def test_transition_score_is_zero_when_segment_has_no_leading_boundary():
    detector = _make_detector()

    evidence = detector._finalize_segment((0.0, 1.0, None), None, LiveActionBaselineTracker(), [])

    assert evidence.transition_score == 0.0


# --- FR-015: logo signal degrades gracefully with no template configured ----


def test_logo_score_is_zero_when_no_template_configured():
    detector = _make_detector()
    frame = _solid_frame(128)

    assert detector._logo_match_score(frame, None) == 0.0


def test_logo_score_is_zero_when_template_path_does_not_load(tmp_path):
    detector = _make_detector()
    frame = _solid_frame(128)
    missing_path = str(tmp_path / "does_not_exist.png")

    assert detector._logo_match_score(frame, missing_path) == 0.0


def test_logo_score_is_zero_when_template_larger_than_frame(tmp_path):
    detector = _make_detector()
    frame = _solid_frame(128, size=(16, 16, 3))
    template_path = tmp_path / "template.png"
    cv2.imwrite(str(template_path), _solid_frame(200, size=(32, 32, 3)))

    assert detector._logo_match_score(frame, str(template_path)) == 0.0


def _gradient_frame(size=(32, 32, 3)) -> np.ndarray:
    height, width, channels = size
    frame = np.zeros(size, dtype="uint8")
    for x in range(width):
        frame[:, x, :] = (x * 7) % 256
    return frame


def test_logo_score_reflects_a_genuine_template_match(tmp_path):
    detector = _make_detector()
    frame = _gradient_frame()
    template_path = tmp_path / "template.png"
    # An exact crop of the frame's own top-left corner -- guarantees a
    # well-defined (non-degenerate, non-constant) template with a true
    # best-match location, unlike a solid-color frame/template pair (whose
    # normalized cross-correlation is mathematically undefined, 0/0).
    cv2.imwrite(str(template_path), frame[0:8, 0:8, :])

    score = detector._logo_match_score(frame, str(template_path))

    assert score == pytest.approx(1.0, abs=1e-2)


# --- FR-008: degenerate scoreboard ROI -----------------------------------


def test_scoreboard_signal_is_zero_for_a_degenerate_roi():
    detector = _make_detector()
    frame = _solid_frame(128)

    # A region entirely outside the frame collapses to an empty ROI.
    assert detector._scoreboard_content_signal(frame, (1.5, 0.0, 0.1, 0.1)) == 0.0


# --- Baseline-relative deviation scoring: undefined (zero) baseline --------


def test_deviation_score_is_zero_when_baseline_is_not_positive():
    detector = _make_detector()

    assert detector._deviation_score(segment_value=10.0, baseline_value=0.0) == 0.0


# --- Candidate segment construction: zero-length segments are skipped ------


def test_zero_length_candidate_segment_from_duplicate_boundary_is_skipped():
    detector = _make_detector()
    boundary_at_start = SceneBoundary(
        boundary_id=0, timestamp_seconds=0.0, boundary_type=BoundaryType.ORDINARY_CUT, confidence=0.9
    )
    scene_result = SceneDetectionResult(source_video_id="deadbeef", boundaries=[boundary_at_start])

    segments = detector._build_candidate_segments(scene_result, duration_seconds=10.0)

    # The synthetic start (0.0) and the boundary at 0.0 collapse to a
    # zero-length first segment, which must be skipped rather than reported.
    assert all(end > start for start, end, _ in segments)
    assert segments == [(0.0, 10.0, boundary_at_start)]


# --- Mid-run failure: an unexpected processing error still maps to a typed -
# --- failure reason (not an untyped crash) ----------------------------------


def test_unexpected_processing_error_mid_run_raises_decode_failure_reason(mocker):
    """Regression: an unexpected error while processing an otherwise-
    successfully-decoded frame (here, a frame-shape mismatch reaching
    cv2.absdiff) must still surface as this module's own typed failure
    (FR-022), not an untyped crash -- mirrors Scene Detection's own
    regression test for the same class of bug."""
    load_result = _dummy_load_result(duration_seconds=20.0)
    scene_result = SceneDetectionResult(source_video_id=load_result.source.file_hash)
    frames = [
        FrameContext(
            source_video_id="deadbeef", frame_index=0, timestamp_seconds=0.0, frame=_solid_frame(0, size=(32, 32, 3))
        ),
        FrameContext(
            source_video_id="deadbeef", frame_index=1, timestamp_seconds=1.0, frame=_solid_frame(0, size=(16, 16, 3))
        ),
    ]
    mocker.patch("cvip.video.replay_detection.extract_frames", return_value=_FakeFrameExtractor(frames))

    request = ReplayDetectionRequest(
        load_result=load_result,
        scene_detection_result=scene_result,
        confidence_threshold=0.65,
        min_segment_seconds=3.0,
        scoreboard_region=(0.0, 0.0, 0.2, 0.1),
        logo_template_path=None,
        **DEFAULT_WEIGHTS,
    )

    from cvip.video.replay_detection_errors import ReplayDetectionError

    with pytest.raises(ReplayDetectionError) as exc_info:
        with detect_replays(request) as detector:
            detector.run()

    from cvip.video.replay_detection_errors import ReplayDetectionFailureReason

    assert exc_info.value.reason == ReplayDetectionFailureReason.DECODE_FAILURE_MID_RUN


# --- FR-004/FR-020/FR-021: frame sourcing, offline, CPU-only ----------------


def test_frames_sourced_exclusively_via_extract_frames_not_cv2_directly(mocker):
    load_result = _load("valid_short.mp4")
    scene_result = SceneDetectionResult(source_video_id=load_result.source.file_hash)

    frames = [
        FrameContext(source_video_id="deadbeef", frame_index=i, timestamp_seconds=float(i), frame=_solid_frame(0))
        for i in range(5)
    ]
    mock_extract = mocker.patch(
        "cvip.video.replay_detection.extract_frames", return_value=_FakeFrameExtractor(frames)
    )
    mock_capture = mocker.patch("cv2.VideoCapture")

    request = ReplayDetectionRequest(
        load_result=load_result,
        scene_detection_result=scene_result,
        confidence_threshold=0.65,
        min_segment_seconds=3.0,
        scoreboard_region=(0.0, 0.0, 0.2, 0.1),
        logo_template_path=None,
        **DEFAULT_WEIGHTS,
    )

    with detect_replays(request) as detector:
        detector.run()

    mock_extract.assert_called_once()
    mock_capture.assert_not_called()


def test_detection_makes_no_network_calls(mocker):
    def _fail_if_called(*args, **kwargs):
        raise AssertionError("detection must not create network sockets")

    mocker.patch.object(socket, "socket", side_effect=_fail_if_called)
    mocker.patch.object(socket, "create_connection", side_effect=_fail_if_called)

    load_result = _load("valid_short.mp4")
    scene_result = SceneDetectionResult(source_video_id=load_result.source.file_hash)
    request = ReplayDetectionRequest(
        load_result=load_result,
        scene_detection_result=scene_result,
        confidence_threshold=0.65,
        min_segment_seconds=3.0,
        scoreboard_region=(0.0, 0.0, 0.2, 0.1),
        logo_template_path=None,
        **DEFAULT_WEIGHTS,
    )

    with detect_replays(request) as detector:
        result = detector.run()

    assert result is not None


def test_no_gpu_specific_opencv_api_is_used():
    source_dir = Path(__file__).parent.parent.parent / "src" / "cvip" / "video"
    for filename in ("replay_detection.py", "replay_detection_models.py", "replay_detection_errors.py"):
        text = (source_dir / filename).read_text(encoding="utf-8")
        assert "cv2.cuda" not in text, f"{filename} must not use GPU-specific OpenCV APIs"
        assert "cuda" not in text.lower(), f"{filename} must not reference CUDA/GPU APIs"


# --- FR-018: deterministic secondary ordering --------------------------------


def test_tied_start_ordered_by_end_then_stable_input_order():
    detector = _make_detector()
    from cvip.video.replay_detection_models import ReplayEvidence

    def _evidence(confidence):
        return ReplayEvidence(
            logo_score=0.0, scoreboard_score=0.0, motion_score=0.0, transition_score=0.0,
            camera_angle_score=0.0, combined_confidence=confidence,
        )

    finalized = [
        (5.0, 6.0, _evidence(0.7)),
        (2.0, 5.0, _evidence(0.8)),
        (2.0, 4.0, _evidence(0.9)),
    ]

    segments = detector._finalize_result_segments(finalized)

    assert [(s.start_seconds, s.end_seconds) for s in segments] == [(2.0, 4.0), (2.0, 5.0), (5.0, 6.0)]


def test_true_ties_preserve_stable_input_order():
    detector = _make_detector()
    from cvip.video.replay_detection_models import ReplayEvidence

    def _evidence(confidence):
        return ReplayEvidence(
            logo_score=0.0, scoreboard_score=0.0, motion_score=0.0, transition_score=0.0,
            camera_angle_score=0.0, combined_confidence=confidence,
        )

    finalized = [(2.0, 4.0, _evidence(0.66)), (2.0, 4.0, _evidence(0.99))]

    segments = detector._finalize_result_segments(finalized)

    assert [s.confidence for s in segments] == [0.66, 0.99]


# --- FR-014/SC-011: replay_id uniqueness -------------------------------------


def test_replay_ids_are_unique_and_sequential():
    detector = _make_detector()
    from cvip.video.replay_detection_models import ReplayEvidence

    def _evidence(confidence):
        return ReplayEvidence(
            logo_score=0.0, scoreboard_score=0.0, motion_score=0.0, transition_score=0.0,
            camera_angle_score=0.0, combined_confidence=confidence,
        )

    finalized = [(0.0, 1.0, _evidence(0.7)), (2.0, 3.0, _evidence(0.8)), (4.0, 5.0, _evidence(0.9))]

    segments = detector._finalize_result_segments(finalized)

    ids = [s.replay_id for s in segments]
    assert ids == [0, 1, 2]
    assert len(ids) == len(set(ids))


# --- FR-029: per-segment aggregation is the mean, not peak/majority-vote ----


def test_baseline_relative_signal_uses_mean_not_peak_of_sampled_frames():
    detector = _make_detector()
    baseline = LiveActionBaselineTracker()
    reference_fingerprint = np.array([50.0, 10.0])
    for _ in range(3):
        baseline.update(100.0, 100.0, reference_fingerprint)
    assert baseline.is_warmed_up

    accum = {
        "frame_count": 3,
        "logo_scores": [0.0, 0.0, 0.0],
        "scoreboard_raw": [60.0, 80.0, 100.0],  # mean=80, peak=100, min=60
        "motion_raw": [100.0, 100.0, 100.0],
        "fingerprint_sum": reference_fingerprint * 3,
    }

    evidence = detector._finalize_segment((0.0, 5.0, None), accum, baseline, [])

    # deviation_score(mean=80, baseline=100) == 0.2; a peak-based (100) or
    # min-based (60) aggregation would yield 0.0 or 0.4 instead.
    assert evidence.scoreboard_score == pytest.approx(0.2)


# --- Cold-start handling: neutral 0.5 for baseline-relative signals ---------


def test_cold_start_yields_neutral_score_for_baseline_relative_signals():
    detector = _make_detector()
    baseline = LiveActionBaselineTracker()
    assert not baseline.is_warmed_up

    accum = {
        "frame_count": 2,
        "logo_scores": [0.0, 0.0],
        "scoreboard_raw": [10.0, 20.0],
        "motion_raw": [10.0, 20.0],
        "fingerprint_sum": np.array([5.0, 5.0]),
    }

    evidence = detector._finalize_segment((0.0, 2.0, None), accum, baseline, [])

    assert evidence.scoreboard_score == 0.5
    assert evidence.motion_score == 0.5
    assert evidence.camera_angle_score == 0.5


# --- US2: result shape is genuinely immutable --------------------------------


def test_replay_segment_is_frozen():
    segment = ReplaySegment(replay_id=0, start_seconds=0.0, end_seconds=1.0, confidence=0.7)
    with pytest.raises(Exception):
        segment.confidence = 0.9  # type: ignore[misc]


def test_replay_detection_result_is_frozen_and_segments_is_a_tuple():
    result = ReplayDetectionResult(source_video_id="deadbeef", segments=(), total_segments=0, total_replay_duration=0.0)
    with pytest.raises(Exception):
        result.total_segments = 5  # type: ignore[misc]
    assert isinstance(result.segments, tuple)


# --- FR-025: diagnostics field completeness, and partial-state preservation -


_TRANSITION_HEAVY_WEIGHTS = dict(
    logo_weight=0.075, scoreboard_weight=0.075, motion_weight=0.075, transition_weight=0.70, camera_angle_weight=0.075
)


def _one_fps_frames(duration_seconds, source_video_id="deadbeef"):
    return [
        FrameContext(
            source_video_id=source_video_id, frame_index=i, timestamp_seconds=float(i), frame=_solid_frame(0)
        )
        for i in range(int(duration_seconds))
    ]


def test_diagnostics_contains_every_required_field_on_success(mocker):
    load_result = _dummy_load_result(duration_seconds=20.0)
    boundary = SceneBoundary(
        boundary_id=0, timestamp_seconds=10.0, boundary_type=BoundaryType.REPLAY_TRANSITION, confidence=1.0
    )
    scene_result = SceneDetectionResult(source_video_id=load_result.source.file_hash, boundaries=[boundary])
    frames = _one_fps_frames(20.0)
    mocker.patch("cvip.video.replay_detection.extract_frames", return_value=_FakeFrameExtractor(frames))
    emit_spy = mocker.patch("cvip.video.replay_detection.emit_diagnostics")

    request = ReplayDetectionRequest(
        load_result=load_result,
        scene_detection_result=scene_result,
        confidence_threshold=0.65,
        min_segment_seconds=3.0,
        scoreboard_region=(0.0, 0.0, 0.2, 0.1),
        logo_template_path=None,
        **_TRANSITION_HEAVY_WEIGHTS,
    )

    with detect_replays(request) as detector:
        detector.run()

    assert emit_spy.call_count == 1
    output_summary = emit_spy.call_args[0][0].output_summary
    for field_name in (
        "candidate_segments_evaluated=",
        "replay_segments_accepted=",
        "replay_segments_rejected=",
        "average_confidence=",
        "highest_confidence=",
        "longest_replay_duration=",
        "total_replay_duration=",
        "sampling_rate_used=",
    ):
        assert field_name in output_summary, f"{field_name!r} missing from diagnostics output_summary"
    assert "replay_segments_accepted=1" in output_summary


def test_diagnostics_preserve_partial_progress_on_mid_run_failure(mocker):
    from cvip.video.frame_extraction_errors import ExtractionError, ExtractionFailureReason
    from cvip.video.replay_detection_errors import ReplayDetectionError

    load_result = _dummy_load_result(duration_seconds=30.0)
    boundary = SceneBoundary(
        boundary_id=0, timestamp_seconds=10.0, boundary_type=BoundaryType.REPLAY_TRANSITION, confidence=1.0
    )
    boundary2 = SceneBoundary(
        boundary_id=1, timestamp_seconds=20.0, boundary_type=BoundaryType.ORDINARY_CUT, confidence=0.9
    )
    scene_result = SceneDetectionResult(
        source_video_id=load_result.source.file_hash, boundaries=[boundary, boundary2]
    )
    # Frames covering the first two segments ([0,10) and [10,20)) plus a
    # couple into the third, then a mid-run failure -- the first replay
    # segment ([10,20), REPLAY_TRANSITION) should already have been accepted
    # and finalized by the time the failure hits.
    frames = _one_fps_frames(30.0)[:22]
    mocker.patch(
        "cvip.video.replay_detection.extract_frames",
        return_value=_FakeFrameExtractor(
            frames, error=ExtractionError(ExtractionFailureReason.SOURCE_UNAVAILABLE_MID_RUN, "gone")
        ),
    )
    emit_spy = mocker.patch("cvip.video.replay_detection.emit_diagnostics")

    request = ReplayDetectionRequest(
        load_result=load_result,
        scene_detection_result=scene_result,
        confidence_threshold=0.65,
        min_segment_seconds=3.0,
        scoreboard_region=(0.0, 0.0, 0.2, 0.1),
        logo_template_path=None,
        **_TRANSITION_HEAVY_WEIGHTS,
    )

    with pytest.raises(ReplayDetectionError):
        with detect_replays(request) as detector:
            detector.run()

    assert emit_spy.call_count == 1
    output_summary = emit_spy.call_args[0][0].output_summary
    assert "replay_segments_accepted=1" in output_summary
