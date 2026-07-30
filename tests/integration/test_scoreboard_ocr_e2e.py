"""Integration tests for Scoreboard OCR: real fixture files (reused from
Video Loader), full extract_scoreboard() calls. See
specs/005-scoreboard-ocr/spec.md User Stories 1-3.
"""

from pathlib import Path

import cv2
import pytest

from cvip.video.frame_extraction_errors import ExtractionError, ExtractionFailureReason
from cvip.video.frame_extraction_models import FrameContext
from cvip.video.loader import load_video
from cvip.video.models import ContainerFormat, LoadResult, MatchVideoSource
from cvip.video.scoreboard_ocr import ClubBroadcastParser, extract_scoreboard
from cvip.video.scoreboard_ocr_errors import ScoreboardOcrError, ScoreboardOcrFailureReason
from cvip.video.scoreboard_ocr_models import ScoreboardOcrRequest, ScoreboardOcrResult, ScoreboardSample

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


def _solid_frame_contexts(duration_seconds, value=0, source_video_id="deadbeef"):
    import numpy as np

    return [
        FrameContext(
            source_video_id=source_video_id,
            frame_index=i,
            timestamp_seconds=float(i),
            frame=np.full((64, 640, 3), value, dtype="uint8"),
        )
        for i in range(int(duration_seconds))
    ]


def _make_request(load_result, **overrides) -> ScoreboardOcrRequest:
    fields = dict(load_result=load_result, **DEFAULT_REQUEST_KWARGS)
    fields.update(overrides)
    return ScoreboardOcrRequest(**fields)


# --- US1: structural correctness against a real fixture, real Tesseract ----


def test_extraction_against_real_fixture_yields_valid_structural_result(mocker):
    load_result = _load("valid_short.mp4")
    request = _make_request(load_result)
    emit_spy = mocker.patch("cvip.video.scoreboard_ocr.emit_diagnostics")

    with extract_scoreboard(request) as extractor:
        result = extractor.run()

    timestamps = [s.timestamp_seconds for s in result.samples]
    assert timestamps == sorted(timestamps)
    assert len(result.samples) > 0
    for sample in result.samples:
        assert 0.0 <= sample.ocr_confidence <= 1.0
        assert 0.0 <= sample.parse_confidence <= 1.0
    assert result.total_samples == len(result.samples)
    assert emit_spy.call_count == 1


# --- US1: determinism ---------------------------------------------------------


def test_repeated_runs_produce_identical_sample_sequences():
    load_result = _load("valid_short.mp4")

    def run_once():
        request = _make_request(load_result)
        with extract_scoreboard(request) as extractor:
            result = extractor.run()
        return [
            (s.timestamp_seconds, s.runs, s.wickets, s.raw_text, s.ocr_confidence, s.parse_confidence)
            for s in result.samples
        ]

    first = run_once()
    second = run_once()
    third = run_once()

    assert first == second == third


# --- US1: undetectable region throughout still completes normally ----------


def test_video_with_undetectable_region_throughout_still_completes_fully(mocker):
    load_result = _dummy_load_result(duration_seconds=5.0)
    frames = _solid_frame_contexts(5.0, value=0)
    mocker.patch("cvip.video.scoreboard_ocr.extract_frames", return_value=_FakeFrameExtractor(frames))

    request = _make_request(load_result)
    with extract_scoreboard(request) as extractor:
        result = extractor.run()

    assert len(result.samples) == 5
    assert all(sample.ocr_confidence == 0.0 for sample in result.samples)


# --- US2: result is self-contained -------------------------------------------


def test_result_source_video_id_matches_the_video_file_hash(mocker):
    load_result = _dummy_load_result(file_hash="cafef00d", duration_seconds=2.0)
    frames = _solid_frame_contexts(2.0)
    mocker.patch("cvip.video.scoreboard_ocr.extract_frames", return_value=_FakeFrameExtractor(frames))

    request = _make_request(load_result)

    with extract_scoreboard(request) as extractor:
        result = extractor.run()

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
    request = _make_request(load_result)

    with extract_scoreboard(request) as extractor:
        extractor.run()

    # The Frame Extraction Service performs a one-time O(1) calibration
    # probe (seek to frame 0, then the last frame) before the real
    # FIXED_INTERVAL pass begins -- see Replay Detection's own precedent
    # test for the same underlying behavior.
    assert len(seek_positions) > 2
    extraction_seeks = seek_positions[2:]
    assert extraction_seeks == sorted(extraction_seeks)
    assert len(extraction_seeks) == len(set(extraction_seeks))


