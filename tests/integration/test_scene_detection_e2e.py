"""Integration tests for Scene Detection: real fixture files (reused from
Video Loader), full detect_scenes() calls. See
specs/003-scene-detection/spec.md User Stories 1-3.
"""

from pathlib import Path

import cv2
import numpy as np
import pytest

from cvip.video.frame_extraction_models import FrameContext
from cvip.video.loader import load_video
from cvip.video.scene_detection import detect_scenes
from cvip.video.scene_detection_errors import SceneDetectionError, SceneDetectionFailureReason
from cvip.video.scene_detection_models import BoundaryType, SceneDetectionRequest

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


class _FakeFrameExtractor:
    """A minimal stand-in for FrameExtractor: a context manager yielding a
    caller-supplied list of FrameContext objects, used to feed Scene
    Detection deterministic, synthetic frame content without a real video
    file (e.g., a controlled hard cut at a known frame index)."""

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


def _solid_frame(value: int, size=(32, 32, 3)) -> np.ndarray:
    return np.full(size, value, dtype="uint8")


def _two_segment_frame_contexts(source_video_id="deadbeef", fps=25.0, segment_frames=40):
    """A synthetic sequence: `segment_frames` black frames, then
    `segment_frames` white frames -- one unambiguous hard cut at the
    boundary between the two segments."""
    frames = []
    total = segment_frames * 2
    for i in range(total):
        value = 0 if i < segment_frames else 255
        frames.append(
            FrameContext(
                source_video_id=source_video_id,
                frame_index=i,
                timestamp_seconds=i / fps,
                frame=_solid_frame(value),
            )
        )
    return frames


