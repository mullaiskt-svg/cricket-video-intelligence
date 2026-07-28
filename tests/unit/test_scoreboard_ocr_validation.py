"""Unit tests for Scoreboard OCR internals: preprocessing, OCR/parsing,
cricket-rule validation, the ROI-unchanged skip, weight/threshold
validation. See specs/005-scoreboard-ocr/spec.md FR-007, FR-009 through
FR-021, FR-025 through FR-031.
"""

import socket
from pathlib import Path

import numpy as np
import pytest

from cvip.video.frame_extraction_models import FrameContext
from cvip.video.loader import load_video
from cvip.video.models import ContainerFormat, LoadResult, MatchVideoSource
from cvip.video.scoreboard_ocr import ScoreboardOcrExtractor, _LastAcceptedReading, extract_scoreboard
from cvip.video.scoreboard_ocr_errors import ScoreboardOcrError, ValidationFailureReason
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


def _make_extractor(**overrides) -> ScoreboardOcrExtractor:
    load_result = overrides.pop("load_result", None) or _dummy_load_result()
    fields = dict(load_result=load_result, **DEFAULT_REQUEST_KWARGS)
    fields.update(overrides)
    request = ScoreboardOcrRequest(**fields)
    return ScoreboardOcrExtractor(request)


def _solid_frame(value: int, size=(64, 640, 3)) -> np.ndarray:
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


def _tesseract_data(tokens):
    """tokens: list of (text, confidence_0_100) tuples, matching
    pytesseract.image_to_data()'s own (text, conf) column pairing."""
    return {"text": [t for t, _ in tokens], "conf": [c for _, c in tokens]}


HAPPY_PATH_TOKENS = [
    ("125/3", 95.0),
    ("12.3", 92.0),
    ("8.5", 90.0),
    ("Smith*", 88.0),
    ("Jones", 85.0),
    ("B:", 80.0),
    ("Kumar", 82.0),
]


# --- FR-007/FR-030: preprocessing pipeline order -----------------------------


def test_preprocessing_applies_grayscale_upscale_threshold_in_order():
    extractor = _make_extractor(preprocess_grayscale=True, preprocess_threshold=True, preprocess_upscale=2)
    roi = _solid_frame(128, size=(20, 100, 3))

    result = extractor._preprocess_roi(roi)

    # Grayscale -> 2D; upscale by 2 -> dimensions doubled; threshold -> binary values only.
    assert result.ndim == 2
    assert result.shape == (40, 200)
    assert set(np.unique(result)).issubset({0, 255})


def test_preprocessing_stages_independently_toggleable():
    extractor = _make_extractor(preprocess_grayscale=False, preprocess_threshold=False, preprocess_upscale=1)
    roi = _solid_frame(128, size=(20, 100, 3))

    result = extractor._preprocess_roi(roi)

    assert result.shape == (20, 100, 3)
    assert result.ndim == 3


# --- FR-010: undetectable scoreboard region ----------------------------------


def test_undetectable_region_yields_zero_confidence_and_empty_text():
    extractor = _make_extractor()
    from cvip.video.scoreboard_ocr import _LastAcceptedReading as Baseline

    sample, evidence = extractor._process_frame(None, 5.0, Baseline())

    assert sample.ocr_confidence == 0.0
    assert sample.raw_text == ""
    assert sample.parse_confidence == 0.0


def test_zero_recognized_tokens_also_treated_as_undetectable(mocker):
    extractor = _make_extractor()
    mocker.patch("cvip.video.scoreboard_ocr.pytesseract.image_to_data", return_value=_tesseract_data([]))
    roi = _solid_frame(0, size=(20, 100, 3))

    sample, evidence = extractor._process_frame(roi, 5.0, _LastAcceptedReading())

    assert sample.ocr_confidence == 0.0
    assert sample.raw_text == ""


def test_undetectable_evidence_has_validation_passed_none_not_false():
    """Regression: an undetectable-region/zero-token sample never attempted
    validation at all -- `validation_passed` must be `None` ("not
    attempted"), not `False` ("attempted and failed"), and
    `validation_failure_reason` must stay `null` either way."""
    extractor = _make_extractor()

    _, region_evidence = extractor._process_frame(None, 5.0, _LastAcceptedReading())
    assert region_evidence.validation_passed is None
    assert region_evidence.validation_failure_reason is None


# --- FR-011: low OCR confidence recorded as-is -------------------------------