# --- US3: mid-run failures, each with exactly one diagnostics record --------


def test_source_unavailable_mid_run_raises_specific_reason_with_one_diagnostics(mocker):
    load_result = _dummy_load_result(duration_seconds=10.0)
    frames = _solid_frame_contexts(10.0)[:3]
    mocker.patch(
        "cvip.video.scoreboard_ocr.extract_frames",
        return_value=_FakeFrameExtractor(
            frames, error=ExtractionError(ExtractionFailureReason.SOURCE_UNAVAILABLE_MID_RUN, "gone")
        ),
    )
    emit_spy = mocker.patch("cvip.video.scoreboard_ocr.emit_diagnostics")

    request = _make_request(load_result)

    with pytest.raises(ScoreboardOcrError) as exc_info:
        with extract_scoreboard(request) as extractor:
            extractor.run()

    assert exc_info.value.reason == ScoreboardOcrFailureReason.SOURCE_UNAVAILABLE_MID_RUN
    assert emit_spy.call_count == 1


def test_decode_failure_mid_run_raises_specific_reason_with_one_diagnostics(mocker):
    load_result = _dummy_load_result(duration_seconds=10.0)
    frames = _solid_frame_contexts(10.0)[:3]
    mocker.patch(
        "cvip.video.scoreboard_ocr.extract_frames",
        return_value=_FakeFrameExtractor(
            frames, error=ExtractionError(ExtractionFailureReason.DECODE_FAILURE_MID_RUN, "bad frame")
        ),
    )
    emit_spy = mocker.patch("cvip.video.scoreboard_ocr.emit_diagnostics")

    request = _make_request(load_result)

    with pytest.raises(ScoreboardOcrError) as exc_info:
        with extract_scoreboard(request) as extractor:
            extractor.run()

    assert exc_info.value.reason == ScoreboardOcrFailureReason.DECODE_FAILURE_MID_RUN
    assert emit_spy.call_count == 1


# --- US3: invalid configuration, each independently, one diagnostics record -


def test_malformed_roi_rejected_with_one_diagnostics(mocker):
    load_result = _dummy_load_result(duration_seconds=5.0)
    mock_extract = mocker.patch("cvip.video.scoreboard_ocr.extract_frames")
    emit_spy = mocker.patch("cvip.video.scoreboard_ocr.emit_diagnostics")

    request = _make_request(load_result, scoreboard_region=(0.9, 0.9, 0.5, 0.5))

    with pytest.raises(ScoreboardOcrError) as exc_info:
        with extract_scoreboard(request) as extractor:
            extractor.run()

    assert exc_info.value.reason == ScoreboardOcrFailureReason.INVALID_OCR_CONFIGURATION
    mock_extract.assert_not_called()
    assert emit_spy.call_count == 1


@pytest.mark.parametrize(
    "region",
    [None, (0.1, 0.1, 0.5), (0.1, 0.1, 0.5, "0.5"), ("a", "b", "c", "d")],
    ids=["none", "wrong-length", "non-numeric-element", "all-non-numeric"],
)
def test_structurally_malformed_roi_rejected_not_crashed(mocker, region):
    """PR review finding: a malformed (not merely out-of-bounds) ROI --
    None, wrong length, or non-numeric elements -- must still fail with
    INVALID_OCR_CONFIGURATION, not an untyped TypeError/ValueError."""
    load_result = _dummy_load_result(duration_seconds=5.0)
    mock_extract = mocker.patch("cvip.video.scoreboard_ocr.extract_frames")
    emit_spy = mocker.patch("cvip.video.scoreboard_ocr.emit_diagnostics")

    request = _make_request(load_result, scoreboard_region=region)

    with pytest.raises(ScoreboardOcrError) as exc_info:
        with extract_scoreboard(request) as extractor:
            extractor.run()

    assert exc_info.value.reason == ScoreboardOcrFailureReason.INVALID_OCR_CONFIGURATION
    mock_extract.assert_not_called()
    assert emit_spy.call_count == 1


