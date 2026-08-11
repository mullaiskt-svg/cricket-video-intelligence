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
from cvip.video.scoreboard_ocr import (
    _LastAcceptedReading,
    ScoreboardOcrExtractor,
    extract_scoreboard,
)
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


def test_ball_in_over_regression_within_the_same_over_is_rejected():
    """PR review finding: over_number staying the same while ball_in_over
    goes backwards (e.g. "12.5" followed by a noisy "12.3") is an
    impossible sequence within a single over -- over_number alone not
    decreasing must not be enough to accept it."""
    extractor = _make_extractor()
    baseline = _LastAcceptedReading()
    baseline.update(runs=50, wickets=2, over_number=12, ball_in_over=5)

    passed, reason = extractor._validate_reading(
        {"batter": "Smith", "runs": 51, "wickets": 2, "over_number": 12, "ball_in_over": 3}, baseline
    )

    assert passed is False
    assert reason == ValidationFailureReason.INVALID_OVER_SEQUENCE


def test_ball_in_over_advancing_within_the_same_over_is_accepted():
    extractor = _make_extractor()
    baseline = _LastAcceptedReading()
    baseline.update(runs=50, wickets=2, over_number=12, ball_in_over=3)

    passed, reason = extractor._validate_reading(
        {"batter": "Smith", "runs": 51, "wickets": 2, "over_number": 12, "ball_in_over": 5}, baseline
    )

    assert passed is True
    assert reason is None


def test_ball_in_over_reset_on_a_new_over_is_accepted():
    extractor = _make_extractor()
    baseline = _LastAcceptedReading()
    baseline.update(runs=50, wickets=2, over_number=12, ball_in_over=5)

    passed, reason = extractor._validate_reading(
        {"batter": "Smith", "runs": 51, "wickets": 2, "over_number": 13, "ball_in_over": 1}, baseline
    )

    assert passed is True
    assert reason is None


# --- Post-implementation fix: implausible over_number is rejected, not --
# --- accepted-and-baseline-poisoning (real-video finding, PLATINUM CUP  --
# --- FINAL full-match validation) ----------------------------------------


def test_implausibly_large_over_number_is_rejected_not_accepted():
    """A garbled OCR frame that coincidentally matches the generic
    over.ball token shape against unrelated on-screen text (e.g. a clock
    display) must not be accepted just because it isn't a *decrease*
    relative to the baseline -- an absolute sanity ceiling is needed too,
    or a single such frame poisons the baseline for the rest of the
    innings (real match: over_number=600 accepted, then ~14 legitimate
    overs' worth of readings rejected as INVALID_OVER_SEQUENCE against
    that corrupted baseline)."""
    extractor = _make_extractor()
    baseline = _LastAcceptedReading()
    baseline.update(runs=37, wickets=2, over_number=5, ball_in_over=2)

    passed, reason = extractor._validate_reading({"over_number": 600, "ball_in_over": 0}, baseline)

    assert passed is False
    assert reason == ValidationFailureReason.INVALID_OVER_SEQUENCE


def test_implausibly_large_over_number_does_not_poison_the_baseline():
    """The concrete failure mode this fix targets: confirm a bogus,
    rejected over_number=600 reading leaves the baseline untouched, so the
    NEXT genuine reading (a real over 6) still validates correctly against
    the real baseline rather than against a corrupted one."""
    extractor = _make_extractor()
    baseline = _LastAcceptedReading()
    baseline.update(runs=37, wickets=2, over_number=5, ball_in_over=2)

    passed, _ = extractor._validate_reading({"over_number": 600, "ball_in_over": 0}, baseline)
    assert passed is False
    # _validate_reading() is a pure predicate -- baseline.update() is only
    # ever called by _process_frame() when validation_passed is True, so a
    # rejected reading like this one never reaches it. Confirm the baseline
    # itself is still exactly where it was before this rejected reading.
    assert baseline.over_number == 5

    passed, reason = extractor._validate_reading(
        {"batter": "Smith", "runs": 38, "wickets": 2, "over_number": 6, "ball_in_over": 1}, baseline
    )
    assert passed is True
    assert reason is None


def test_over_number_at_the_sanity_ceiling_is_still_accepted():
    extractor = _make_extractor()
    baseline = _LastAcceptedReading()
    baseline.update(runs=50, wickets=2, over_number=49, ball_in_over=0)

    passed, reason = extractor._validate_reading(
        {"batter": "Smith", "runs": 51, "wickets": 2, "over_number": 50, "ball_in_over": 1}, baseline
    )

    assert passed is True
    assert reason is None