def test_low_ocr_confidence_recorded_as_is(mocker):
    extractor = _make_extractor(min_confidence=0.90)
    low_confidence_tokens = [("125/3", 50.0), ("12.3", 50.0), ("Smith*", 50.0)]
    mocker.patch(
        "cvip.video.scoreboard_ocr.pytesseract.image_to_data",
        return_value=_tesseract_data(low_confidence_tokens),
    )
    roi = _solid_frame(0, size=(20, 100, 3))

    sample, evidence = extractor._process_frame(roi, 5.0, _LastAcceptedReading())
    extractor._record_stats(sample, evidence)  # counting happens centrally in run()'s loop

    assert sample.ocr_confidence == pytest.approx(0.5)
    assert extractor._low_confidence_count == 1
    # Low OCR confidence does not by itself affect parse_confidence.
    assert sample.parse_confidence == 1.0


# --- FR-029/research.md: per-field OCR confidence attribution ---------------


def test_field_confidences_attributed_from_tokens_and_missing_field_is_absent():
    extractor = _make_extractor()
    tokens = [("125/3", 95.0), ("Smith*", 88.0)]  # no over/ball, no bowler, no non-striker

    parsed, confidences = extractor._parse_fields(tokens)

    assert confidences["runs"] == pytest.approx(0.95)
    assert confidences["wickets"] == pytest.approx(0.95)
    assert confidences["batter"] == pytest.approx(0.88)
    assert "over_number" not in confidences
    assert "bowler" not in confidences
    assert "non_striker" not in confidences


# --- FR-007: over-and-ball parsing -------------------------------------------


def test_over_and_ball_reading_splits_correctly():
    extractor = _make_extractor()

    parsed, _ = extractor._parse_fields([("12.3", 90.0)])

    assert parsed["over_number"] == 12
    assert parsed["ball_in_over"] == 3


# --- FR-013/FR-031: ball_in_over range ----------------------------------------


def test_ball_in_over_out_of_range_yields_invalid_ball_number():
    extractor = _make_extractor()
    parsed_fields = {"batter": "Smith", "runs": 10, "wickets": 1, "over_number": 2, "ball_in_over": 7}

    passed, reason = extractor._validate_reading(parsed_fields, _LastAcceptedReading())

    assert passed is False
    assert reason == ValidationFailureReason.INVALID_BALL_NUMBER


# --- FR-013/FR-031: the three monotonic-rule violations, independently ------


def test_runs_decreased_yields_runs_decreased_reason():
    extractor = _make_extractor()
    baseline = _LastAcceptedReading()
    baseline.update(runs=50, wickets=2, over_number=10, ball_in_over=3)

    passed, reason = extractor._validate_reading(
        {"batter": "Smith", "runs": 40, "wickets": 2, "over_number": 10, "ball_in_over": 4}, baseline
    )

    assert passed is False
    assert reason == ValidationFailureReason.RUNS_DECREASED


def test_wickets_decreased_yields_wickets_decreased_reason():
    extractor = _make_extractor()
    baseline = _LastAcceptedReading()
    baseline.update(runs=50, wickets=3, over_number=10, ball_in_over=3)

    passed, reason = extractor._validate_reading(
        {"batter": "Smith", "runs": 55, "wickets": 2, "over_number": 10, "ball_in_over": 4}, baseline
    )

    assert passed is False
    assert reason == ValidationFailureReason.WICKETS_DECREASED


def test_over_number_decreased_yields_invalid_over_sequence_reason():
    extractor = _make_extractor()
    baseline = _LastAcceptedReading()
    baseline.update(runs=50, wickets=2, over_number=10, ball_in_over=3)

    passed, reason = extractor._validate_reading(
        {"batter": "Smith", "runs": 55, "wickets": 2, "over_number": 9, "ball_in_over": 4}, baseline
    )

    assert passed is False
    assert reason == ValidationFailureReason.INVALID_OVER_SEQUENCE


# --- FR-014: innings-transition heuristic ------------------------------------


def test_innings_transition_suppresses_monotonic_checks():
    extractor = _make_extractor()
    baseline = _LastAcceptedReading()
    baseline.update(runs=180, wickets=9, over_number=45, ball_in_over=2)

    # A new innings: runs and wickets both drop -- over_number also drops,
    # which alone would otherwise be INVALID_OVER_SEQUENCE.
    passed, reason = extractor._validate_reading(
        {"batter": "Smith", "runs": 4, "wickets": 0, "over_number": 1, "ball_in_over": 1}, baseline
    )

    assert passed is True
    assert reason is None