@pytest.mark.parametrize("field_name", ["preprocess_grayscale", "preprocess_threshold"])
def test_non_boolean_preprocessing_flag_rejected_with_one_diagnostics(mocker, field_name):
    """PR review finding: a truthy-but-non-boolean preprocessing flag (e.g.
    the string "false") must be rejected rather than silently running a
    different pipeline than the caller actually requested."""
    load_result = _dummy_load_result(duration_seconds=5.0)
    mock_extract = mocker.patch("cvip.video.scoreboard_ocr.extract_frames")
    emit_spy = mocker.patch("cvip.video.scoreboard_ocr.emit_diagnostics")

    request = _make_request(load_result, **{field_name: "false"})

    with pytest.raises(ScoreboardOcrError) as exc_info:
        with extract_scoreboard(request) as extractor:
            extractor.run()

    assert exc_info.value.reason == ScoreboardOcrFailureReason.INVALID_OCR_CONFIGURATION
    mock_extract.assert_not_called()
    assert emit_spy.call_count == 1


def test_non_positive_integer_upscale_rejected_with_one_diagnostics(mocker):
    load_result = _dummy_load_result(duration_seconds=5.0)
    mock_extract = mocker.patch("cvip.video.scoreboard_ocr.extract_frames")
    emit_spy = mocker.patch("cvip.video.scoreboard_ocr.emit_diagnostics")

    request = _make_request(load_result, preprocess_upscale=0)

    with pytest.raises(ScoreboardOcrError) as exc_info:
        with extract_scoreboard(request) as extractor:
            extractor.run()

    assert exc_info.value.reason == ScoreboardOcrFailureReason.INVALID_OCR_CONFIGURATION
    mock_extract.assert_not_called()
    assert emit_spy.call_count == 1


def test_min_confidence_out_of_range_rejected_with_one_diagnostics(mocker):
    load_result = _dummy_load_result(duration_seconds=5.0)
    mock_extract = mocker.patch("cvip.video.scoreboard_ocr.extract_frames")
    emit_spy = mocker.patch("cvip.video.scoreboard_ocr.emit_diagnostics")

    request = _make_request(load_result, min_confidence=1.5)

    with pytest.raises(ScoreboardOcrError) as exc_info:
        with extract_scoreboard(request) as extractor:
            extractor.run()

    assert exc_info.value.reason == ScoreboardOcrFailureReason.INVALID_OCR_CONFIGURATION
    mock_extract.assert_not_called()
    assert emit_spy.call_count == 1


# --- US3: cancellation ---------------------------------------------------------


def test_cancel_mid_extraction_stops_cleanly_and_emits_once(mocker):
    load_result = _dummy_load_result(duration_seconds=20.0)
    frames = _solid_frame_contexts(20.0)
    detector_holder = {}

    def frame_generator():
        for idx, frame_context in enumerate(frames):
            yield frame_context
            if idx == 5:
                detector_holder["extractor"].cancel()

    mocker.patch(
        "cvip.video.scoreboard_ocr.extract_frames",
        return_value=_FakeFrameExtractor(frame_generator()),
    )
    emit_spy = mocker.patch("cvip.video.scoreboard_ocr.emit_diagnostics")

    request = _make_request(load_result)

    with extract_scoreboard(request) as extractor:
        detector_holder["extractor"] = extractor
        result = extractor.run()

    assert len(result.samples) == 6  # frames 0-5 processed before the break
    assert emit_spy.call_count == 1


# =============================================================================
# specs/011-club-broadcast-overlay-support/ analysis finding E1 (T034):
# SC-005's mandatory, non-optional proof -- a deterministic timeline built
# directly from ClubBroadcastParser output, fed into Event Detection, with
# no real video/OCR/fixture involved. The genuinely optional real-recording
# check (T036) is additive to this, not a substitute for it.
# =============================================================================


def _club_broadcast_tokens(batter_stats, non_striker_stats, score, bowler_stats):
    """Builds a club-broadcast-format token list matching this feature's own
    raw evidence shape (research.md), with the given per-reading stats/score
    tokens substituted in."""
    return [
        ("MAHESH", 90.0),
        *batter_stats,
        ("SAI", 88.0),
        ("KRISHNA", 87.0),
        *non_striker_stats,
        ("Chai", 70.0),
        ("Cricket", 70.0),
        ("Club", 70.0),
        (score, 92.0),
        ("BHARATH", 89.0),
        *bowler_stats,
    ]


