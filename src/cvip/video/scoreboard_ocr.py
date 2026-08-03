"""Scoreboard OCR: extract_scoreboard() and ScoreboardOcrExtractor.

See specs/005-scoreboard-ocr/contracts/scoreboard_ocr_contract.md
for the full contract this module implements, and
specs/011-club-broadcast-overlay-support/ for the club-broadcast-overlay
amendment (compound score strings, best-effort name extraction). The
structured-parsing stage itself is a pluggable, per-broadcast-format
architecture living in scoreboard_parsers.py (see that module's docstring
for the extension guide) -- this module owns everything *around* parsing:
ROI extraction, preprocessing, Tesseract invocation, cricket-rule
validation, and diagnostics, all parser-agnostic by construction.
"""

from __future__ import annotations

import dataclasses
import math
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
import pytesseract
from pytesseract import Output

from cvip.common.diagnostics import DiagnosticsTracker, ExecutionDiagnostics, emit_diagnostics
from cvip.video.frame_extraction import extract_frames
from cvip.video.frame_extraction_errors import ExtractionError, ExtractionFailureReason
from cvip.video.frame_extraction_models import ExtractionRequest, SamplingMode
from cvip.video.models import LoadStatus
from cvip.video.scoreboard_ocr_errors import (
    ScoreboardOcrError,
    ScoreboardOcrFailureReason,
    ValidationFailureReason,
)
from cvip.video.scoreboard_ocr_models import (
    OCREvidence,
    ScoreboardOcrRequest,
    ScoreboardOcrResult,
    ScoreboardSample,
)
from cvip.video.scoreboard_parsers import PARSER_PREFERRED_STRATEGY, PARSERS, GenericBroadcastParser, select_parser
from cvip.video.scoreboard_preprocessing import DEFAULT_STRATEGY_NAME, PREPROCESSING_STRATEGIES

MODULE_NAME = "video.scoreboard_ocr"

# The platform's configured sampling rate (config/default.yaml's
# video.sample_fps) -- this feature's own dedicated request to the Frame
# Extraction Service, independent of any other module's own sampling rate.
SAMPLING_RATE_FPS = 1.0

# The mean whole-ROI absolute-difference tolerance (0-255 scale) below which
# a sampled frame's scoreboard ROI is considered pixel-unchanged from the
# previous sampled frame's ROI (research.md Decision 1) -- absorbs ordinary
# video-compression noise on an otherwise-static graphic without masking a
# genuine scoreboard update. A reasoned, not empirically tuned, choice (no
# golden dataset yet); tune here if real broadcast footage shows it's wrong.
ROI_UNCHANGED_TOLERANCE = 2.0

# Valid ranges for the count-like fields (spec.md Assumptions).
WICKETS_MAX = 10
BALL_IN_OVER_MAX = 6

# How many samples to preprocess with scoreboard_preprocessing.py's
# DEFAULT_STRATEGY_NAME (Otsu) before giving up on identifying a specific
# broadcast format and locking Otsu in permanently for this run. Each
# counted warm-up sample also trials every other registered strategy
# against that same frame before giving up on it (see _process_frame),
# so this ceiling bounds "frames whose ROI was undetectable/generic under
# every strategy," not just "frames Otsu alone couldn't parse." In
# practice this rarely matters: a specific parser's `matches()` signature
# has been observed to fire on the very first successfully-tokenized
# frame, so this ceiling only bounds the worst case (e.g. a run whose
# opening samples are all undetectable). See scoreboard_preprocessing.py's
# module docstring for the full warm-up-then-lock rationale.
PREPROCESSING_WARMUP_SAMPLE_LIMIT = 5

# Post-implementation fix (specs/011-club-broadcast-overlay-support/'s
# full-match real-video validation, PLATINUM CUP FINAL): over_number had no
# sanity ceiling, unlike wickets/ball_in_over above. A single garbled OCR
# frame produced a bogus over_number in the hundreds (a misread of unrelated
# on-screen text coincidentally matching the generic over.ball token shape)
# that passed validation -- nothing in range [0, over_number_max] rejects
# it, and it isn't a decrease relative to the real baseline. That one
# accepted reading then became the new baseline, and every subsequent
# genuine reading for the rest of the innings was rejected as
# INVALID_OVER_SEQUENCE (over_number always less than the corrupted
# baseline) -- one bad frame silently blacked out ~74 minutes / ~14 overs
# of an otherwise fully-readable innings. No format on this platform's
# roadmap runs beyond 50 overs; this ceiling exists purely to catch
# obviously-impossible values, not to encode a specific match format.
OVER_NUMBER_MAX = 50


# Tesseract's own confidence scale is 0-100; this platform's confidence
# fields are always 0.0-1.0.
_TESSERACT_CONFIDENCE_SCALE = 100.0

# "Assume a single uniform block of text" -- a scoreboard graphic is a small,
# dense text block, not a full page (research.md-style reasoned default).
_TESSERACT_CONFIG = "--psm 6"