# --- FR-030/FR-031: structurally unparseable essential field ----------------


def test_missing_batter_field_yields_player_parse_failed():
    extractor = _make_extractor()

    passed, reason = extractor._validate_reading(
        {"runs": 10, "wickets": 1, "over_number": 2, "ball_in_over": 3}, _LastAcceptedReading()
    )

    assert passed is False
    assert reason == ValidationFailureReason.PLAYER_PARSE_FAILED


# --- FR-016: first reading is exempt from rule-consistency checks -----------


def test_first_reading_is_never_rejected_by_rule_consistency_checks():
    extractor = _make_extractor()

    passed, reason = extractor._validate_reading(
        {"batter": "Smith", "runs": 999, "wickets": 9, "over_number": 1, "ball_in_over": 0},
        _LastAcceptedReading(),
    )

    assert passed is True
    assert reason is None


# --- FR-012: validation compares against the last *accepted* reading -------


def test_validation_compares_against_last_accepted_not_immediately_preceding():
    extractor = _make_extractor()
    baseline = _LastAcceptedReading()
    baseline.update(runs=50, wickets=2, over_number=10, ball_in_over=0)

    # A rejected reading (runs decreased to 40) -- must NOT become the new baseline.
    rejected, _ = extractor._validate_reading(
        {"batter": "Smith", "runs": 40, "wickets": 2, "over_number": 10, "ball_in_over": 1}, baseline
    )
    assert rejected is False
    # baseline.update() is only ever called by production code when validation
    # passes -- simulate that contract precisely by not updating here.

    # A reading of 45 is still below the *last accepted* value (50), even
    # though it's above the rejected one (40) -- must still be rejected.
    passed, reason = extractor._validate_reading(
        {"batter": "Smith", "runs": 45, "wickets": 2, "over_number": 10, "ball_in_over": 2}, baseline
    )

    assert passed is False
    assert reason == ValidationFailureReason.RUNS_DECREASED


# --- research.md Decision 1: ROI-unchanged skip ------------------------------


def test_roi_unchanged_detects_pixel_identical_and_different_rois():
    extractor = _make_extractor()
    roi_a = _solid_frame(100, size=(20, 100, 3))
    roi_b = _solid_frame(100, size=(20, 100, 3))
    roi_c = _solid_frame(200, size=(20, 100, 3))

    assert extractor._roi_unchanged(roi_a, roi_b) is True
    assert extractor._roi_unchanged(roi_a, roi_c) is False
    assert extractor._roi_unchanged(None, roi_b) is False


def test_roi_unchanged_skip_reuses_previous_sample_without_new_ocr_call(mocker):
    load_result = _dummy_load_result(duration_seconds=3.0)
    frames = [
        FrameContext(source_video_id="deadbeef", frame_index=i, timestamp_seconds=float(i), frame=_solid_frame(50))
        for i in range(3)
    ]
    mocker.patch("cvip.video.scoreboard_ocr.extract_frames", return_value=_FakeFrameExtractor(frames))
    ocr_spy = mocker.patch(
        "cvip.video.scoreboard_ocr.pytesseract.image_to_data",
        return_value=_tesseract_data(HAPPY_PATH_TOKENS),
    )

    request = ScoreboardOcrRequest(load_result=load_result, **DEFAULT_REQUEST_KWARGS)
    with extract_scoreboard(request) as extractor:
        result = extractor.run()

    # All three sampled frames have an identical (solid-color) ROI, so only
    # the first should trigger a real OCR call.
    assert ocr_spy.call_count == 1
    assert len(result.samples) == 3
    first, second, third = result.samples
    assert second.runs == first.runs and second.raw_text == first.raw_text
    assert third.runs == first.runs and third.raw_text == first.raw_text
    assert second.timestamp_seconds == 1.0 and third.timestamp_seconds == 2.0