# --- Post-implementation fix: an over/ball-only reading (no accompanying --
# --- runs/wickets) must not advance the baseline's over_number/ball_in_over
# --- (real-video finding, PLATINUM CUP FINAL full-match validation) -----


def test_over_only_update_without_runs_and_wickets_does_not_advance_baseline():
    """A reading with over_number/ball_in_over but no runs/wickets can only
    have come from the generic parser's standalone over.ball token regex
    matching in isolation -- no compound-score evidence backs it up. It
    must not be trusted to advance the baseline, or a single spurious
    match (unrelated on-screen text coincidentally shaped like "N.M")
    silently jumps the baseline ahead of where the game actually is,
    causing every subsequent genuine reading to be rejected as an
    over-number decrease."""
    baseline = _LastAcceptedReading()
    baseline.update(runs=5, wickets=2, over_number=1, ball_in_over=0)

    baseline.update(runs=None, wickets=None, over_number=5, ball_in_over=0)

    assert baseline.over_number == 1
    assert baseline.ball_in_over == 0
    assert baseline.runs == 5
    assert baseline.wickets == 2


def test_over_and_ball_advance_together_with_runs_and_wickets():
    baseline = _LastAcceptedReading()
    baseline.update(runs=5, wickets=2, over_number=1, ball_in_over=0)

    baseline.update(runs=9, wickets=2, over_number=1, ball_in_over=3)

    assert baseline.over_number == 1
    assert baseline.ball_in_over == 3
    assert baseline.runs == 9


def test_over_only_reading_does_not_poison_subsequent_validation():
    """End-to-end version of the baseline-corruption scenario: confirm a
    genuine next-ball reading (over=1, ball=2) still validates correctly
    after an over-only spurious reading (over=5) was fed through the same
    baseline -- it must not be rejected as INVALID_OVER_SEQUENCE against a
    corrupted baseline."""
    extractor = _make_extractor()
    baseline = _LastAcceptedReading()
    baseline.update(runs=5, wickets=2, over_number=1, ball_in_over=0)

    # A spurious over.ball-only reading -- passes _validate_reading() (it's
    # not a decrease, and has_any_score_field is satisfied by over_number
    # alone), but must not corrupt the baseline via _LastAcceptedReading.update().
    passed, _ = extractor._validate_reading({"over_number": 5, "ball_in_over": 0}, baseline)
    assert passed is True
    baseline.update(runs=None, wickets=None, over_number=5, ball_in_over=0)
    assert baseline.over_number == 1  # unchanged

    passed, reason = extractor._validate_reading(
        {"batter": "Smith", "runs": 9, "wickets": 2, "over_number": 1, "ball_in_over": 2}, baseline
    )
    assert passed is True
    assert reason is None


# --- Post-implementation fix: an implausible single-reading runs increase -
# --- is rejected even when it isn't a decrease and over/ball are in-range -
# --- (real-video finding, PLATINUM CUP FINAL: a single Tesseract-inserted -
# --- digit turned a real "31-3/6.1(20)" into "311-3/6.1(20)") ------------


def test_implausible_runs_jump_on_the_same_ball_is_rejected():
    extractor = _make_extractor()
    baseline = _LastAcceptedReading()
    baseline.update(runs=31, wickets=3, over_number=6, ball_in_over=1)

    passed, reason = extractor._validate_reading(
        {"batter": "Smith", "runs": 311, "wickets": 3, "over_number": 6, "ball_in_over": 1}, baseline
    )

    assert passed is False
    assert reason == ValidationFailureReason.RUNS_DECREASED


def test_implausible_runs_jump_does_not_poison_the_baseline():
    extractor = _make_extractor()
    baseline = _LastAcceptedReading()
    baseline.update(runs=31, wickets=3, over_number=6, ball_in_over=1)

    passed, _ = extractor._validate_reading(
        {"batter": "Smith", "runs": 311, "wickets": 3, "over_number": 6, "ball_in_over": 1}, baseline
    )
    assert passed is False
    assert baseline.runs == 31  # _validate_reading is a pure predicate; unchanged

    passed, reason = extractor._validate_reading(
        {"batter": "Smith", "runs": 32, "wickets": 3, "over_number": 6, "ball_in_over": 2}, baseline
    )
    assert passed is True
    assert reason is None


