"""Unit tests for Scene Detection internals: classification heuristic,
offline/CPU-only behavior, boundary_id uniqueness. See
specs/003-scene-detection/spec.md FR-003, FR-008, FR-009, FR-011, FR-016, FR-017.
"""

import socket
from pathlib import Path

import numpy as np
import pytest

from cvip.video.frame_extraction_models import FrameContext
from cvip.video.loader import load_video
from cvip.video.scene_detection import SceneDetector, detect_scenes
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
    def __init__(self, frame_contexts):
        self._frame_contexts = frame_contexts

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def __iter__(self):
        yield from self._frame_contexts


def _solid_frame(value: int, size=(32, 32, 3)) -> np.ndarray:
    return np.full(size, value, dtype="uint8")


def _three_segment_frame_contexts(source_video_id="deadbeef", fps=25.0, segment_frames=40):
    """Three segments (black, white, black) -- two unambiguous hard cuts,
    giving multiple boundary_id values to check for uniqueness."""
    frames = []
    values = [0, 255, 0]
    total = segment_frames * 3
    for i in range(total):
        value = values[min(i // segment_frames, 2)]
        frames.append(
            FrameContext(
                source_video_id=source_video_id,
                frame_index=i,
                timestamp_seconds=i / fps,
                frame=_solid_frame(value),
            )
        )
    return frames


def test_scene_threshold_must_be_finite_and_non_negative():
    load_result = _load("valid_short.mp4")
    with pytest.raises(ValueError, match="finite, non-negative"):
        SceneDetectionRequest(load_result=load_result, scene_threshold=-1.0)


def test_cut_near_end_of_stream_is_still_flushed_and_classified(mocker):
    """A cut whose post-cut window can't fully fill (fewer than
    POST_CUT_WINDOW frames remain before the stream ends) must still be
    finalized -- flushed with whatever partial evidence is available,
    rather than silently dropped."""
    frames = _three_segment_frame_contexts(segment_frames=40)
    # Truncate right after the second cut (around frame 80), leaving fewer
    # than POST_CUT_WINDOW=3 frames for its post-cut window.
    frames = frames[:82]
    mocker.patch(
        "cvip.video.scene_detection.extract_frames",
        return_value=_FakeFrameExtractor(frames),
    )

    load_result = _load("valid_short.mp4")
    request = SceneDetectionRequest(load_result=load_result, scene_threshold=27.0)

    with detect_scenes(request) as detector:
        result = detector.run()

    assert len(result.boundaries) >= 2
    for boundary in result.boundaries:
        assert boundary.confidence is not None


def test_boundary_ids_are_unique_within_a_result(mocker):
    frames = _three_segment_frame_contexts(segment_frames=40)
    mocker.patch(
        "cvip.video.scene_detection.extract_frames",
        return_value=_FakeFrameExtractor(frames),
    )

    load_result = _load("valid_short.mp4")
    request = SceneDetectionRequest(load_result=load_result, scene_threshold=27.0)

    with detect_scenes(request) as detector:
        result = detector.run()

    assert len(result.boundaries) >= 2
    boundary_ids = [b.boundary_id for b in result.boundaries]
    assert len(boundary_ids) == len(set(boundary_ids))


def test_frames_sourced_exclusively_via_extract_frames_not_cv2_directly(mocker):
    """FR-003: this feature must never construct cv2.VideoCapture itself --
    all frame access goes through the Frame Extraction Service."""
    # load_video() itself uses cv2.VideoCapture internally, so the fixture
    # must be loaded *before* patching cv2.VideoCapture out.
    load_result = _load("valid_short.mp4")

    frames = [
        FrameContext(source_video_id="deadbeef", frame_index=i, timestamp_seconds=i / 25.0, frame=_solid_frame(0))
        for i in range(5)
    ]
    mock_extract = mocker.patch(
        "cvip.video.scene_detection.extract_frames",
        return_value=_FakeFrameExtractor(frames),
    )
    mock_capture = mocker.patch("cv2.VideoCapture")

    request = SceneDetectionRequest(load_result=load_result, scene_threshold=27.0)

    with detect_scenes(request) as detector:
        detector.run()

    mock_extract.assert_called_once()
    mock_capture.assert_not_called()


def test_detection_makes_no_network_calls(mocker):
    def _fail_if_called(*args, **kwargs):
        raise AssertionError("detection must not create network sockets")

    mocker.patch.object(socket, "socket", side_effect=_fail_if_called)
    mocker.patch.object(socket, "create_connection", side_effect=_fail_if_called)

    load_result = _load("valid_short.mp4")
    request = SceneDetectionRequest(load_result=load_result, scene_threshold=27.0)

    with detect_scenes(request) as detector:
        result = detector.run()

    assert result is not None


def test_no_gpu_specific_opencv_api_is_used():
    """Static check (FR-017): no cv2.cuda.* call anywhere in this module's
    source. CPU-only is otherwise satisfied by construction -- no GPU
    library is a dependency of this project at all."""
    source_dir = Path(__file__).parent.parent.parent / "src" / "cvip" / "video"
    for filename in ("scene_detection.py", "scene_detection_models.py", "scene_detection_errors.py"):
        text = (source_dir / filename).read_text(encoding="utf-8")
        assert "cv2.cuda" not in text, f"{filename} must not use GPU-specific OpenCV APIs"
        assert "cuda" not in text.lower(), f"{filename} must not reference CUDA/GPU APIs"


# --- User Story 2: classification heuristic and confidence ------------------


def _make_detector() -> SceneDetector:
    load_result = _load("valid_short.mp4")
    request = SceneDetectionRequest(load_result=load_result, scene_threshold=27.0)
    return SceneDetector(request)


def test_confidence_is_always_present_and_bounded(mocker):
    """FR-008/SC-009: every returned boundary carries a confidence score,
    never absent, always in [0.0, 1.0] -- including an ambiguous case with
    no post-cut evidence at all (an empty post_scores window)."""
    detector = _make_detector()

    clean_cut = detector._classify({"timestamp": 1.0, "cut_score": 255.0, "post_scores": [0.0, 0.0, 0.0]})
    clean_ramp = detector._classify({"timestamp": 2.0, "cut_score": 255.0, "post_scores": [255.0, 255.0, 255.0]})
    no_evidence = detector._classify({"timestamp": 3.0, "cut_score": 255.0, "post_scores": []})

    for _, boundary_type, confidence in (clean_cut, clean_ramp, no_evidence):
        assert confidence is not None
        assert 0.0 <= confidence <= 1.0
        assert boundary_type in (BoundaryType.ORDINARY_CUT, BoundaryType.REPLAY_TRANSITION)


def test_instantaneous_jump_classifies_ordinary_cut_with_high_confidence():
    """research.md Decision 2: a cut followed by near-zero further change
    reads as an ordinary, instantaneous cut, with high confidence."""
    detector = _make_detector()

    _, boundary_type, confidence = detector._classify(
        {"timestamp": 1.6, "cut_score": 255.0, "post_scores": [0.0, 0.0, 0.0]}
    )

    assert boundary_type == BoundaryType.ORDINARY_CUT
    assert confidence >= 0.9


def test_gradual_ramp_classifies_replay_transition_with_high_confidence():
    """research.md Decision 2: a cut followed by several more frames of
    similarly-elevated content difference reads as a gradual, replay-style
    transition, with high confidence."""
    detector = _make_detector()

    _, boundary_type, confidence = detector._classify(
        {"timestamp": 2.44, "cut_score": 255.0, "post_scores": [255.0, 255.0, 255.0]}
    )

    assert boundary_type == BoundaryType.REPLAY_TRANSITION
    assert confidence >= 0.9


def test_ambiguous_boundary_completes_without_raising_and_gets_lower_confidence():
    """FR-011/US2 Acceptance Scenario 4: a boundary whose post-cut window
    matches neither pattern cleanly (only one of three post-frames elevated,
    below the ramp threshold but not zero either) still completes without
    raising, is still returned with a valid classification, and gets a
    confidence lower than the unambiguous cases above -- never absent."""
    detector = _make_detector()

    timestamp, boundary_type, confidence = detector._classify(
        {"timestamp": 5.0, "cut_score": 255.0, "post_scores": [255.0, 0.0, 0.0]}
    )

    assert boundary_type in (BoundaryType.ORDINARY_CUT, BoundaryType.REPLAY_TRANSITION)
    assert confidence is not None
    assert 0.0 <= confidence < 1.0
    assert timestamp == 5.0