def test_previous_roi_is_retained_as_a_copy_not_a_view(mocker):
    """Regression: `FrameContext.frame` is only guaranteed valid through the
    current iteration step (Frame Extraction Service's own contract) -- a
    `FrameExtractor` that reused a decode buffer between frames would make
    an uncopied `previous_roi` alias the *next* frame's already-overwritten
    pixels, causing every later frame to be misdetected as unchanged."""
    load_result = _dummy_load_result(duration_seconds=2.0)
    shared_buffer = np.full((64, 640, 3), 100, dtype="uint8")

    def frame_generator():
        yield FrameContext(source_video_id="deadbeef", frame_index=0, timestamp_seconds=0.0, frame=shared_buffer)
        shared_buffer[:] = 200  # simulate a FrameExtractor reusing its own decode buffer
        yield FrameContext(source_video_id="deadbeef", frame_index=1, timestamp_seconds=1.0, frame=shared_buffer)

    mocker.patch(
        "cvip.video.scoreboard_ocr.extract_frames", return_value=_FakeFrameExtractor(frame_generator())
    )
    ocr_spy = mocker.patch(
        "cvip.video.scoreboard_ocr.pytesseract.image_to_data",
        return_value=_tesseract_data(HAPPY_PATH_TOKENS),
    )

    request = ScoreboardOcrRequest(load_result=load_result, **DEFAULT_REQUEST_KWARGS)
    with extract_scoreboard(request) as extractor:
        extractor.run()

    # If `previous_roi` aliased the shared buffer, the second (genuinely
    # different-content) frame would be incorrectly treated as unchanged
    # and skipped -- both frames must have triggered a real OCR call.
    assert ocr_spy.call_count == 2


# --- FR-021: skipped/reused samples still count toward diagnostics ---------


def test_skipped_sample_still_counted_toward_undetectable_diagnostics(mocker):
    """Regression: a long stretch of pixel-identical, undetectable-region
    frames must each be reflected in `_undetectable_count`, not just the
    first one that was actually processed -- the ROI-unchanged skip changes
    how much OCR work runs, not what the diagnostics record reports."""
    load_result = _dummy_load_result(duration_seconds=3.0)
    frames = [
        FrameContext(source_video_id="deadbeef", frame_index=i, timestamp_seconds=float(i), frame=_solid_frame(0))
        for i in range(3)
    ]
    mocker.patch("cvip.video.scoreboard_ocr.extract_frames", return_value=_FakeFrameExtractor(frames))
    mocker.patch("cvip.video.scoreboard_ocr.pytesseract.image_to_data", return_value=_tesseract_data([]))

    request = ScoreboardOcrRequest(load_result=load_result, **DEFAULT_REQUEST_KWARGS)
    with extract_scoreboard(request) as extractor:
        result = extractor.run()

    assert len(result.samples) == 3
    assert extractor._undetectable_count == 3


# --- FR-003/FR-025/FR-026: frame sourcing, offline, CPU-only ----------------


def test_frames_sourced_exclusively_via_extract_frames_not_cv2_directly(mocker):
    load_result = _load("valid_short.mp4")
    frames = [
        FrameContext(source_video_id="deadbeef", frame_index=i, timestamp_seconds=float(i), frame=_solid_frame(0))
        for i in range(3)
    ]
    mock_extract = mocker.patch(
        "cvip.video.scoreboard_ocr.extract_frames", return_value=_FakeFrameExtractor(frames)
    )
    mock_capture = mocker.patch("cv2.VideoCapture")
    mocker.patch("cvip.video.scoreboard_ocr.pytesseract.image_to_data", return_value=_tesseract_data([]))

    request = ScoreboardOcrRequest(load_result=load_result, **DEFAULT_REQUEST_KWARGS)

    with extract_scoreboard(request) as extractor:
        extractor.run()

    mock_extract.assert_called_once()
    mock_capture.assert_not_called()


def test_extraction_makes_no_network_calls(mocker):
    def _fail_if_called(*args, **kwargs):
        raise AssertionError("extraction must not create network sockets")

    mocker.patch.object(socket, "socket", side_effect=_fail_if_called)
    mocker.patch.object(socket, "create_connection", side_effect=_fail_if_called)

    load_result = _load("valid_short.mp4")
    request = ScoreboardOcrRequest(load_result=load_result, **DEFAULT_REQUEST_KWARGS)

    with extract_scoreboard(request) as extractor:
        result = extractor.run()

    assert result is not None


def test_no_gpu_specific_opencv_api_is_used():
    source_dir = Path(__file__).parent.parent.parent / "src" / "cvip" / "video"
    for filename in ("scoreboard_ocr.py", "scoreboard_ocr_models.py", "scoreboard_ocr_errors.py"):
        text = (source_dir / filename).read_text(encoding="utf-8")
        assert "cv2.cuda" not in text, f"{filename} must not use GPU-specific OpenCV APIs"
        assert "cuda" not in text.lower(), f"{filename} must not reference CUDA/GPU APIs"