def test_large_runs_jump_across_a_genuine_over_advance_is_accepted():
    """A large jump is only suspect on the *same* ball -- once over_number
    (or ball_in_over) has genuinely advanced, no magnitude cap applies, so
    a big catch-up jump after a real sampling gap spanning several
    deliveries must still be accepted."""
    extractor = _make_extractor()
    baseline = _LastAcceptedReading()
    baseline.update(runs=30, wickets=3, over_number=6, ball_in_over=0)

    passed, reason = extractor._validate_reading(
        {"batter": "Smith", "runs": 62, "wickets": 3, "over_number": 8, "ball_in_over": 0}, baseline
    )

    assert passed is True
    assert reason is None


def test_wickets_only_slightly_decreased_is_rejected_not_treated_as_a_transition():
    """specs/015-innings-transition-detection supersedes this test's own
    pre-015 premise. Previously: FR-014's innings-transition heuristic
    waved through ANY simultaneous runs+wickets decrease, however small,
    as a possible innings transition -- which meant a coincidental drop
    (wickets 4->3, nowhere near a genuine innings-opening 0 or 1) silently
    corrupted the baseline, requiring a separate "recovery jump" workaround
    to recognize the next genuinely correct reading. specs/015's real-
    incident investigation found this exact mechanism (an implausible
    reading being accepted as a transition and poisoning the baseline)
    causing real data corruption elsewhere in this pipeline
    (scoreboard_readings.innings). The shared InningsTracker's
    reset-plausibility check (wickets must land at or under
    max_wickets_for_new_segment, not merely "lower than before") now
    correctly rejects this as ordinary noise -- so the baseline is never
    corrupted in the first place, and no special recovery handling is
    needed at all."""
    extractor = _make_extractor()
    baseline = _LastAcceptedReading()
    # Prime the extractor's own internal InningsTracker to match `baseline`
    # (mirrors real usage: _validate_reading and baseline.update() are
    # always called together, in order, starting from the very first frame).
    extractor._validate_reading(
        {"batter": "Smith", "runs": 69, "wickets": 4, "over_number": 12, "ball_in_over": 2}, baseline
    )
    baseline.update(runs=69, wickets=4, over_number=12, ball_in_over=2)

    # A garbled reading coincidentally drops both runs and wickets, but
    # wickets only drops by one (4->3) -- not a plausible innings reset.
    passed, reason = extractor._validate_reading(
        {"batter": "Smith", "runs": 8, "wickets": 3, "over_number": 9, "ball_in_over": 2}, baseline
    )
    assert passed is False
    assert reason == ValidationFailureReason.RUNS_DECREASED

    # The baseline was never corrupted -- the next genuinely correct
    # reading (matching the ORIGINAL baseline) passes normally, with no
    # special "recovery" handling required.
    passed, reason = extractor._validate_reading(
        {"batter": "Smith", "runs": 69, "wickets": 4, "over_number": 12, "ball_in_over": 2}, baseline
    )
    assert passed is True
    assert reason is None


# --- specs/015-innings-transition-detection: innings-transition heuristic ---


def test_innings_transition_suppresses_monotonic_checks():
    extractor = _make_extractor()
    baseline = _LastAcceptedReading()
    # Prime the extractor's own internal InningsTracker (see the priming
    # note in test_wickets_only_slightly_decreased_is_rejected_not_treated_as_a_transition).
    extractor._validate_reading(
        {"batter": "Smith", "runs": 180, "wickets": 9, "over_number": 45, "ball_in_over": 2}, baseline
    )
    baseline.update(runs=180, wickets=9, over_number=45, ball_in_over=2)

    # A genuine new innings: runs and wickets both drop near zero, AND
    # over_number resets near the start -- fully corroborated, so the
    # over_number drop (which alone would otherwise be INVALID_OVER_SEQUENCE)
    # is correctly permitted.
    passed, reason = extractor._validate_reading(
        {"batter": "Smith", "runs": 4, "wickets": 0, "over_number": 1, "ball_in_over": 1}, baseline
    )

    assert passed is True
    assert reason is None


