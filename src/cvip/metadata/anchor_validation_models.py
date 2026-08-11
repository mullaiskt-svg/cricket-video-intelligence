"""Data model for Stage 2b: Anchor Validation.

See specs/014-anchor-validation/data-model.md. These are the types Stage 2b
(`anchor_validation.py`) produces and Stage 2 (`alignment.py`) folds into
its own `MatchAlignmentEvidence` (`alignment_models.py`).

Self-caught correction to data-model.md during implementation: the OCR
quality signal gained a fifth verdict, `UNKNOWN`, alongside the documented
HIGH/MEDIUM/LOW/INSUFFICIENT -- for a candidate reading with no
`ocr_confidence` value at all (distinct from a reading that *has* a value
and it's simply low). This mirrors the other three signals, all of which
already have an `UNKNOWN` verdict for "not enough information," and treats
missing data the same way the rest of this design already treats it: as
something to be conservative about, not something to hard-reject on --
only a *known-bad* reading (`INSUFFICIENT`) blocks acceptance outright.

Also: `MatchAlignmentEvidence.rejected_candidates` (alignment_models.py)
holds `RejectedCandidate` pairs (a `CandidateAnchor` plus the
`AnchorValidationSignals` that got it rejected), not bare `CandidateAnchor`
objects as data-model.md's prose suggested -- `summarize()`'s
`ordering_violations_detected`/`ordering_violations_prevented` counts
(spec FR-010) need each rejected candidate's own ordering verdict, and
`MatchAlignmentEvidence` is the only thing `summarize()` receives (research
.md Decision 9's own choice to fold results into `AccuracyReport` rather
than thread a second object through `analyze_accuracy()`'s signature).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple

from cvip.metadata.alignment_models import AlignmentConfidenceTier
from cvip.metadata.extraction_models import MetadataEvent


class AnchorConfidenceTier(str, Enum):
    """The validation *outcome* classification -- distinct from
    `AlignmentConfidenceTier`, which describes which *search* tier produced
    a candidate, not whether it was ultimately trusted (research.md
    Decision 6)."""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNRESOLVED = "UNRESOLVED"


class OCRQualityVerdict(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    INSUFFICIENT = "INSUFFICIENT"
    UNKNOWN = "UNKNOWN"


class ScoreStateVerdict(str, Enum):
    CONSISTENT = "CONSISTENT"
    UNKNOWN = "UNKNOWN"
    INCONSISTENT = "INCONSISTENT"


class OrderingVerdict(str, Enum):
    PRESERVED = "PRESERVED"
    VIOLATION = "VIOLATION"


class NeighborPacingVerdict(str, Enum):
    WITHIN_EXPECTED = "WITHIN_EXPECTED"
    SUSPICIOUS = "SUSPICIOUS"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class AnchorValidationConfig:
    """Thresholds mirroring config/default.yaml's `metadata.anchor_validation`
    block (research.md Decision 4) -- passed explicitly by the caller
    rather than read from disk by this module, matching every prior
    module's own config-value-passing precedent (e.g. Event Detection's
    `ranking`/`team_milestone_interval`, `EventDetectionRequest`)."""

    ocr_confidence_high: float = 0.60
    ocr_confidence_medium: float = 0.35
    ocr_confidence_low: float = 0.15
    #: Self-caught recalibration (specs/016 follow-on investigation): the
    #: original 3.0 was chosen without checking the real observed ratio
    #: distribution. On ww_vs_pf, the 33 WITHIN_EXPECTED accepted candidates
    #: span ratio 0.378-2.974; 4 real, otherwise-clean boundaries landed
    #: just outside that at 3.09-3.965 (a marginal miss, not a wrong match);
    #: the next-nearest genuinely-anomalous candidates start at 11.9. 5.0
    #: covers the real marginal cluster with headroom while staying well
    #: below the anomalous cluster's floor -- see config/default.yaml's own
    #: comment for the same rationale.
    neighbor_pacing_tolerance: float = 5.0


DEFAULT_ANCHOR_VALIDATION_CONFIG = AnchorValidationConfig()


@dataclass(frozen=True)
class CandidateAnchor:
    """One scoreboard reading being considered as a possible timestamp
    source for one metadata event, before validation judges it -- Stage
    2a's output."""

    reading: object  # ScoreboardReadingLike (structural typing; a dict in practice)
    search_tier: AlignmentConfidenceTier
    rank: int


@dataclass(frozen=True)
class AnchorValidationSignals:
    """The per-signal breakdown behind one confidence-tier decision -- the
    substance of Story 2's rejection diagnostics (spec FR-009)."""

    ocr_quality: OCRQualityVerdict
    ocr_confidence_value: Optional[float]
    score_state: ScoreStateVerdict
    ordering: OrderingVerdict
    neighbor_pacing: NeighborPacingVerdict
    reason: str


@dataclass(frozen=True)
class OrderingConflict:
    """Detail captured when a candidate's ordering signal is `VIOLATION`."""

    candidate_timestamp_seconds: float
    conflicting_anchor_event: MetadataEvent
    conflicting_anchor_timestamp_seconds: float


@dataclass(frozen=True)
class RejectedCandidate:
    """One candidate that was tried and did not clear the hard-reject
    checks -- pairs the candidate itself with the signals that rejected
    it, so downstream diagnostics/summary code never needs to re-evaluate
    anything (determinism, research.md Decision 7 applied to this pairing
    too: it is captured once, at evaluation time, not recomputed later)."""

    candidate: CandidateAnchor
    signals: AnchorValidationSignals


@dataclass(frozen=True)
class AnchorValidationResult:
    """One metadata event's full validation outcome -- what
    `validate_anchors()` returns, one per input event, before
    `alignment.py` folds it into a `MatchAlignmentEvidence`."""

    accepted_candidate: Optional[CandidateAnchor]
    tier: AnchorConfidenceTier
    signals: Optional[AnchorValidationSignals]
    rejected_candidates: Tuple[RejectedCandidate, ...]


@dataclass(frozen=True)
class AlignmentValidationSummary:
    """The Validation Run Summary entity (spec.md) -- an aggregate over one
    full `align()` call's results, computed by `summarize()`."""

    total_metadata_events: int
    anchored_high_confidence: int
    anchored_medium_confidence: int
    anchored_low_confidence: int
    unresolved_count: int
    ordering_violations_detected: int
    ordering_violations_prevented: int
