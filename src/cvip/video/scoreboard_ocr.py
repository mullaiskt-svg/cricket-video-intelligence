"""Scoreboard OCR: extract_scoreboard() and ScoreboardOcrExtractor.

See specs/005-scoreboard-ocr/contracts/scoreboard_ocr_contract.md
for the full contract this module implements.
"""

from __future__ import annotations

import dataclasses
import math
import re
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

# Valid ranges for the two count-like fields (spec.md Assumptions).
WICKETS_MAX = 10
BALL_IN_OVER_MAX = 6

# Tesseract's own confidence scale is 0-100; this platform's confidence
# fields are always 0.0-1.0.
_TESSERACT_CONFIDENCE_SCALE = 100.0

# "Assume a single uniform block of text" -- a scoreboard graphic is a small,
# dense text block, not a full page (research.md-style reasoned default).
_TESSERACT_CONFIG = "--psm 6"

_RUNS_WICKETS_RE = re.compile(r"^(\d+)/(\d+)$")
_OVER_BALL_RE = re.compile(r"^(\d+)\.(\d+)$")
_BOWLER_LABEL_RE = re.compile(r"^(?:B|BOWLER)[:.]?$", re.IGNORECASE)
_NAME_RE = re.compile(r"^[A-Za-z]+\*?$")

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
    so a partially-parsed reading can't corrupt future comparisons."""

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
        self._samples: List[ScoreboardSample] = []
        self._evidence_list: List[OCREvidence] = []

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
        x, y, w, h = request.scoreboard_region
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
                f"scoreboard_region {request.scoreboard_region} is out of bounds",
            )

        upscale = request.preprocess_upscale
        if isinstance(upscale, bool) or not isinstance(upscale, int) or upscale < 1:
            self._fail(
                ScoreboardOcrFailureReason.INVALID_OCR_CONFIGURATION,
                f"preprocess_upscale {upscale} must be a positive integer",
            )

        min_confidence = request.min_confidence
        if not (math.isfinite(min_confidence) and 0.0 <= min_confidence <= 1.0):
            self._fail(
                ScoreboardOcrFailureReason.INVALID_OCR_CONFIGURATION,
                f"min_confidence {min_confidence} must be within [0.0, 1.0]",
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

    def _preprocess_roi(self, roi: np.ndarray) -> np.ndarray:
        """grayscale -> upscale -> threshold, each independently toggleable
        (research.md: this order preserves more edge detail for Tesseract
        than thresholding before enlarging)."""
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
            _, image = cv2.threshold(gray_for_threshold, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

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

    def _parse_fields(self, tokens: List[Tuple[str, float]]) -> Tuple[Dict[str, Any], Dict[str, float]]:
        """Locates and parses runs, wickets, over_number/ball_in_over,
        batter, non_striker, bowler, and run_rate from OCR tokens (FR-007),
        attributing each field's confidence to the token(s) it came from
        (research.md) -- a field with no attributable token is simply
        absent, never fabricated."""
        parsed: Dict[str, Any] = {}
        confidences: Dict[str, float] = {}
        consumed: set = set()
        over_ball_found = False

        for i, (text, conf) in enumerate(tokens):
            match = _RUNS_WICKETS_RE.match(text)
            if match and "runs" not in parsed:
                parsed["runs"] = int(match.group(1))
                parsed["wickets"] = int(match.group(2))
                confidences["runs"] = conf / _TESSERACT_CONFIDENCE_SCALE
                confidences["wickets"] = conf / _TESSERACT_CONFIDENCE_SCALE
                consumed.add(i)
                continue

            match = _OVER_BALL_RE.match(text)
            if match:
                if not over_ball_found:
                    parsed["over_number"] = int(match.group(1))
                    parsed["ball_in_over"] = int(match.group(2))
                    confidences["over_number"] = conf / _TESSERACT_CONFIDENCE_SCALE
                    confidences["ball_in_over"] = conf / _TESSERACT_CONFIDENCE_SCALE
                    over_ball_found = True
                elif "run_rate" not in parsed:
                    parsed["run_rate"] = float(text)
                    confidences["run_rate"] = conf / _TESSERACT_CONFIDENCE_SCALE
                consumed.add(i)
                continue

            if _BOWLER_LABEL_RE.match(text) and i + 1 < len(tokens):
                next_text, next_conf = tokens[i + 1]
                if _NAME_RE.match(next_text):
                    parsed["bowler"] = next_text.rstrip("*")
                    confidences["bowler"] = next_conf / _TESSERACT_CONFIDENCE_SCALE
                    consumed.add(i)
                    consumed.add(i + 1)
                continue

        for i, (text, conf) in enumerate(tokens):
            if i in consumed or not _NAME_RE.match(text):
                continue
            if text.endswith("*") and "batter" not in parsed:
                parsed["batter"] = text.rstrip("*")
                confidences["batter"] = conf / _TESSERACT_CONFIDENCE_SCALE
            elif not text.endswith("*") and "non_striker" not in parsed:
                parsed["non_striker"] = text
                confidences["non_striker"] = conf / _TESSERACT_CONFIDENCE_SCALE

        return parsed, confidences

    # -- internal: cricket-rule validation stage ----------------------------

    def _validate_reading(
        self, parsed_fields: Dict[str, Any], baseline: _LastAcceptedReading
    ) -> Tuple[bool, Optional[ValidationFailureReason]]:
        """FR-012-FR-016, FR-030, FR-031. `batter` is the one field whose
        absence is treated as a structural parse failure (FR-030's own
        example); the numeric fields are individually optional but
        rule-checked when present."""
        if parsed_fields.get("batter") is None:
            return False, ValidationFailureReason.PLAYER_PARSE_FAILED

        runs = parsed_fields.get("runs")
        wickets = parsed_fields.get("wickets")
        over_number = parsed_fields.get("over_number")
        ball_in_over = parsed_fields.get("ball_in_over")

        if ball_in_over is not None and not (0 <= ball_in_over <= BALL_IN_OVER_MAX):
            return False, ValidationFailureReason.INVALID_BALL_NUMBER

        if wickets is not None and not (0 <= wickets <= WICKETS_MAX):
            return False, ValidationFailureReason.WICKETS_DECREASED

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

        return True, None

    # -- internal: per-frame orchestration -----------------------------------

    def _process_frame(
        self,
        roi: Optional[np.ndarray],
        timestamp_seconds: float,
        baseline: _LastAcceptedReading,
    ) -> Tuple[ScoreboardSample, OCREvidence]:
        if roi is None:
            return self._undetectable_sample(timestamp_seconds), self._undetectable_evidence()

        preprocessed = self._preprocess_roi(roi)
        raw_text, ocr_confidence, tokens = self._run_ocr(preprocessed)

        if not tokens:
            sample = self._undetectable_sample(timestamp_seconds, raw_text=raw_text)
            evidence = OCREvidence(
                raw_text=raw_text, preprocessed_image_ref=preprocessed.copy(), ocr_confidence=0.0
            )
            return sample, evidence

        parsed_fields, field_confidences = self._parse_fields(tokens)
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
        input_summary = (
            f"source_video_id={source_id} scoreboard_region={request.scoreboard_region} "
            f"preprocess=(grayscale={request.preprocess_grayscale},"
            f"threshold={request.preprocess_threshold},upscale={request.preprocess_upscale}) "
            f"min_confidence={request.min_confidence}"
        )

        ocr_confidences = [s.ocr_confidence for s in self._samples]
        parse_confidences = [s.parse_confidence for s in self._samples]
        average_ocr_confidence = sum(ocr_confidences) / len(ocr_confidences) if ocr_confidences else 0.0
        average_parse_confidence = sum(parse_confidences) / len(parse_confidences) if parse_confidences else 0.0
        parse_failure_total = sum(self._validation_failure_counts.values())
        reason_breakdown = ", ".join(
            f"{reason.value}={count}" for reason, count in sorted(self._validation_failure_counts.items(), key=lambda kv: kv[0].value)
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
            f"configuration_version=1"
        )
        return self._tracker.build(
            module_name=MODULE_NAME,
            input_summary=input_summary,
            output_summary=output_summary,
            warnings=[],
            failure_reason=self._failure_reason,
        )