# --- FR-030/FR-031: structurally unparseable essential field ----------------
# specs/011-club-broadcast-overlay-support/ real-video finding (quickstart.md
# Steps 3/5): `batter` no longer gates a reading with a fully valid score --
# see _validate_reading()'s docstring. PLAYER_PARSE_FAILED now fires only
# when *nothing* usable (neither a name nor any score field) was found.


def test_missing_batter_field_with_valid_score_still_passes():
    extractor = _make_extractor()
    baseline = _LastAcceptedReading()

    passed, reason = extractor._validate_reading(
        {"runs": 10, "wickets": 1, "over_number": 2, "ball_in_over": 3}, baseline
    )

    assert passed is True
    assert reason is None


def test_missing_batter_field_with_valid_score_still_updates_baseline_for_next_reading():
    """The concrete behavior this fix targets: a name-less-but-score-valid
    reading must still advance the accepted-reading baseline, so the NEXT
    reading's monotonic checks compare against it rather than against a
    stale, multi-ball-old baseline (the real-video finding: this gap is what
    caused Event Detection to silently miss FOUR/SIX events)."""
    extractor = _make_extractor()
    baseline = _LastAcceptedReading()
    baseline.update(runs=10, wickets=0, over_number=2, ball_in_over=0)

    # A name-less reading with a valid, monotonically-later score.
    passed, _ = extractor._validate_reading(
        {"runs": 14, "wickets": 0, "over_number": 2, "ball_in_over": 1}, baseline
    )
    assert passed is True
    baseline.update(runs=14, wickets=0, over_number=2, ball_in_over=1)

    # A subsequent reading with runs *between* the two prior values would
    # have been wrongly rejected as RUNS_DECREASED had the name-less
    # reading above not updated the baseline.
    passed, reason = extractor._validate_reading(
        {"batter": "Smith", "runs": 12, "wickets": 0, "over_number": 2, "ball_in_over": 2}, baseline
    )
    assert passed is False
    assert reason == ValidationFailureReason.RUNS_DECREASED


def test_reading_with_no_name_and_no_score_field_yields_player_parse_failed():
    extractor = _make_extractor()

    passed, reason = extractor._validate_reading({}, _LastAcceptedReading())

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
        # specs/011-club-broadcast-overlay-support/ research.md Decision 4/6:
        # GenericBroadcastParser's asterisk-backed batter is "verified",
        # distinguishing it from ClubBroadcastParser's "best_effort".
        "batter_attribution": "verified",
        "parser_strategy": "generic_broadcast",
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


# =============================================================================
# specs/011-club-broadcast-overlay-support/: Club Broadcast Overlay Support
# (Scoreboard OCR Amendment) -- see that feature's spec.md/research.md/
# data-model.md for the full design. Token-list evidence below is drawn
# directly from research.md's raw Tesseract capture against the real
# fixture (First8Overs.mp4).
# =============================================================================

# The real evidence's token stream, reconstructed as (text, confidence)
# pairs: two batters each immediately followed by a runs-and-balls stats
# token (one joined, one split -- matching what Tesseract actually
# produced), a multi-word team name that must NOT be mistaken for a player,
# the compound score (with its observed stray leading "_"), and a bowler
# immediately followed by their own stats token.
CLUB_EVIDENCE_TOKENS = [
    ("MAHESH", 90.0),
    ("0", 85.0),
    ("(0)", 80.0),
    ("SAI", 88.0),
    ("KRISHNA", 87.0),
    ("0(0)", 84.0),
    ("Chai", 70.0),
    ("Cricket", 70.0),
    ("Club", 70.0),
    ("_0-0/0.0(20)", 92.0),
    ("BHARATH", 89.0),
    ("0-0(0)", 83.0),
]


# --- T007 (US1): compound score populates runs/wickets/over/ball -----------
# (_COMPOUND_SCORE_RE's own matching behavior is tested directly in
# tests/unit/test_scoreboard_parsers.py -- these two tests specifically
# cover _parse_fields()'s dispatch-and-stamp integration, which stays here.)


def test_compound_score_token_populates_score_fields_and_raw_token():
    extractor = _make_extractor()

    parsed, confidences = extractor._parse_fields(CLUB_EVIDENCE_TOKENS)

    assert parsed["runs"] == 0
    assert parsed["wickets"] == 0
    assert parsed["over_number"] == 0
    assert parsed["ball_in_over"] == 0
    assert parsed["raw_compound_score_token"] == "_0-0/0.0(20)"
    assert parsed["parser_strategy"] == "club_broadcast"
    assert confidences["runs"] == pytest.approx(0.92)