def test_synthetic_club_broadcast_timeline_produces_four_and_wicket_events_via_event_detection():
    """SC-005: Event Detection (Module 5), run unmodified against a cleaned
    timeline derived from ClubBroadcastParser's parsing path, successfully
    detects FOUR/SIX/WICKET events -- proven synthetically, without a real
    video, so this success criterion is never gated on the optional
    real-fixture check alone (analysis finding E1)."""
    from cvip.events.detection import detect_events
    from cvip.events.models import EventDetectionRequest
    from cvip.video.ocr_timeline_smoother_models import CleanedScoreboardSample, OCRTimelineSmootherResult
    from cvip.video.replay_detection_models import ReplayDetectionResult

    club_parser = ClubBroadcastParser()

    # Three consecutive club-broadcast readings: a dot ball, then a FOUR
    # (runs +4, ball_in_over advances by exactly one), then a WICKET (a
    # wicket falls on the next ball).
    readings_tokens = [
        _club_broadcast_tokens([("0", 85.0), ("(0)", 80.0)], [("0(0)", 84.0)], "0-0/0.0(20)", [("0-0(0)", 83.0)]),
        _club_broadcast_tokens([("4", 85.0), ("(1)", 80.0)], [("0(1)", 84.0)], "4-0/0.1(20)", [("0-0(0)", 83.0)]),
        _club_broadcast_tokens([("4", 85.0), ("(2)", 80.0)], [("0(2)", 84.0)], "4-1/0.2(20)", [("0-1(0)", 83.0)]),
    ]

    cleaned_samples = []
    raw_samples = []
    for i, tokens in enumerate(readings_tokens):
        # Real parser output, not hand-fabricated values (task requirement).
        parsed, _ = club_parser.parse(tokens)
        timestamp = float(i)
        cleaned_samples.append(
            CleanedScoreboardSample(
                timestamp_seconds=timestamp,
                runs=parsed["runs"],
                wickets=parsed["wickets"],
                over_number=parsed["over_number"],
                ball_in_over=parsed["ball_in_over"],
                batter=parsed.get("batter"),
                non_striker=parsed.get("non_striker"),
                bowler=parsed.get("bowler"),
                run_rate=None,
            )
        )
        raw_samples.append(
            ScoreboardSample(
                timestamp_seconds=timestamp,
                runs=parsed["runs"],
                wickets=parsed["wickets"],
                over_number=parsed["over_number"],
                ball_in_over=parsed["ball_in_over"],
                batter=parsed.get("batter"),
                non_striker=parsed.get("non_striker"),
                bowler=parsed.get("bowler"),
                run_rate=None,
                raw_text="",
                ocr_confidence=1.0,
                parse_confidence=1.0,  # batter is populated (best-effort) -> validation passes
            )
        )

    source_video_id = "club-broadcast-synthetic"
    request = EventDetectionRequest(
        cleaned_timeline=OCRTimelineSmootherResult(
            source_video_id=source_video_id, samples=tuple(cleaned_samples), total_samples=len(cleaned_samples)
        ),
        raw_ocr_result=ScoreboardOcrResult(
            source_video_id=source_video_id, samples=tuple(raw_samples), total_samples=len(raw_samples)
        ),
        replay_result=ReplayDetectionResult(source_video_id=source_video_id, segments=(), total_segments=0),
        team_milestone_interval=50,
        ranking={"FOUR": 60, "SIX": 80, "WICKET": 95, "TEAM_MILESTONE": 65},
    )

    with detect_events(request) as runner:
        result = runner.run()

    event_types = [event.event_type for event in result.events]
    assert "FOUR" in event_types
    assert "WICKET" in event_types

    four_event = next(event for event in result.events if event.event_type == "FOUR")
    wicket_event = next(event for event in result.events if event.event_type == "WICKET")
    # WICKET's player attribution comes from the best-effort batter
    # ClubBroadcastParser populated -- proving the amendment's output is
    # genuinely usable downstream, not just structurally present.
    assert wicket_event.player == "MAHESH"
    assert four_event.confidence > 0.0