_ExtractionFailureToScoreboardOcrFailure = {
    ExtractionFailureReason.SOURCE_UNAVAILABLE_MID_RUN: ScoreboardOcrFailureReason.SOURCE_UNAVAILABLE_MID_RUN,
    ExtractionFailureReason.DECODE_FAILURE_MID_RUN: ScoreboardOcrFailureReason.DECODE_FAILURE_MID_RUN,
}


def extract_scoreboard(request: ScoreboardOcrRequest) -> "ScoreboardOcrExtractor":
    """Return a ScoreboardOcrExtractor for the given request. See the
    contract doc's Usage section -- always use as a context manager:

        with extract_scoreboard(request) as extractor:
            result = extractor.run()
    """
    return ScoreboardOcrExtractor(request)


class _LastAcceptedReading:
    """The minimal rolling state used for cricket-rule validation
    (FR-012, FR-013, FR-014) -- only the most recent *accepted* reading's
    numeric fields, updated in place. A field left `None` on an otherwise
    accepted reading does not overwrite the tracked value for that field,
    so a partially-parsed reading can't corrupt future comparisons.

    Post-implementation fix (specs/011-club-broadcast-overlay-support/'s
    full-match real-video validation, PLATINUM CUP FINAL): `over_number`/
    `ball_in_over` only advance the baseline when `runs` and `wickets` are
    ALSO present in that same call. The compound-score parser always
    produces all four fields atomically (one regex match, one token) or
    none at all -- a reading with `over_number` set but `runs`/`wickets`
    both `None` can only have come from the generic parser's standalone
    `over.ball` token regex, which matches any "N.M"-shaped token in
    isolation and has no accompanying score context to corroborate it.
    Without this gate, one such spurious match (e.g. unrelated on-screen
    UI text coincidentally shaped like "5.0") silently advances
    `over_number` ahead of where the game actually is, and every
    genuinely correct subsequent reading gets rejected as an over-number
    decrease relative to that now-corrupted baseline -- the same failure
    mode `OVER_NUMBER_MAX` guards against for wildly-out-of-range values,
    but for small, individually-plausible ones that ceiling can't catch."""

    def __init__(self) -> None:
        self.runs: Optional[int] = None
        self.wickets: Optional[int] = None
        self.over_number: Optional[int] = None
        self.ball_in_over: Optional[int] = None

    def update(
        self,
        runs: Optional[int],
        wickets: Optional[int],
        over_number: Optional[int],
        ball_in_over: Optional[int],
    ) -> None:
        if runs is not None:
            self.runs = runs
        if wickets is not None:
            self.wickets = wickets
        if runs is not None and wickets is not None:
            if over_number is not None:
                self.over_number = over_number
            if ball_in_over is not None:
                self.ball_in_over = ball_in_over