# --- Mid-run failure: an unexpected processing error still maps to a typed -
# --- failure reason (not an untyped crash) ----------------------------------


def test_unexpected_processing_error_mid_run_raises_decode_failure_reason(mocker):
    """Regression: an unexpected error while processing an otherwise-
    successfully-decoded frame (here, a Tesseract call itself raising) must
    still surface as this module's own typed failure (FR-018), not an
    untyped crash -- mirrors Scene Detection's and Replay Detection's own
    regression tests for the same class of bug."""
    load_result = _dummy_load_result(duration_seconds=5.0)
    frames = [
        FrameContext(source_video_id="deadbeef", frame_index=0, timestamp_seconds=0.0, frame=_solid_frame(0))
    ]
    mocker.patch("cvip.video.scoreboard_ocr.extract_frames", return_value=_FakeFrameExtractor(frames))
    mocker.patch(
        "cvip.video.scoreboard_ocr.pytesseract.image_to_data",
        side_effect=RuntimeError("tesseract crashed"),
    )

    request = ScoreboardOcrRequest(load_result=load_result, **DEFAULT_REQUEST_KWARGS)

    with pytest.raises(ScoreboardOcrError) as exc_info:
        with extract_scoreboard(request) as extractor:
            extractor.run()

    from cvip.video.scoreboard_ocr_errors import ScoreboardOcrFailureReason

    assert exc_info.value.reason == ScoreboardOcrFailureReason.DECODE_FAILURE_MID_RUN


# --- Degenerate ROI crop (zero-pixel result despite passing config bounds) -


def test_crop_roi_returns_none_when_dimensions_truncate_to_zero_pixels():
    extractor = _make_extractor()
    tiny_frame = _solid_frame(0, size=(10, 10, 3))

    # A tiny width fraction on a small frame truncates to zero pixels wide.
    result = extractor._crop_roi(tiny_frame, (0.0, 0.0, 0.01, 0.5))

    assert result is None


# --- FR-013: wickets absolute out-of-range (independent of history) --------


def test_wickets_absolute_out_of_range_is_rejected_even_without_prior_history():
    extractor = _make_extractor()

    passed, reason = extractor._validate_reading(
        {"batter": "Smith", "runs": 10, "wickets": 15, "over_number": 2, "ball_in_over": 1},
        _LastAcceptedReading(),
    )

    assert passed is False
    assert reason == ValidationFailureReason.WICKETS_DECREASED


# --- FR-029: OCREvidence preserved internally for every sample --------------


def test_ocr_evidence_preserved_for_every_sample(mocker):
    load_result = _dummy_load_result(duration_seconds=2.0)
    frames = [
        FrameContext(source_video_id="deadbeef", frame_index=i, timestamp_seconds=float(i), frame=_solid_frame(50 + i))
        for i in range(2)
    ]
    mocker.patch("cvip.video.scoreboard_ocr.extract_frames", return_value=_FakeFrameExtractor(frames))
    mocker.patch(
        "cvip.video.scoreboard_ocr.pytesseract.image_to_data",
        return_value=_tesseract_data(HAPPY_PATH_TOKENS),
    )

    request = ScoreboardOcrRequest(load_result=load_result, **DEFAULT_REQUEST_KWARGS)
    with extract_scoreboard(request) as extractor:
        result = extractor.run()

    assert len(extractor.evidence) == len(result.samples)
    for evidence in extractor.evidence:
        assert evidence.raw_text != "" or evidence.ocr_confidence == 0.0
        assert isinstance(evidence.field_confidences, dict)
        assert isinstance(evidence.parsed_fields, dict)
        assert evidence.validation_passed in (True, False, None)


# --- Analysis finding E1: happy-path full-field parse ------------------------


def test_happy_path_parses_every_field_with_high_confidence():
    extractor = _make_extractor()

    parsed, confidences = extractor._parse_fields(HAPPY_PATH_TOKENS)
    passed, reason = extractor._validate_reading(parsed, _LastAcceptedReading())

    assert parsed == {
        "runs": 125,
        "wickets": 3,
        "over_number": 12,
        "ball_in_over": 3,
        "run_rate": 8.5,
        "batter": "Smith",
        "non_striker": "Jones",
        "bowler": "Kumar",
    }
    assert passed is True
    assert reason is None
    assert all(0.0 < c <= 1.0 for c in confidences.values())


# --- Analysis finding E2: text fields carry no historical check ------------