# --- T008 (US1): original-format reading is unaffected (FR-002) -----------


def test_original_format_reading_parses_identically_post_amendment():
    extractor = _make_extractor()

    parsed, confidences = extractor._parse_fields(HAPPY_PATH_TOKENS)

    assert parsed["parser_strategy"] == "generic_broadcast"
    assert parsed["runs"] == 125 and parsed["wickets"] == 3
    assert parsed["over_number"] == 12 and parsed["ball_in_over"] == 3
    assert parsed["batter"] == "Smith" and parsed["batter_attribution"] == "verified"
    assert parsed["non_striker"] == "Jones"
    assert parsed["bowler"] == "Kumar"


# (_select_parser()/select_parser() selection+determinism,
# _find_stats_marker_positions(), and _walk_name_fragment() are tested
# directly in tests/unit/test_scoreboard_parsers.py, alongside the parsers
# that use them.)


# --- T016 (US2): batter/non_striker populate, team-name excluded -----------


def test_club_broadcast_batter_and_non_striker_populate_excluding_team_name():
    extractor = _make_extractor()

    parsed, _ = extractor._parse_fields(CLUB_EVIDENCE_TOKENS)

    assert parsed["batter"] == "MAHESH"
    assert parsed["non_striker"] == "SAI KRISHNA"
    for team_fragment in ("Chai", "Cricket", "Club"):
        assert parsed["batter"] != team_fragment
        assert parsed["non_striker"] != team_fragment
        assert parsed.get("bowler") != team_fragment


# --- T017 (US2): batter_attribution best_effort vs verified ----------------


def test_club_broadcast_batter_attribution_is_best_effort():
    extractor = _make_extractor()

    parsed, _ = extractor._parse_fields(CLUB_EVIDENCE_TOKENS)

    assert parsed["batter_attribution"] == "best_effort"


def test_generic_broadcast_batter_attribution_is_verified():
    extractor = _make_extractor()

    parsed, _ = extractor._parse_fields(HAPPY_PATH_TOKENS)

    assert parsed["batter_attribution"] == "verified"


# --- T018 (US2, amended per real-video finding): no locatable name --------
# Originally: a club-broadcast reading with no locatable name unconditionally
# failed as PLAYER_PARSE_FAILED (matching FR-030's blanket batter gate).
# specs/011-.../quickstart.md Steps 3/5 against the real First8Overs.mp4
# recording found this caused Event Detection to silently miss FOUR/SIX
# events spanning the resulting timeline gaps -- _validate_reading() no
# longer gates a valid score on batter presence (see its docstring).


def test_club_broadcast_reading_with_no_locatable_name_but_valid_score_still_passes():
    extractor = _make_extractor()
    tokens = [("_0-0/0.0(20)", 90.0)]  # score only, no adjacent name anywhere

    parsed, _ = extractor._parse_fields(tokens)
    passed, reason = extractor._validate_reading(parsed, _LastAcceptedReading())

    assert parsed.get("batter") is None
    assert parsed.get("runs") == 0
    assert passed is True
    assert reason is None


def test_club_broadcast_reading_with_no_name_and_no_score_yields_player_parse_failed():
    extractor = _make_extractor()
    tokens = [("Chai", 70.0), ("Cricket", 70.0), ("Club", 70.0)]  # team-name text only

    parsed, _ = extractor._parse_fields(tokens)
    passed, reason = extractor._validate_reading(parsed, _LastAcceptedReading())

    assert parsed.get("batter") is None
    assert parsed.get("runs") is None
    assert passed is False
    assert reason == ValidationFailureReason.PLAYER_PARSE_FAILED


# --- T019 (US2, analysis finding C1): shared validation is parser-agnostic -


def test_shared_validation_fires_runs_decreased_for_a_club_broadcast_reading():
    """FR-009: _validate_reading() must apply the same monotonic-rule check
    to a ClubBroadcastParser-produced reading as to a GenericBroadcastParser
    one -- parser strategy has no influence on rule-validation behavior."""
    extractor = _make_extractor()
    baseline = _LastAcceptedReading()
    baseline.update(runs=10, wickets=0, over_number=1, ball_in_over=0)

    club_reading, _ = extractor._parse_fields(CLUB_EVIDENCE_TOKENS)
    club_reading = dict(club_reading, runs=8)  # intentionally violates the monotonic-runs rule

    passed, reason = extractor._validate_reading(club_reading, baseline)

    assert passed is False
    assert reason == ValidationFailureReason.RUNS_DECREASED