class ScoreboardOcrExtractor:
    """Single-pass raw scoreboard timeline extractor over a validated
    video's frames, via Tesseract OCR against a configured ROI.

    Not constructed directly -- use `extract_scoreboard()`. Validation of
    the source and configuration (FR-001, FR-002, FR-017) happens lazily,
    when `.run()` is called, not at construction time -- so
    `extract_scoreboard()` itself never raises and never touches a frame.
    """

    def __init__(self, request: ScoreboardOcrRequest) -> None:
        self._request = request
        self._cancelled = False
        self._finished = False
        self._diagnostics_emitted = False
        self._tracker = DiagnosticsTracker()
        self._tracker_entered = False
        self._failure_reason: Optional[str] = None
        self._frames_processed = 0
        self._undetectable_count = 0
        self._low_confidence_count = 0
        self._skipped_count = 0
        self._validation_failure_counts: Dict[ValidationFailureReason, int] = {}
        # specs/011-club-broadcast-overlay-support/ research.md Decision 8:
        # per-strategy usage counts, folded into output_summary below --
        # no new field on the shared ExecutionDiagnostics dataclass.
        self._parser_strategy_counts: Dict[str, int] = {
            parser.name: 0 for parser in PARSERS
        }
        self._generic_broadcast_unparsed_count = 0
        self._samples: List[ScoreboardSample] = []
        self._evidence_list: List[OCREvidence] = []
        # Preprocessing-strategy warm-up/lock state (scoreboard_preprocessing.py):
        # None until a specific (non-generic) parser is confidently
        # identified, or PREPROCESSING_WARMUP_SAMPLE_LIMIT is reached --
        # after which every subsequent frame uses this locked-in strategy
        # directly, without re-checking.
        self._locked_strategy_name: Optional[str] = None
        self._warmup_samples_seen = 0

    def __enter__(self) -> "ScoreboardOcrExtractor":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self._finish()

    @property
    def evidence(self) -> List[OCREvidence]:
        """The full internal `OCREvidence` list, one entry per sample
        produced so far, in the same order as the result's samples
        (FR-029) -- readable at any point, primarily for testing/debugging."""
        return self._evidence_list

    def cancel(self) -> None:
        """Cooperative cancellation (FR-019): requests that `run()` stop
        processing further frames at its next opportunity."""
        self._cancelled = True

    def run(self) -> ScoreboardOcrResult:
        """Perform the full extraction pass and return a ScoreboardOcrResult."""
        self._tracker.__enter__()
        self._tracker_entered = True

        load_result = self._request.load_result
        if load_result.status != LoadStatus.SUCCESS or load_result.source is None:
            self._fail(
                ScoreboardOcrFailureReason.SOURCE_NOT_VALIDATED,
                "LoadResult is not a successful, validated video",
            )

        source = load_result.source
        self._validate_configuration()

        baseline = _LastAcceptedReading()
        previous_roi: Optional[np.ndarray] = None
        previous_sample: Optional[ScoreboardSample] = None
        previous_evidence: Optional[OCREvidence] = None
        samples: List[ScoreboardSample] = []
        evidence_list: List[OCREvidence] = []

        try:
            extraction_request = ExtractionRequest(
                load_result=load_result, mode=SamplingMode.FIXED_INTERVAL, rate_fps=SAMPLING_RATE_FPS
            )
            with extract_frames(extraction_request) as extractor:
                for frame_context in extractor:
                    if self._cancelled:
                        break
                    self._frames_processed += 1

                    roi = self._crop_roi(frame_context.frame, self._request.scoreboard_region)

                    if (
                        roi is not None
                        and previous_sample is not None
                        and previous_evidence is not None
                        and self._roi_unchanged(previous_roi, roi)
                    ):
                        sample = dataclasses.replace(
                            previous_sample, timestamp_seconds=frame_context.timestamp_seconds
                        )
                        evidence = previous_evidence
                        self._skipped_count += 1
                    else:
                        sample, evidence = self._process_frame(
                            roi, frame_context.timestamp_seconds, baseline
                        )
                        # Retain a copy, not a view: FrameContext.frame is
                        # only guaranteed valid through the current
                        # iteration step (Frame Extraction Service's own
                        # contract) -- a future FrameExtractor that reuses a
                        # decode buffer would otherwise silently alias this
                        # into next iteration's already-overwritten pixels.
                        previous_roi = roi.copy() if roi is not None else None

                    # Every produced sample (fresh or reused-via-skip) counts
                    # toward diagnostics identically -- a long stretch of
                    # skipped, reused samples must still be reflected in the
                    # undetectable/low-confidence/rule-failure counts, not
                    # just the one frame that was actually OCR'd (FR-021).
                    self._record_stats(sample, evidence)
                    samples.append(sample)
                    evidence_list.append(evidence)
                    previous_sample = sample
                    previous_evidence = evidence
        except ExtractionError as exc:
            self._samples = samples
            self._evidence_list = evidence_list
            # This module only ever requests FIXED_INTERVAL extraction with
            # no resume parameters, and only calls extract_frames() after
            # confirming load_result.status == SUCCESS itself -- so the
            # Frame Extraction Service's own SOURCE_NOT_VALIDATED and
            # RESUME_POINT_OUT_OF_RANGE reasons are not expected to reach
            # here. Rather than mislabel an unanticipated reason as the
            # specific-sounding-but-wrong SOURCE_UNAVAILABLE_MID_RUN, treat
            # it the same as any other unexpected mid-run problem (below).
            reason = _ExtractionFailureToScoreboardOcrFailure.get(
                exc.reason, ScoreboardOcrFailureReason.DECODE_FAILURE_MID_RUN
            )
            self._fail(reason, str(exc))
        except Exception as exc:  # noqa: BLE001 -- deliberately broad: any
            # unexpected failure while processing an otherwise-successfully-
            # decoded frame must still surface as this module's own typed
            # failure (FR-018), not an untyped crash.
            self._samples = samples
            self._evidence_list = evidence_list
            self._fail(ScoreboardOcrFailureReason.DECODE_FAILURE_MID_RUN, str(exc))

        self._samples = samples
        self._evidence_list = evidence_list
        self._finished = True
        self._finish()

        return ScoreboardOcrResult(
            source_video_id=source.file_hash,
            samples=tuple(self._samples),
            total_samples=len(self._samples),
        )

    # -- internal: validation ---------------------------------------------

    def _validate_configuration(self) -> None:
        request = self._request
        region = request.scoreboard_region

        # Validate shape/types before destructuring or calling math.isfinite
        # on them -- a malformed region (None, wrong length, non-numeric
        # elements) must fail with our own typed reason, not an untyped
        # TypeError/ValueError escaping before _fail() ever runs.
        is_numeric_quadruple = (
            isinstance(region, tuple)
            and len(region) == 4
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in region)
        )
        roi_in_bounds = False
        if is_numeric_quadruple:
            x, y, w, h = region
            values_finite = all(math.isfinite(v) for v in (x, y, w, h))
            roi_in_bounds = (
                values_finite
                and 0.0 <= x <= 1.0
                and 0.0 <= y <= 1.0
                and w > 0.0
                and h > 0.0
                and x + w <= 1.0 + 1e-9
                and y + h <= 1.0 + 1e-9
            )
        if not roi_in_bounds:
            self._fail(
                ScoreboardOcrFailureReason.INVALID_OCR_CONFIGURATION,
                f"scoreboard_region {region!r} must be a 4-tuple of finite numbers describing an in-bounds ROI",
            )

        upscale = request.preprocess_upscale
        if isinstance(upscale, bool) or not isinstance(upscale, int) or upscale < 1:
            self._fail(
                ScoreboardOcrFailureReason.INVALID_OCR_CONFIGURATION,
                f"preprocess_upscale {upscale} must be a positive integer",
            )

        if not isinstance(request.preprocess_grayscale, bool):
            self._fail(
                ScoreboardOcrFailureReason.INVALID_OCR_CONFIGURATION,
                f"preprocess_grayscale {request.preprocess_grayscale!r} must be a boolean",
            )
        if not isinstance(request.preprocess_threshold, bool):
            self._fail(
                ScoreboardOcrFailureReason.INVALID_OCR_CONFIGURATION,
                f"preprocess_threshold {request.preprocess_threshold!r} must be a boolean",
            )

        min_confidence = request.min_confidence
        if (
            isinstance(min_confidence, bool)
            or not isinstance(min_confidence, (int, float))
            or not (math.isfinite(min_confidence) and 0.0 <= min_confidence <= 1.0)
        ):
            self._fail(
                ScoreboardOcrFailureReason.INVALID_OCR_CONFIGURATION,
                f"min_confidence {min_confidence!r} must be a number within [0.0, 1.0]",
            )

    # -- internal: per-frame ROI extraction and preprocessing --------------

    def _crop_roi(self, frame: np.ndarray, region: Tuple[float, float, float, float]) -> Optional[np.ndarray]:
        x_frac, y_frac, w_frac, h_frac = region
        height, width = frame.shape[:2]
        x0 = int(x_frac * width)
        y0 = int(y_frac * height)
        x1 = min(width, x0 + int(w_frac * width))
        y1 = min(height, y0 + int(h_frac * height))
        if x1 <= x0 or y1 <= y0:
            return None
        return frame[y0:y1, x0:x1]

    def _preprocess_roi(self, roi: np.ndarray, strategy_name: Optional[str] = None) -> np.ndarray:
        """grayscale -> upscale -> strategy, each independently toggleable
        (research.md: this order preserves more edge detail for Tesseract
        than thresholding before enlarging). `strategy_name` selects the
        final-stage scoreboard_preprocessing.PreprocessingStrategy applied
        when `preprocess_threshold` is set -- defaults to
        `DEFAULT_STRATEGY_NAME` (Otsu, this platform's original behavior)
        when not given, so every existing direct caller of this method
        (tests, and any run before warm-up has locked in a format-specific
        choice) is unaffected."""
        request = self._request
        image = roi

        if request.preprocess_grayscale:
            image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image

        if request.preprocess_upscale > 1:
            image = cv2.resize(
                image,
                None,
                fx=float(request.preprocess_upscale),
                fy=float(request.preprocess_upscale),
                interpolation=cv2.INTER_CUBIC,
            )

        if request.preprocess_threshold:
            gray_for_threshold = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
            strategy = PREPROCESSING_STRATEGIES[strategy_name or DEFAULT_STRATEGY_NAME]
            image = strategy.apply(gray_for_threshold)

        return image

    def _roi_unchanged(self, previous_roi: Optional[np.ndarray], current_roi: np.ndarray) -> bool:
        if previous_roi is None or previous_roi.shape != current_roi.shape:
            return False
        return float(cv2.absdiff(previous_roi, current_roi).mean()) <= ROI_UNCHANGED_TOLERANCE

    # -- internal: OCR stage ------------------------------------------------

    def _run_ocr(self, preprocessed_image: np.ndarray) -> Tuple[str, float, List[Tuple[str, float]]]:
        """Runs pytesseract.image_to_data() once, producing both the raw
        text and per-token confidences (research.md) -- no second call
        needed for a plain image_to_string()."""
        data = pytesseract.image_to_data(preprocessed_image, config=_TESSERACT_CONFIG, output_type=Output.DICT)
        tokens: List[Tuple[str, float]] = []
        for text, conf in zip(data["text"], data["conf"]):
            stripped = text.strip()
            confidence = float(conf)
            if stripped and confidence >= 0:  # Tesseract reports -1 for non-text regions
                tokens.append((stripped, confidence))

        if not tokens:
            return "", 0.0, []

        raw_text = " ".join(text for text, _ in tokens)
        overall_confidence = sum(conf for _, conf in tokens) / len(tokens) / _TESSERACT_CONFIDENCE_SCALE
        return raw_text, overall_confidence, tokens

    # -- internal: structured-parsing stage ---------------------------------
    # This is a thin dispatcher over scoreboard_parsers.py's pluggable
    # `ScoreboardParser` architecture (`select_parser()` + `PARSERS`)
    # rather than owning any parsing logic itself -- kept as a same-named
    # method so every existing caller/test continues to work unmodified.

    def _parse_fields(self, tokens: List[Tuple[str, float]]) -> Tuple[Dict[str, Any], Dict[str, float]]:
        """Selects the applicable `ScoreboardParser` (see
        scoreboard_parsers.py) and delegates to it. See
        `GenericBroadcastParser` for the original spec's clean-token path,
        `ClubBroadcastParser` for the club-broadcast-overlay amendment's
        compound-score path, and `SeparateTokenBroadcastParser` for the
        third, separate-token format."""
        selected_parser = select_parser(tokens)
        parsed_fields, field_confidences = selected_parser.parse(tokens)
        parsed_fields["parser_strategy"] = selected_parser.name
        return parsed_fields, field_confidences

    # -- internal: cricket-rule validation stage ----------------------------

    def _validate_reading(
        self, parsed_fields: Dict[str, Any], baseline: _LastAcceptedReading
    ) -> Tuple[bool, Optional[ValidationFailureReason]]:
        """FR-012-FR-016, FR-030, FR-031 -- amended per
        specs/011-club-broadcast-overlay-support/'s real-video validation
        finding (quickstart.md Steps 3/5 against First8Overs.mp4): FR-030's
        original design treated a missing `batter` as an unconditional,
        whole-reading structural-parse failure. On real footage where the
        best-effort name heuristic fails more often than the score fields
        themselves do, that blanket gate discarded otherwise-good score
        readings wholesale, opening multi-ball gaps in the accepted-reading
        baseline -- which in turn made Event Detection's single-ball-advance
        requirement silently miss FOUR/SIX events spanning those gaps.

        `batter` is no longer a gate on the *score* fields: a reading with a
        fully valid, monotonic score is now accepted (and updates the
        baseline) regardless of whether a name could be located. A reading
        with *neither* a locatable name *nor* any score field at all --
        i.e., nothing usable was extracted -- still fails as
        `PLAYER_PARSE_FAILED` (FR-030's "nothing usable" case, narrowed
        rather than removed). `parsed_fields["batter"]`/`ScoreboardSample.batter`
        remain `None` exactly as before when unreadable; a caller that cares
        about name presence must still check that field directly rather
        than inferring it from `parse_confidence`.

        Parser-agnostic by construction (specs/011-.../FR-009): this method
        only ever reads keys out of `parsed_fields`, never which
        `ScoreboardParser` produced them -- the same validation logic
        applies identically regardless of which registered parser
        (scoreboard_parsers.py) produced the reading."""
        runs = parsed_fields.get("runs")
        wickets = parsed_fields.get("wickets")
        over_number = parsed_fields.get("over_number")
        ball_in_over = parsed_fields.get("ball_in_over")

        has_any_score_field = any(v is not None for v in (runs, wickets, over_number, ball_in_over))
        if parsed_fields.get("batter") is None and not has_any_score_field:
            return False, ValidationFailureReason.PLAYER_PARSE_FAILED

        if ball_in_over is not None and not (0 <= ball_in_over <= BALL_IN_OVER_MAX):
            return False, ValidationFailureReason.INVALID_BALL_NUMBER

        if wickets is not None and not (0 <= wickets <= WICKETS_MAX):
            return False, ValidationFailureReason.WICKETS_DECREASED

        if over_number is not None and not (0 <= over_number <= OVER_NUMBER_MAX):
            return False, ValidationFailureReason.INVALID_OVER_SEQUENCE

        # Post-implementation fix (specs/011-.../real-video validation,
        # PLATINUM CUP FINAL): a single-digit OCR misread within an
        # otherwise atomic compound-score match (e.g. real "31-3/6.1(20)"
        # misread as "311-3/6.1(20)") is neither a decrease nor an
        # out-of-range value, so nothing above catches it. A reading
        # claiming the exact same ball (over_number AND ball_in_over both
        # unchanged from baseline) is describing the same historical
        # instant in the match -- its runs value must match what was
        # already recorded there; a magnitude-based cap was tried first
        # and rejected (it also blocked a legitimate large catch-up jump
        # elsewhere, when the innings-transition heuristic below
        # occasionally misfires on a garbled reading and temporarily
        # resets the baseline low -- FR-014's own documented trade-off).
        # This same-ball check can never conflict with that recovery,
        # since a genuine catch-up jump always comes with the over/ball
        # having also advanced.
        if (
            runs is not None
            and baseline.runs is not None
            and over_number is not None
            and baseline.over_number is not None
            and over_number == baseline.over_number
            and ball_in_over is not None
            and baseline.ball_in_over is not None
            and ball_in_over == baseline.ball_in_over
            and runs != baseline.runs
        ):
            return False, ValidationFailureReason.RUNS_DECREASED

        # No outer "has a prior reading at all" gate is needed here: every
        # comparison below already guards on `baseline.<field> is not None`
        # individually, which is `False` for every field at cold start (and
        # for any field an accepted-but-partial reading never populated) --
        # the same effective skip as a dedicated gate, without a second,
        # redundant mechanism to keep in sync (FR-016).
        innings_transition = (
            runs is not None
            and wickets is not None
            and baseline.runs is not None
            and baseline.wickets is not None
            and runs < baseline.runs
            and wickets < baseline.wickets
        )
        if not innings_transition:
            if runs is not None and baseline.runs is not None and runs < baseline.runs:
                return False, ValidationFailureReason.RUNS_DECREASED
            if wickets is not None and baseline.wickets is not None and wickets < baseline.wickets:
                return False, ValidationFailureReason.WICKETS_DECREASED
            if (
                over_number is not None
                and baseline.over_number is not None
                and over_number < baseline.over_number
            ):
                return False, ValidationFailureReason.INVALID_OVER_SEQUENCE
            # Within the *same* over, ball_in_over must not go backwards
            # either (e.g. baseline "12.5" followed by a noisy "12.3") --
            # an over_number-only check misses this, since it only compares
            # across an over boundary, never within one (PR review finding).
            if (
                over_number is not None
                and baseline.over_number is not None
                and over_number == baseline.over_number
                and ball_in_over is not None
                and baseline.ball_in_over is not None
                and ball_in_over < baseline.ball_in_over
            ):
                return False, ValidationFailureReason.INVALID_OVER_SEQUENCE

        return True, None

    # -- internal: per-frame orchestration -----------------------------------

    def _advance_preprocessing_warmup(self, parser_name: Optional[str]) -> None:
        """scoreboard_preprocessing.py's warm-up-then-lock selection: a
        no-op once `self._locked_strategy_name` is already set. Otherwise,
        locks in `parser_name`'s declared preferred strategy the moment a
        *specific* (non-generic) parser is identified -- a single
        confident match is enough, no run of consecutive agreement
        required, since a specific parser's `matches()` signature has been
        observed to be a strong, non-coincidental signal on its own
        (scoreboard_parsers.py's own mutual-exclusivity contract, verified
        in tests/contract/test_scoreboard_parsers_contract.py). If
        `PREPROCESSING_WARMUP_SAMPLE_LIMIT` samples pass without ever
        seeing a specific parser (e.g. an unrecognized fourth format, or a
        run of undetectable frames), locks to `DEFAULT_STRATEGY_NAME`
        (Otsu) permanently -- the same behavior this platform already had
        before this amendment, for the cases this amendment doesn't
        change anything about."""
        if self._locked_strategy_name is not None:
            return

        if parser_name is not None and parser_name != GenericBroadcastParser.name:
            self._locked_strategy_name = PARSER_PREFERRED_STRATEGY.get(parser_name, DEFAULT_STRATEGY_NAME)
            return

        self._warmup_samples_seen += 1
        if self._warmup_samples_seen >= PREPROCESSING_WARMUP_SAMPLE_LIMIT:
            self._locked_strategy_name = DEFAULT_STRATEGY_NAME

    def _ocr_and_parse(
        self, roi: np.ndarray, strategy_name: str
    ) -> Tuple[np.ndarray, str, float, List[Tuple[str, float]], Dict[str, Any], Dict[str, float]]:
        """Preprocess `roi` with `strategy_name` and run it through OCR +
        field parsing, with no side effects (no baseline mutation, no
        warm-up/diagnostics bookkeeping) -- so warm-up can trial multiple
        strategies against the same frame and only commit to one
        afterward, via `_process_frame` below."""
        preprocessed = self._preprocess_roi(roi, strategy_name)
        raw_text, ocr_confidence, tokens = self._run_ocr(preprocessed)
        if not tokens:
            return preprocessed, raw_text, ocr_confidence, tokens, {}, {}
        parsed_fields, field_confidences = self._parse_fields(tokens)
        return preprocessed, raw_text, ocr_confidence, tokens, parsed_fields, field_confidences

    def _process_frame(
        self,
        roi: Optional[np.ndarray],
        timestamp_seconds: float,
        baseline: _LastAcceptedReading,
    ) -> Tuple[ScoreboardSample, OCREvidence]:
        if roi is None:
            return self._undetectable_sample(timestamp_seconds), self._undetectable_evidence()

        strategy_name = self._locked_strategy_name or DEFAULT_STRATEGY_NAME
        preprocessed, raw_text, ocr_confidence, tokens, parsed_fields, field_confidences = self._ocr_and_parse(
            roi, strategy_name
        )
        parser_name = parsed_fields.get("parser_strategy") if tokens else None

        parser_found_no_score_data = (
            parser_name == GenericBroadcastParser.name
            and parsed_fields.get("runs") is None
            and parsed_fields.get("wickets") is None
        )
        if self._locked_strategy_name is None and (parser_name is None or parser_found_no_score_data):
            # Still warming up, and this strategy produced nothing usable
            # on this frame: either no tokens at all, or tokens that fell
            # through every specific parser to the universal
            # GenericBroadcastParser fallback (which always "matches") with
            # no score data extracted either -- as opposed to a frame that
            # genuinely fell through to, and was correctly read by, that
            # same fallback (e.g. the "original" format, which also stays
            # on Otsu; a runs/wickets-bearing generic_broadcast reading is
            # never subject to this trial). Otsu's own failure mode on a
            # format it can't binarize correctly is for that format's
            # frames to look undetectable or generic-with-no-score-data in
            # the first place (module docstring, scoreboard_preprocessing.py)
            # -- so judging warm-up solely by Otsu's result never gives such
            # a format a chance to be recognized, and a run of unlucky early
            # frames permanently locks Otsu for the whole run even though a
            # later frame preprocessed with the right strategy would have
            # matched (review finding on this PR). Before spending this
            # frame's warm-up sample, trial the other registered strategies
            # against the *same* frame -- bounded to the warm-up window, not
            # every frame, so this doesn't reintroduce the per-frame
            # multi-strategy cost the module docstring explicitly rules out
            # for steady state.
            for alt_name in PREPROCESSING_STRATEGIES:
                if alt_name == strategy_name:
                    continue
                (
                    alt_preprocessed,
                    alt_raw_text,
                    alt_confidence,
                    alt_tokens,
                    alt_parsed_fields,
                    alt_field_confidences,
                ) = self._ocr_and_parse(roi, alt_name)
                alt_parser_name = alt_parsed_fields.get("parser_strategy") if alt_tokens else None
                if alt_parser_name is not None and alt_parser_name != GenericBroadcastParser.name:
                    preprocessed, raw_text, ocr_confidence, tokens, parsed_fields, field_confidences = (
                        alt_preprocessed,
                        alt_raw_text,
                        alt_confidence,
                        alt_tokens,
                        alt_parsed_fields,
                        alt_field_confidences,
                    )
                    parser_name = alt_parser_name
                    break

        if not tokens:
            self._advance_preprocessing_warmup(parser_name=None)
            sample = self._undetectable_sample(timestamp_seconds, raw_text=raw_text)
            evidence = OCREvidence(
                raw_text=raw_text, preprocessed_image_ref=preprocessed.copy(), ocr_confidence=0.0
            )
            return sample, evidence

        self._advance_preprocessing_warmup(parser_name=parser_name)
        validation_passed, failure_reason = self._validate_reading(parsed_fields, baseline)

        if validation_passed:
            baseline.update(
                parsed_fields.get("runs"),
                parsed_fields.get("wickets"),
                parsed_fields.get("over_number"),
                parsed_fields.get("ball_in_over"),
            )
            parse_confidence = 1.0
        else:
            parse_confidence = 0.0

        evidence = OCREvidence(
            raw_text=raw_text,
            preprocessed_image_ref=preprocessed.copy(),
            ocr_confidence=ocr_confidence,
            field_confidences=field_confidences,
            parsed_fields=parsed_fields,
            validation_passed=validation_passed,
            validation_failure_reason=failure_reason,
        )
        sample = ScoreboardSample(
            timestamp_seconds=timestamp_seconds,
            runs=parsed_fields.get("runs"),
            wickets=parsed_fields.get("wickets"),
            over_number=parsed_fields.get("over_number"),
            ball_in_over=parsed_fields.get("ball_in_over"),
            batter=parsed_fields.get("batter"),
            non_striker=parsed_fields.get("non_striker"),
            bowler=parsed_fields.get("bowler"),
            run_rate=parsed_fields.get("run_rate"),
            raw_text=raw_text,
            ocr_confidence=ocr_confidence,
            parse_confidence=parse_confidence,
        )
        return sample, evidence

    def _undetectable_sample(self, timestamp_seconds: float, raw_text: str = "") -> ScoreboardSample:
        return ScoreboardSample(
            timestamp_seconds=timestamp_seconds,
            runs=None,
            wickets=None,
            over_number=None,
            ball_in_over=None,
            batter=None,
            non_striker=None,
            bowler=None,
            run_rate=None,
            raw_text=raw_text,
            ocr_confidence=0.0,
            parse_confidence=0.0,
        )

    def _undetectable_evidence(self) -> OCREvidence:
        return OCREvidence(raw_text="", preprocessed_image_ref=None, ocr_confidence=0.0)

    def _record_stats(self, sample: ScoreboardSample, evidence: OCREvidence) -> None:
        """Update the diagnostics counters for one produced sample --
        called once per sample regardless of whether it was freshly OCR'd
        or served via the ROI-unchanged skip, so a long stretch of skipped,
        reused samples is still fully reflected in the undetectable/
        low-confidence/rule-failure counts (FR-021), not just the one frame
        that was actually processed."""
        if evidence.validation_passed is None:
            self._undetectable_count += 1
            return

        # specs/011-.../research.md Decision 8: parser-strategy usage, and
        # how many generic_broadcast-routed readings still ended in
        # PLAYER_PARSE_FAILED (Decision 7's "unknown layout" case, tracked
        # without a new failure-taxonomy value).
        parser_strategy = evidence.parsed_fields.get("parser_strategy")
        if parser_strategy in self._parser_strategy_counts:
            self._parser_strategy_counts[parser_strategy] += 1
            if (
                parser_strategy == GenericBroadcastParser.name
                and not evidence.validation_passed
                and evidence.validation_failure_reason == ValidationFailureReason.PLAYER_PARSE_FAILED
            ):
                self._generic_broadcast_unparsed_count += 1

        if sample.ocr_confidence < self._request.min_confidence:
            self._low_confidence_count += 1
        if not evidence.validation_passed and evidence.validation_failure_reason is not None:
            self._validation_failure_counts[evidence.validation_failure_reason] = (
                self._validation_failure_counts.get(evidence.validation_failure_reason, 0) + 1
            )

    # -- internal: failure/diagnostics ---------------------------------------

    def _fail(self, reason: ScoreboardOcrFailureReason, detail: str):
        self._failure_reason = reason.value
        self._finished = True
        self._finish()
        raise ScoreboardOcrError(reason, detail)

    def _finish(self) -> None:
        if self._tracker_entered and not self._diagnostics_emitted:
            self._tracker.__exit__(None, None, None)
            diagnostics = self._build_diagnostics()
            emit_diagnostics(diagnostics)
            self._diagnostics_emitted = True

    def _build_diagnostics(self) -> ExecutionDiagnostics:
        """Build the one ExecutionDiagnostics record for this run (FR-021)."""
        request = self._request
        source = request.load_result.source
        source_id = source.file_hash if source is not None else None
        # Which ScoreboardParser implementations were even available this
        # run, and what layout each one claims to recognize -- combined
        # with output_summary's `parser_strategy` usage counts below, this
        # answers "which parser was selected, and why" without needing to
        # read scoreboard_parsers.py's source.
        parser_registry = "; ".join(f"{parser.name}: {parser.description}" for parser in PARSERS)
        input_summary = (
            f"source_video_id={source_id} scoreboard_region={request.scoreboard_region} "
            f"preprocess=(grayscale={request.preprocess_grayscale},"
            f"threshold={request.preprocess_threshold},upscale={request.preprocess_upscale}) "
            f"min_confidence={request.min_confidence} "
            f"parser_registry=({parser_registry})"
        )

        ocr_confidences = [s.ocr_confidence for s in self._samples]
        parse_confidences = [s.parse_confidence for s in self._samples]
        average_ocr_confidence = sum(ocr_confidences) / len(ocr_confidences) if ocr_confidences else 0.0
        average_parse_confidence = sum(parse_confidences) / len(parse_confidences) if parse_confidences else 0.0
        parse_failure_total = sum(self._validation_failure_counts.values())
        reason_breakdown = ", ".join(
            f"{reason.value}={count}" for reason, count in sorted(self._validation_failure_counts.items(), key=lambda kv: kv[0].value)
        )
        parser_strategy_breakdown = ", ".join(
            f"{name}={count}" for name, count in sorted(self._parser_strategy_counts.items())
        )

        output_summary = (
            f"frames_processed={self._frames_processed} "
            f"undetectable_region_count={self._undetectable_count} "
            f"average_ocr_confidence={average_ocr_confidence} "
            f"low_ocr_confidence_count={self._low_confidence_count} "
            f"average_parse_confidence={average_parse_confidence} "
            f"parse_confidence_zero_count={parse_failure_total} "
            f"validation_failure_breakdown=({reason_breakdown}) "
            f"roi_unchanged_skip_count={self._skipped_count} "
            f"parser_strategy=({parser_strategy_breakdown}) "
            f"generic_broadcast_unparsed_count={self._generic_broadcast_unparsed_count} "
            f"preprocessing_strategy_locked={self._locked_strategy_name or 'none'} "
            f"preprocessing_warmup_samples={self._warmup_samples_seen} "
            f"configuration_version=1"
        )
        return self._tracker.build(
            module_name=MODULE_NAME,
            input_summary=input_summary,
            output_summary=output_summary,
            warnings=[],
            failure_reason=self._failure_reason,
        )