def _three_segment_frame_contexts(source_video_id="deadbeef", fps=25.0, segment_frames=40):
    """Three segments (black, white, black) -- two unambiguous hard cuts."""
    frames = []
    total = segment_frames * 3
    values = [0, 255, 0]
    for i in range(total):
        value = values[i // segment_frames] if i // segment_frames < 3 else values[-1]
        frames.append(
            FrameContext(
                source_video_id=source_video_id,
                frame_index=i,
                timestamp_seconds=i / fps,
                frame=_solid_frame(value),
            )
        )
    return frames


def _closely_spaced_cuts_frame_contexts(source_video_id="deadbeef", fps=25.0, gap_frames=10):
    """Two genuinely distinct ordinary cuts `gap_frames` apart -- closer
    than PySceneDetect's own default min_scene_len (15), which would
    silently drop the second one if left at its default."""
    frames = []
    values = [0, 255, 0]
    boundaries_at = [20, 20 + gap_frames]
    value_index = 0
    for i in range(20 + gap_frames + 20):
        if value_index < len(boundaries_at) and i == boundaries_at[value_index]:
            value_index += 1
        frames.append(
            FrameContext(
                source_video_id=source_video_id,
                frame_index=i,
                timestamp_seconds=i / fps,
                frame=_solid_frame(values[value_index]),
            )
        )
    return frames


# --- User Story 1: structural correctness against a real fixture -----------


def test_detection_against_real_fixture_yields_valid_structural_result(mocker):
    load_result = _load("valid_short.mp4")
    request = SceneDetectionRequest(load_result=load_result, scene_threshold=27.0)

    emit_spy = mocker.patch("cvip.video.scene_detection.emit_diagnostics")

    with detect_scenes(request) as detector:
        result = detector.run()

    timestamps = [b.timestamp_seconds for b in result.boundaries]
    assert timestamps == sorted(timestamps)
    assert len(timestamps) == len(set(timestamps))

    assert result.total_boundaries == len(result.boundaries)
    assert result.replay_transition_count == sum(
        1 for b in result.boundaries if b.boundary_type == BoundaryType.REPLAY_TRANSITION
    )
    assert result.processing_duration > 0
    assert result.configuration_version is not None

    assert emit_spy.call_count == 1


def test_detected_boundary_has_correct_frame_index_and_timestamp(mocker):
    frames = _two_segment_frame_contexts(segment_frames=40)
    mocker.patch(
        "cvip.video.scene_detection.extract_frames",
        return_value=_FakeFrameExtractor(frames),
    )

    load_result = _load("valid_short.mp4")
    request = SceneDetectionRequest(load_result=load_result, scene_threshold=27.0)

    with detect_scenes(request) as detector:
        result = detector.run()

    assert len(result.boundaries) >= 1
    boundary = result.boundaries[0]
    assert boundary.timestamp_seconds == pytest.approx(40 / 25.0, abs=1 / 25.0)


def test_two_distinct_cuts_closer_than_15_frames_are_both_detected(mocker):
    """Regression: two genuinely distinct ordinary cuts spaced 10 frames
    apart -- closer than PySceneDetect's own default min_scene_len (15) --
    must both be reported (FR-006), not have the second silently dropped."""
    frames = _closely_spaced_cuts_frame_contexts(gap_frames=10)
    mocker.patch(
        "cvip.video.scene_detection.extract_frames",
        return_value=_FakeFrameExtractor(frames),
    )

    load_result = _load("valid_short.mp4")
    request = SceneDetectionRequest(load_result=load_result, scene_threshold=27.0)

    with detect_scenes(request) as detector:
        result = detector.run()

    assert len(result.boundaries) == 2
    assert all(b.boundary_type == BoundaryType.ORDINARY_CUT for b in result.boundaries)


# --- User Story 1: no-cuts edge case ----------------------------------------


def test_single_continuous_shot_yields_empty_boundary_list(mocker):
    frames = [
        FrameContext(
            source_video_id="deadbeef",
            frame_index=i,
            timestamp_seconds=i / 25.0,
            frame=_solid_frame(128),
        )
        for i in range(50)
    ]
    mocker.patch(
        "cvip.video.scene_detection.extract_frames",
        return_value=_FakeFrameExtractor(frames),
    )

    load_result = _load("valid_short.mp4")
    request = SceneDetectionRequest(load_result=load_result, scene_threshold=27.0)

    with detect_scenes(request) as detector:
        result = detector.run()

    assert result.boundaries == []


# --- User Story 1: mid-run failures -----------------------------------------


def test_source_unavailable_mid_run_raises_specific_reason(mocker):
    from cvip.video.frame_extraction_errors import ExtractionError, ExtractionFailureReason

    frames = _two_segment_frame_contexts(segment_frames=5)[:3]
    mocker.patch(
        "cvip.video.scene_detection.extract_frames",
        return_value=_FakeFrameExtractor(
            frames, error=ExtractionError(ExtractionFailureReason.SOURCE_UNAVAILABLE_MID_RUN, "gone")
        ),
    )

    load_result = _load("valid_short.mp4")
    request = SceneDetectionRequest(load_result=load_result, scene_threshold=27.0)

    with pytest.raises(SceneDetectionError) as exc_info:
        with detect_scenes(request) as detector:
            detector.run()

    assert exc_info.value.reason == SceneDetectionFailureReason.SOURCE_UNAVAILABLE_MID_RUN


def test_unexpected_processing_error_mid_run_raises_decode_failure_reason(mocker):
    """Regression: an unexpected error while processing an otherwise-
    successfully-decoded frame (here, a frame-shape mismatch reaching
    cv2.absdiff) must still surface as this module's own typed failure
    (FR-018), not an untyped crash."""
    frames = [
        FrameContext(
            source_video_id="deadbeef", frame_index=0, timestamp_seconds=0.0, frame=_solid_frame(0, size=(32, 32, 3))
        ),
        FrameContext(
            source_video_id="deadbeef", frame_index=1, timestamp_seconds=0.04, frame=_solid_frame(0, size=(16, 16, 3))
        ),
    ]
    mocker.patch(
        "cvip.video.scene_detection.extract_frames",
        return_value=_FakeFrameExtractor(frames),
    )

    load_result = _load("valid_short.mp4")
    request = SceneDetectionRequest(load_result=load_result, scene_threshold=27.0)

    with pytest.raises(SceneDetectionError) as exc_info:
        with detect_scenes(request) as detector:
            detector.run()

    assert exc_info.value.reason == SceneDetectionFailureReason.DECODE_FAILURE_MID_RUN


def test_diagnostics_preserve_partial_boundaries_on_mid_run_failure(mocker):
    """Regression: a mid-run failure's diagnostics record must reflect
    boundaries already classified before the failure, not report
    boundaries_detected=0 for a run that actually found some (FR-015/FR-019
    'summarizing the partial run')."""
    from cvip.video.frame_extraction_errors import ExtractionError, ExtractionFailureReason

    # segment_frames=10 -> cut at frame 10, window closes by frame 13
    # (well before the injected failure at frame 15).
    frames = _two_segment_frame_contexts(segment_frames=10)[:15]
    mocker.patch(
        "cvip.video.scene_detection.extract_frames",
        return_value=_FakeFrameExtractor(
            frames, error=ExtractionError(ExtractionFailureReason.SOURCE_UNAVAILABLE_MID_RUN, "gone")
        ),
    )
    emit_spy = mocker.patch("cvip.video.scene_detection.emit_diagnostics")

    load_result = _load("valid_short.mp4")
    request = SceneDetectionRequest(load_result=load_result, scene_threshold=27.0)

    with pytest.raises(SceneDetectionError):
        with detect_scenes(request) as detector:
            detector.run()

    assert emit_spy.call_count == 1
    diagnostics = emit_spy.call_args[0][0]
    assert "boundaries_detected=1" in diagnostics.output_summary


def test_decode_failure_mid_run_raises_specific_reason(mocker):
    from cvip.video.frame_extraction_errors import ExtractionError, ExtractionFailureReason

    frames = _two_segment_frame_contexts(segment_frames=5)[:3]
    mocker.patch(
        "cvip.video.scene_detection.extract_frames",
        return_value=_FakeFrameExtractor(
            frames, error=ExtractionError(ExtractionFailureReason.DECODE_FAILURE_MID_RUN, "bad frame")
        ),
    )

    load_result = _load("valid_short.mp4")
    request = SceneDetectionRequest(load_result=load_result, scene_threshold=27.0)

    with pytest.raises(SceneDetectionError) as exc_info:
        with detect_scenes(request) as detector:
            detector.run()

    assert exc_info.value.reason == SceneDetectionFailureReason.DECODE_FAILURE_MID_RUN


# --- User Story 1: determinism -----------------------------------------------


def test_repeated_runs_produce_identical_boundary_sequences(mocker):
    def run_once():
        frames = _three_segment_frame_contexts(segment_frames=40)
        mocker.patch(
            "cvip.video.scene_detection.extract_frames",
            return_value=_FakeFrameExtractor(frames),
        )
        load_result = _load("valid_short.mp4")
        request = SceneDetectionRequest(load_result=load_result, scene_threshold=27.0)
        with detect_scenes(request) as detector:
            result = detector.run()
        return [(b.boundary_id, b.timestamp_seconds, b.boundary_type, b.confidence) for b in result.boundaries]

    first = run_once()
    second = run_once()
    third = run_once()

    assert first == second == third


# --- User Story 1: configurable sensitivity threshold -----------------------


def test_scene_threshold_is_actually_applied(mocker):
    def run_with_threshold(threshold):
        frames = _two_segment_frame_contexts(segment_frames=40)
        mocker.patch(
            "cvip.video.scene_detection.extract_frames",
            return_value=_FakeFrameExtractor(frames),
        )
        load_result = _load("valid_short.mp4")
        request = SceneDetectionRequest(load_result=load_result, scene_threshold=threshold)
        with detect_scenes(request) as detector:
            result = detector.run()
        return len(result.boundaries)

    low_threshold_count = run_with_threshold(1.0)
    high_threshold_count = run_with_threshold(99999.0)

    assert low_threshold_count != high_threshold_count
    assert high_threshold_count == 0


# --- User Story 1: single forward pass, no backward seek -------------------


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
    request = SceneDetectionRequest(load_result=load_result, scene_threshold=27.0)

    with detect_scenes(request) as detector:
        detector.run()

    assert len(seek_positions) > 0
    assert seek_positions == sorted(seek_positions)
    assert len(seek_positions) == len(set(seek_positions))


# --- User Story 2: classification --------------------------------------------


def test_ordinary_cut_and_replay_transition_classified_distinctly(mocker):
    frames = []
    fps = 25.0
    # Segment 1: black (ordinary content)
    for i in range(30):
        frames.append(
            FrameContext(source_video_id="deadbeef", frame_index=i, timestamp_seconds=i / fps, frame=_solid_frame(0))
        )
    # Ordinary hard cut: instantaneous jump to white
    for i in range(30, 60):
        frames.append(
            FrameContext(source_video_id="deadbeef", frame_index=i, timestamp_seconds=i / fps, frame=_solid_frame(255))
        )
    # Replay-style transition: several large consecutive full-range flips
    # (each step individually well above the cut threshold -- ContentDetector's
    # HSV-based score divides by the sum of its component weights, so a step
    # needs a large enough magnitude to still cross the threshold after that
    # division), unlike an ordinary cut's single isolated jump followed by a
    # steady frame.
    steps = [0, 255, 0, 255, 0]
    for j, value in enumerate(steps):
        i = 60 + j
        frames.append(
            FrameContext(source_video_id="deadbeef", frame_index=i, timestamp_seconds=i / fps, frame=_solid_frame(value))
        )
    for i in range(60 + len(steps), 100 + len(steps)):
        frames.append(
            FrameContext(source_video_id="deadbeef", frame_index=i, timestamp_seconds=i / fps, frame=_solid_frame(0))
        )

    mocker.patch(
        "cvip.video.scene_detection.extract_frames",
        return_value=_FakeFrameExtractor(frames),
    )

    load_result = _load("valid_short.mp4")
    request = SceneDetectionRequest(load_result=load_result, scene_threshold=27.0)

    with detect_scenes(request) as detector:
        result = detector.run()

    types = [b.boundary_type for b in result.boundaries]
    assert BoundaryType.ORDINARY_CUT in types
    assert BoundaryType.REPLAY_TRANSITION in types


# --- User Story 3: cancellation ----------------------------------------------


def test_cancel_mid_detection_stops_cleanly_and_emits_once(mocker):
    """Simulates an external cancellation request arriving mid-run: the
    fake FrameExtractor's generator calls detector.cancel() after yielding
    a handful of frames, which the detection loop must notice and stop on
    before reaching the later segments' cuts."""
    frames = _three_segment_frame_contexts(segment_frames=200)  # 2 cuts, deep in the sequence
    detector_holder = {}

    def frame_generator():
        for idx, frame_context in enumerate(frames):
            yield frame_context
            if idx == 50:
                detector_holder["detector"].cancel()

    mocker.patch(
        "cvip.video.scene_detection.extract_frames",
        return_value=_FakeFrameExtractor(frame_generator()),
    )
    emit_spy = mocker.patch("cvip.video.scene_detection.emit_diagnostics")

    load_result = _load("valid_short.mp4")
    request = SceneDetectionRequest(load_result=load_result, scene_threshold=27.0)

    with detect_scenes(request) as detector:
        detector_holder["detector"] = detector
        result = detector.run()

    # cancelled after 51 frames, still within the first 200-frame black
    # segment -- neither of the sequence's two cuts should have been reached
    assert result.boundaries == []
    assert emit_spy.call_count == 1