def test_shared_validation_fires_invalid_over_sequence_for_a_club_broadcast_reading():
    extractor = _make_extractor()
    baseline = _LastAcceptedReading()
    baseline.update(runs=10, wickets=0, over_number=5, ball_in_over=0)

    club_reading, _ = extractor._parse_fields(CLUB_EVIDENCE_TOKENS)
    club_reading = dict(club_reading, runs=15, over_number=3)  # invalid regression

    passed, reason = extractor._validate_reading(club_reading, baseline)

    assert passed is False
    assert reason == ValidationFailureReason.INVALID_OVER_SEQUENCE


# --- T025 (US3): bowler populates without a label ---------------------------


def test_club_broadcast_bowler_populates_from_post_score_stats_marker():
    extractor = _make_extractor()

    parsed, confidences = extractor._parse_fields(CLUB_EVIDENCE_TOKENS)

    assert parsed["bowler"] == "BHARATH"
    assert confidences["bowler"] == pytest.approx(0.89)


# --- T026 (US3): original-format label-based bowler extraction unaffected --


def test_generic_broadcast_bowler_still_requires_a_label():
    extractor = _make_extractor()

    parsed, _ = extractor._parse_fields(HAPPY_PATH_TOKENS)

    assert parsed["bowler"] == "Kumar"
    # No stray B:-label logic leaks into a token list with no compound score.
    assert "raw_compound_score_token" not in parsed


# --- T029/T031 (Polish, research.md Decision 8): parser-strategy diagnostics


def test_parser_strategy_counters_increment_on_record_stats():
    extractor = _make_extractor()
    club_parsed, club_confidences = extractor._parse_fields(CLUB_EVIDENCE_TOKENS)
    club_passed, club_reason = extractor._validate_reading(club_parsed, _LastAcceptedReading())
    from cvip.video.scoreboard_ocr_models import OCREvidence

    club_sample = ScoreboardSample(
        timestamp_seconds=0.0, runs=club_parsed.get("runs"), wickets=club_parsed.get("wickets"),
        over_number=club_parsed.get("over_number"), ball_in_over=club_parsed.get("ball_in_over"),
        batter=club_parsed.get("batter"), non_striker=club_parsed.get("non_striker"),
        bowler=club_parsed.get("bowler"), run_rate=club_parsed.get("run_rate"),
        raw_text="", ocr_confidence=0.9, parse_confidence=1.0 if club_passed else 0.0,
    )
    club_evidence = OCREvidence(
        raw_text="", preprocessed_image_ref=None, ocr_confidence=0.9,
        field_confidences=club_confidences, parsed_fields=club_parsed,
        validation_passed=club_passed, validation_failure_reason=club_reason,
    )

    extractor._record_stats(club_sample, club_evidence)

    assert extractor._parser_strategy_counts["club_broadcast"] == 1
    assert extractor._parser_strategy_counts["generic_broadcast"] == 0


def test_diagnostics_output_summary_contains_parser_strategy_breakdown_for_mixed_run(mocker):
    """T032: a run whose readings alternate between original-format and
    club-broadcast-format tokens -- each is independently and correctly
    classified/parsed (spec.md Edge Cases), and the diagnostics summary
    (research.md Decision 8) reflects both strategies' usage counts."""
    load_result = _dummy_load_result(duration_seconds=2.0)
    # Deliberately different-content ROIs (not just +1) -- otherwise the
    # ROI-unchanged skip (research.md Decision 1) would reuse the first
    # frame's sample for the second, defeating this test's whole point.
    frames = [
        FrameContext(source_video_id="deadbeef", frame_index=0, timestamp_seconds=0.0, frame=_solid_frame(50)),
        FrameContext(source_video_id="deadbeef", frame_index=1, timestamp_seconds=1.0, frame=_solid_frame(200)),
    ]
    mocker.patch("cvip.video.scoreboard_ocr.extract_frames", return_value=_FakeFrameExtractor(frames))
    mocker.patch(
        "cvip.video.scoreboard_ocr.pytesseract.image_to_data",
        side_effect=[_tesseract_data(HAPPY_PATH_TOKENS), _tesseract_data(CLUB_EVIDENCE_TOKENS)],
    )
    emit_spy = mocker.patch("cvip.video.scoreboard_ocr.emit_diagnostics")

    request = ScoreboardOcrRequest(load_result=load_result, **DEFAULT_REQUEST_KWARGS)
    with extract_scoreboard(request) as extractor:
        result = extractor.run()

    assert result.samples[0].batter == "Smith"  # generic_broadcast reading
    assert result.samples[1].batter == "MAHESH"  # club_broadcast reading

    output_summary = emit_spy.call_args[0][0].output_summary
    assert (
        "parser_strategy=(club_broadcast=1, generic_broadcast=1, separate_token_broadcast=0)"
        in output_summary
    )
    assert "generic_broadcast_unparsed_count=" in output_summary


