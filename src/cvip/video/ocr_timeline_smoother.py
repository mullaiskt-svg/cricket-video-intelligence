"""OCR Timeline Smoother: smooth_timeline() and OCRTimelineSmootherRunner.

See specs/006-ocr-timeline-smoother/contracts/ocr_timeline_smoother_contract.md
for the full contract this module implements.

Unlike every other module in this pipeline, this feature never touches a
video file or a video frame -- its only input is Scoreboard OCR's own
ordered `ScoreboardOcrResult` (spec.md Assumptions). It runs a two-pass
algorithm (research.md Decision 3): a flag pass that marks each usable
sample as an isolated outlier or not (Decisions 1-2, 4), followed by a
sequential hold-forward fill pass that resolves every unusable-flagged or
outlier-flagged sample against the most recently established known-good
reading.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from cvip.common.diagnostics import DiagnosticsTracker, ExecutionDiagnostics, emit_diagnostics
from cvip.video.ocr_timeline_smoother_errors import (
    OCRTimelineSmootherError,
    OCRTimelineSmootherFailureReason,
)
from cvip.video.ocr_timeline_smoother_models import (
    CleanedScoreboardSample,
    OCRTimelineSmootherRequest,
    OCRTimelineSmootherResult,
    SmoothingEvidence,
    SmoothingResolution,
)
from cvip.video.scoreboard_ocr_models import ScoreboardSample

MODULE_NAME = "video.ocr_timeline_smoother"

# The four fields Event Detection will actually diff to derive scoring
# events (research.md Decision 2) -- the only fields compared for outlier
# consensus. batter/non_striker/bowler/run_rate are deliberately excluded:
# they are independently noisy OCR targets unrelated to event derivation,
# and folding them in would make the feature more likely to flag a sample as
# an "outlier" purely because of an unrelated player-name misread.
_CORE_TUPLE_FIELDS = ("runs", "wickets", "over_number", "ball_in_over")

# The 8 fields carried onto CleanedScoreboardSample (everything except
# timestamp_seconds, which is always taken from the sample's own position).
_CLEANED_FIELDS = _CORE_TUPLE_FIELDS + ("batter", "non_striker", "bowler", "run_rate")


def smooth_timeline(request: OCRTimelineSmootherRequest) -> "OCRTimelineSmootherRunner":
    """Return an OCRTimelineSmootherRunner for the given request. See the
    contract doc's Usage section -- always use as a context manager:

        with smooth_timeline(request) as runner:
            result = runner.run()
    """
    return OCRTimelineSmootherRunner(request)


class OCRTimelineSmootherRunner:
    """Single-pass-per-stage (two total) cleaner over Scoreboard OCR's raw
    sample sequence.

    Not constructed directly -- use `smooth_timeline()`. Validation of the
    input and configuration (FR-012, FR-013) happens lazily, when `.run()`
    is called, not at construction time.
    """

    def __init__(self, request: OCRTimelineSmootherRequest) -> None:
        self._request = request
        self._cancelled = False
        self._finished = False
        self._diagnostics_emitted = False
        self._tracker = DiagnosticsTracker()
        self._tracker_entered = False
        self._failure_reason: Optional[str] = None
        self._samples_processed = 0
        self._held_forward_unusable_count = 0
        self._held_forward_outlier_count = 0
        self._no_reliable_value_yet_count = 0
        self._samples: List[CleanedScoreboardSample] = []
        self._evidence_list: List[SmoothingEvidence] = []

    def __enter__(self) -> "OCRTimelineSmootherRunner":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self._finish()

    @property
    def evidence(self) -> List[SmoothingEvidence]:
        """The full internal `SmoothingEvidence` list, one entry per sample
        produced so far, in the same order as the result's samples
        (FR-008) -- readable at any point, primarily for testing/debugging."""
        return self._evidence_list

    def cancel(self) -> None:
        """Cooperative cancellation (FR-015): requests that `run()` stop
        processing further samples at its next opportunity."""
        self._cancelled = True

    def run(self) -> OCRTimelineSmootherResult:
        """Perform the full two-pass smoothing operation and return an
        OCRTimelineSmootherResult."""
        self._tracker.__enter__()
        self._tracker_entered = True

        self._validate_input()
        self._validate_configuration()

        request = self._request
        raw_samples = request.scoreboard_ocr_result.samples
        outlier_window = request.outlier_window

        is_unusable = [self._is_unusable(sample) for sample in raw_samples]
        is_outlier = self._flag_outliers(raw_samples, is_unusable, outlier_window)

        known_good: Optional[Dict[str, Any]] = None
        samples: List[CleanedScoreboardSample] = []
        evidence_list: List[SmoothingEvidence] = []

        for index, sample in enumerate(raw_samples):
            if self._cancelled:
                break
            self._samples_processed += 1

            if is_unusable[index]:
                resolution = SmoothingResolution.HELD_FORWARD_UNUSABLE
                self._held_forward_unusable_count += 1
                if known_good is None:
                    self._no_reliable_value_yet_count += 1
                fields = known_good
            elif is_outlier[index]:
                resolution = SmoothingResolution.HELD_FORWARD_OUTLIER
                self._held_forward_outlier_count += 1
                fields = known_good
            else:
                resolution = SmoothingResolution.PASSED_THROUGH
                fields = self._sample_fields(sample)
                # Only update known_good if all core scoring fields are present --
                # partial OCR readings (e.g., has batter but runs/over/ball are None)
                # should not seed known_good, to avoid mid-timeline nulls in output.
                if all(fields.get(f) is not None for f in _CORE_TUPLE_FIELDS):
                    known_good = fields

            samples.append(self._build_cleaned_sample(sample.timestamp_seconds, fields))
            evidence_list.append(SmoothingEvidence(resolution=resolution, original_sample=sample))

        self._samples = samples
        self._evidence_list = evidence_list
        self._finished = True
        self._finish()

        return OCRTimelineSmootherResult(
            source_video_id=request.scoreboard_ocr_result.source_video_id,
            samples=tuple(self._samples),
            total_samples=len(self._samples),
        )

    # -- internal: validation ---------------------------------------------

    def _validate_input(self) -> None:
        result = self._request.scoreboard_ocr_result
        samples = getattr(result, "samples", None) if result is not None else None
        if result is None or samples is None:
            self._fail(
                OCRTimelineSmootherFailureReason.INVALID_INPUT,
                "scoreboard_ocr_result is missing or does not expose a samples sequence",
            )

        previous_timestamp: Optional[float] = None
        for sample in samples:
            if previous_timestamp is not None and sample.timestamp_seconds <= previous_timestamp:
                self._fail(
                    OCRTimelineSmootherFailureReason.INVALID_INPUT,
                    "scoreboard_ocr_result.samples is not a strictly ascending-timestamp-ordered sequence",
                )
            previous_timestamp = sample.timestamp_seconds

    def _validate_configuration(self) -> None:
        outlier_window = self._request.outlier_window
        if isinstance(outlier_window, bool) or not isinstance(outlier_window, int) or outlier_window < 1:
            self._fail(
                OCRTimelineSmootherFailureReason.INVALID_SMOOTHING_CONFIGURATION,
                f"outlier_window {outlier_window!r} must be a positive integer",
            )

    # -- internal: usable/outlier classification (research.md Decisions 1, 2, 4) ---

    def _is_unusable(self, sample: ScoreboardSample) -> bool:
        return sample.ocr_confidence == 0.0 or sample.parse_confidence == 0.0

    def _core_tuple(self, sample: ScoreboardSample) -> Tuple[Any, ...]:
        return tuple(getattr(sample, field_name) for field_name in _CORE_TUPLE_FIELDS)

    def _flag_outliers(
        self,
        raw_samples: Tuple[ScoreboardSample, ...],
        is_unusable: List[bool],
        outlier_window: int,
    ) -> List[bool]:
        """The flag pass (research.md Decision 3): for each usable sample
        with `outlier_window` usable neighbors available on both sides
        (skipping over unusable-flagged samples), flag it as an isolated
        outlier when both neighbor windows mutually agree on the core
        scoring tuple while the sample itself disagrees. Never depends on
        another sample's own outlier flag -- purely a function of the raw
        usable/unusable partition, avoiding any bootstrapping ambiguity."""
        usable_indices = [i for i, unusable in enumerate(is_unusable) if not unusable]
        is_outlier = [False] * len(raw_samples)

        for position, index in enumerate(usable_indices):
            if position < outlier_window or position + outlier_window >= len(usable_indices):
                continue  # not enough usable neighbors on one side (research.md Decision 1)

            before_indices = usable_indices[position - outlier_window : position]
            after_indices = usable_indices[position + 1 : position + 1 + outlier_window]
            window_tuples = [self._core_tuple(raw_samples[i]) for i in before_indices + after_indices]
            consensus = window_tuples[0]
            if all(t == consensus for t in window_tuples) and self._core_tuple(raw_samples[index]) != consensus:
                is_outlier[index] = True

        return is_outlier

    # -- internal: fill pass helpers ----------------------------------------

    def _sample_fields(self, sample: ScoreboardSample) -> Dict[str, Any]:
        return {field_name: getattr(sample, field_name) for field_name in _CLEANED_FIELDS}

    def _build_cleaned_sample(
        self, timestamp_seconds: float, fields: Optional[Dict[str, Any]]
    ) -> CleanedScoreboardSample:
        if fields is None:
            fields = {field_name: None for field_name in _CLEANED_FIELDS}
        return CleanedScoreboardSample(timestamp_seconds=timestamp_seconds, **fields)

    # -- internal: failure/diagnostics ---------------------------------------

    def _fail(self, reason: OCRTimelineSmootherFailureReason, detail: str):
        self._failure_reason = reason.value
        self._finished = True
        self._finish()
        raise OCRTimelineSmootherError(reason, detail)

    def _finish(self) -> None:
        if self._tracker_entered and not self._diagnostics_emitted:
            self._tracker.__exit__(None, None, None)
            diagnostics = self._build_diagnostics()
            emit_diagnostics(diagnostics)
            self._diagnostics_emitted = True

    def _build_diagnostics(self) -> ExecutionDiagnostics:
        """Build the one ExecutionDiagnostics record for this run (FR-017)."""
        request = self._request
        result = request.scoreboard_ocr_result
        source_id = getattr(result, "source_video_id", None) if result is not None else None
        total_input_samples = len(getattr(result, "samples", []) or []) if result is not None else 0

        input_summary = (
            f"source_video_id={source_id} total_input_samples={total_input_samples} "
            f"outlier_window={request.outlier_window}"
        )
        output_summary = (
            f"samples_processed={self._samples_processed} "
            f"held_forward_unusable_count={self._held_forward_unusable_count} "
            f"held_forward_outlier_count={self._held_forward_outlier_count} "
            f"no_reliable_value_yet_count={self._no_reliable_value_yet_count}"
        )
        return self._tracker.build(
            module_name=MODULE_NAME,
            input_summary=input_summary,
            output_summary=output_summary,
            warnings=[],
            failure_reason=self._failure_reason,
        )