def test_batter_name_change_between_valid_readings_does_not_reduce_confidence():
    extractor = _make_extractor()
    baseline = _LastAcceptedReading()
    baseline.update(runs=50, wickets=2, over_number=10, ball_in_over=0)

    passed, reason = extractor._validate_reading(
        {"batter": "Jones", "runs": 51, "wickets": 2, "over_number": 10, "ball_in_over": 1}, baseline
    )

    assert passed is True
    assert reason is None


# --- US2: result shape is genuinely immutable --------------------------------


def test_scoreboard_sample_is_frozen():
    sample = ScoreboardSample(
        timestamp_seconds=0.0, runs=0, wickets=0, over_number=0, ball_in_over=0,
        batter=None, non_striker=None, bowler=None, run_rate=None,
        raw_text="", ocr_confidence=0.0, parse_confidence=0.0,
    )
    with pytest.raises(Exception):
        sample.runs = 5  # type: ignore[misc]


def test_scoreboard_ocr_result_is_frozen_and_samples_is_a_tuple():
    result = ScoreboardOcrResult(source_video_id="deadbeef", samples=(), total_samples=0)
    with pytest.raises(Exception):
        result.total_samples = 5  # type: ignore[misc]
    assert isinstance(result.samples, tuple)


# --- FR-021: diagnostics field completeness, and partial-state preservation -


def test_diagnostics_contains_every_required_field_on_success(mocker):
    load_result = _dummy_load_result(duration_seconds=2.0)
    # Both frames share pixel-identical ROIs, so the second is served via
    # the ROI-unchanged skip -- deliberately, to exercise that diagnostics
    # field below.
    frames = [
        FrameContext(source_video_id="deadbeef", frame_index=i, timestamp_seconds=float(i), frame=_solid_frame(50))
        for i in range(2)
    ]
    mocker.patch("cvip.video.scoreboard_ocr.extract_frames", return_value=_FakeFrameExtractor(frames))
    mocker.patch(
        "cvip.video.scoreboard_ocr.pytesseract.image_to_data",
        return_value=_tesseract_data(HAPPY_PATH_TOKENS),
    )
    emit_spy = mocker.patch("cvip.video.scoreboard_ocr.emit_diagnostics")

    request = ScoreboardOcrRequest(load_result=load_result, **DEFAULT_REQUEST_KWARGS)
    with extract_scoreboard(request) as extractor:
        extractor.run()

    assert emit_spy.call_count == 1
    output_summary = emit_spy.call_args[0][0].output_summary
    for field_name in (
        "frames_processed=",
        "undetectable_region_count=",
        "average_ocr_confidence=",
        "low_ocr_confidence_count=",
        "average_parse_confidence=",
        "parse_confidence_zero_count=",
        "validation_failure_breakdown=",
        "roi_unchanged_skip_count=",
        "configuration_version=",
    ):
        assert field_name in output_summary, f"{field_name!r} missing from diagnostics output_summary"
    # Both sampled frames share an identical ROI, so the second is skipped.
    assert "roi_unchanged_skip_count=1" in output_summary


def test_diagnostics_preserve_partial_progress_on_mid_run_failure(mocker):
    from cvip.video.frame_extraction_errors import ExtractionError, ExtractionFailureReason

    load_result = _dummy_load_result(duration_seconds=5.0)
    frames = [
        FrameContext(source_video_id="deadbeef", frame_index=i, timestamp_seconds=float(i), frame=_solid_frame(50))
        for i in range(3)
    ]
    mocker.patch(
        "cvip.video.scoreboard_ocr.extract_frames",
        return_value=_FakeFrameExtractor(
            frames, error=ExtractionError(ExtractionFailureReason.SOURCE_UNAVAILABLE_MID_RUN, "gone")
        ),
    )
    mocker.patch(
        "cvip.video.scoreboard_ocr.pytesseract.image_to_data",
        return_value=_tesseract_data(HAPPY_PATH_TOKENS),
    )
    emit_spy = mocker.patch("cvip.video.scoreboard_ocr.emit_diagnostics")

    request = ScoreboardOcrRequest(load_result=load_result, **DEFAULT_REQUEST_KWARGS)
    with pytest.raises(ScoreboardOcrError):
        with extract_scoreboard(request) as extractor:
            extractor.run()

    assert emit_spy.call_count == 1
    output_summary = emit_spy.call_args[0][0].output_summary
    assert "frames_processed=3" in output_summary