# --- T033 coverage gate: critical-path branches not exercised above --------


def test_club_broadcast_stats_marker_with_no_preceding_name_is_skipped():
    """A stats marker with no name-shaped token immediately preceding it
    (e.g. a garbled reading that dropped the name entirely) must simply be
    skipped, not raise or fabricate a name."""
    extractor = _make_extractor()
    tokens = [("0(0)", 80.0), ("0-0/0.0(20)", 92.0)]

    parsed, _ = extractor._parse_fields(tokens)

    assert parsed.get("batter") is None
    assert parsed["parser_strategy"] == "club_broadcast"

# (select_parser()'s defensive no-match invariant is tested directly in
# tests/unit/test_scoreboard_parsers.py.)


# =============================================================================
# Post-implementation amendment: preprocessing-strategy warm-up and locking
# (scoreboard_preprocessing.py). See that module's docstring for the full
# "why a locked-in choice per run, not a per-frame fallback chain" rationale.
# =============================================================================

# A minimal token stream matching SeparateTokenBroadcastParser's own
# matches() signature (a bare "{over}.{ball}" token immediately followed by
# its own "({total_overs})" token) -- sufficient to trigger the warm-up
# lock without needing this parser's full field-extraction detail.
SEPARATE_TOKEN_MINIMAL_TOKENS = [("1.0", 90.0), ("(20)", 85.0)]


def test_preprocessing_strategy_locks_on_first_specific_parser_match(mocker):
    extractor = _make_extractor()
    mocker.patch(
        "cvip.video.scoreboard_ocr.pytesseract.image_to_data",
        return_value=_tesseract_data(SEPARATE_TOKEN_MINIMAL_TOKENS),
    )
    roi = _solid_frame(0, size=(20, 100, 3))

    assert extractor._locked_strategy_name is None
    extractor._process_frame(roi, 5.0, _LastAcceptedReading())

    assert extractor._locked_strategy_name == "adaptive_mean"


def test_preprocessing_strategy_locks_to_otsu_for_club_broadcast(mocker):
    extractor = _make_extractor()
    mocker.patch(
        "cvip.video.scoreboard_ocr.pytesseract.image_to_data",
        return_value=_tesseract_data(CLUB_EVIDENCE_TOKENS),
    )
    roi = _solid_frame(0, size=(20, 100, 3))

    extractor._process_frame(roi, 5.0, _LastAcceptedReading())

    assert extractor._locked_strategy_name == "otsu_threshold"


def test_preprocessing_strategy_stays_unlocked_while_only_generic_matches(mocker):
    """A run whose warm-up frames only ever match the universal
    GenericBroadcastParser fallback (never a specific format) must not
    lock in prematurely -- it should keep trying, up to the ceiling."""
    extractor = _make_extractor()
    mocker.patch(
        "cvip.video.scoreboard_ocr.pytesseract.image_to_data",
        return_value=_tesseract_data(HAPPY_PATH_TOKENS),
    )
    roi = _solid_frame(0, size=(20, 100, 3))

    from cvip.video.scoreboard_ocr import PREPROCESSING_WARMUP_SAMPLE_LIMIT

    for _ in range(PREPROCESSING_WARMUP_SAMPLE_LIMIT - 1):
        extractor._process_frame(roi, 5.0, _LastAcceptedReading())
        assert extractor._locked_strategy_name is None

    extractor._process_frame(roi, 5.0, _LastAcceptedReading())
    assert extractor._locked_strategy_name == "otsu_threshold"


def test_preprocessing_strategy_locks_to_otsu_after_warmup_ceiling_with_no_tokens(mocker):
    """Frames that yield zero tokens at all (not even a Generic match)
    count toward the warm-up ceiling too -- an unlucky opening stretch of
    undetectable frames must not stall locking forever."""
    extractor = _make_extractor()
    mocker.patch("cvip.video.scoreboard_ocr.pytesseract.image_to_data", return_value=_tesseract_data([]))
    roi = _solid_frame(0, size=(20, 100, 3))

    from cvip.video.scoreboard_ocr import PREPROCESSING_WARMUP_SAMPLE_LIMIT

    for _ in range(PREPROCESSING_WARMUP_SAMPLE_LIMIT):
        extractor._process_frame(roi, 5.0, _LastAcceptedReading())

    assert extractor._locked_strategy_name == "otsu_threshold"


def test_locked_preprocessing_strategy_used_for_subsequent_frames(mocker):
    """Once locked, later frames' preprocessing must actually use the
    locked strategy -- verified via the real cv2 pipeline output, not just
    the state flag, since that's what Tesseract actually receives."""
    extractor = _make_extractor()
    mocker.patch(
        "cvip.video.scoreboard_ocr.pytesseract.image_to_data",
        return_value=_tesseract_data(SEPARATE_TOKEN_MINIMAL_TOKENS),
    )
    roi = _solid_frame(0, size=(20, 100, 3))
    extractor._process_frame(roi, 5.0, _LastAcceptedReading())
    assert extractor._locked_strategy_name == "adaptive_mean"

    spy = mocker.spy(extractor, "_preprocess_roi")
    extractor._process_frame(roi, 6.0, _LastAcceptedReading())

    spy.assert_called_once_with(roi, "adaptive_mean")


def test_preprocessing_strategy_never_relocks_once_set(mocker):
    """A run that locks onto one format must not re-evaluate on later
    frames, even if a later frame's tokens would structurally match a
    different parser (e.g. a garbled misread) -- the lock is per-run,
    not per-frame."""
    extractor = _make_extractor()
    mocker.patch(
        "cvip.video.scoreboard_ocr.pytesseract.image_to_data",
        return_value=_tesseract_data(SEPARATE_TOKEN_MINIMAL_TOKENS),
    )
    roi = _solid_frame(0, size=(20, 100, 3))
    extractor._process_frame(roi, 5.0, _LastAcceptedReading())
    assert extractor._locked_strategy_name == "adaptive_mean"

    mocker.patch(
        "cvip.video.scoreboard_ocr.pytesseract.image_to_data",
        return_value=_tesseract_data(CLUB_EVIDENCE_TOKENS),
    )
    extractor._process_frame(roi, 6.0, _LastAcceptedReading())

    assert extractor._locked_strategy_name == "adaptive_mean"  # unchanged


def test_diagnostics_report_locked_preprocessing_strategy(mocker):
    load_result = _dummy_load_result(duration_seconds=1.0)
    frames = [FrameContext(source_video_id="deadbeef", frame_index=0, timestamp_seconds=0.0, frame=_solid_frame(50))]
    mocker.patch("cvip.video.scoreboard_ocr.extract_frames", return_value=_FakeFrameExtractor(frames))
    mocker.patch(
        "cvip.video.scoreboard_ocr.pytesseract.image_to_data",
        return_value=_tesseract_data(SEPARATE_TOKEN_MINIMAL_TOKENS),
    )
    emit_spy = mocker.patch("cvip.video.scoreboard_ocr.emit_diagnostics")

    request = ScoreboardOcrRequest(load_result=load_result, **DEFAULT_REQUEST_KWARGS)
    with extract_scoreboard(request) as extractor:
        extractor.run()

    output_summary = emit_spy.call_args[0][0].output_summary
    assert "preprocessing_strategy_locked=adaptive_mean" in output_summary


def test_preprocess_roi_defaults_to_otsu_when_no_strategy_given():
    """Backward-compatibility invariant: every pre-existing direct caller
    of _preprocess_roi() (this test file's own earlier tests included)
    passes no strategy_name at all -- must keep behaving exactly as
    before this amendment."""
    extractor = _make_extractor(preprocess_grayscale=True, preprocess_threshold=True, preprocess_upscale=1)
    roi = _solid_frame(128, size=(20, 100, 3))

    result = extractor._preprocess_roi(roi)

    assert set(np.unique(result)).issubset({0, 255})  # Otsu binarizes; a solid-color ROI collapses to one value
