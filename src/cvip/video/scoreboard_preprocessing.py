"""Scoreboard OCR's pluggable preprocessing-strategy architecture.

Companion to scoreboard_parsers.py's `ScoreboardParser` architecture, same
shape: a public `Protocol`, self-describing `name`/`description` metadata,
and a registry keyed by name. Where `ScoreboardParser` answers "how do I
read the structured fields out of this format's OCR tokens," a
`PreprocessingStrategy` answers "how do I binarize/enhance this format's
ROI before handing it to Tesseract at all."

## Why this exists (specs/005-scoreboard-ocr/'s root-cause analysis)

A single global Otsu threshold, applied across the whole cropped scoreboard
strip, is correct for an overlay whose panels share one background (dark,
uniformly) -- the original and club-broadcast formats. It is actively
destructive on an overlay that mixes backgrounds within one strip (e.g. a
bright gold-gradient score panel beside solid-black panels): the single
threshold value that separates black-background text correctly cannot
also separate bright-background text, and the two panels' text is fused
into the same background value on one side or the other. Measured against
27 hand-verified real readings: Otsu achieves 3.7% exact-match accuracy on
that broadcast; per-neighborhood adaptive thresholding achieves 44.4% on
the identical frames, with zero change to the OCR engine, parser, or
validation logic.

## Selection: a locked-in choice per run, not a per-frame fallback chain

Preprocessing happens *before* OCR produces tokens, so it cannot be
selected from tokens the way `select_parser()` selects a parser -- and
deliberately does not try multiple strategies per frame once a strategy is
locked in (that would add a second Tesseract call to every frame for the
remainder of the run, and this module is already the platform's single
largest per-run performance-budget line item). Instead,
`ScoreboardOcrExtractor` runs a small, bounded warm-up using this module's
`DEFAULT_STRATEGY_NAME` (Otsu) as its first attempt per frame: once a
specific (non-generic) `ScoreboardParser` is confidently identified, that
parser's own declared `preferred_preprocessing_strategy` is locked in for
the remainder of the run -- a single OCR pass per frame in steady state,
including for the two already-working formats, which stay on Otsu. Only
while still warming up, and only on a frame where Otsu's result doesn't
confidently identify a format, does the extractor also trial the other
registered strategies against that same frame before spending the frame's
warm-up budget on it -- Otsu's own failure mode on a format it can't
binarize correctly is for that format's frames to look undetectable or
generic in the first place, so judging warm-up by Otsu's result alone
would never let such a format be recognized. This extra cost is bounded to
`PREPROCESSING_WARMUP_SAMPLE_LIMIT` frames, not every frame.

## Adding a new preprocessing strategy

1. Implement `PreprocessingStrategy` below: a `name`, a `description`, and
   an `apply(image)` method taking the already-grayscaled, already-upscaled
   ROI and returning the final image handed to Tesseract.
2. Add an instance to `PREPROCESSING_STRATEGIES`.
3. Set the `preferred_preprocessing_strategy` class attribute on whichever
   `ScoreboardParser` implementation(s) (scoreboard_parsers.py) should use
   it, referencing this strategy's `name`.

No existing strategy or parser needs to change.
"""

from __future__ import annotations

from typing import Dict, Protocol

import cv2
import numpy as np


class PreprocessingStrategy(Protocol):
    """The pluggable preprocessing extension point (see module docstring).
    Implementations are pure functions of the input image alone -- no
    shared mutable state, no dependency on prior frames."""

    #: A short, stable identifier -- referenced by
    #: `ScoreboardParser.preferred_preprocessing_strategy` and by
    #: `ScoreboardOcrExtractor`'s diagnostics.
    name: str

    #: A human-readable summary of what this strategy does and which kind
    #: of overlay it suits -- surfaced in diagnostics.
    description: str

    def apply(self, image: np.ndarray) -> np.ndarray:
        ...


class OtsuThresholdStrategy:
    """Global Otsu binarization -- this platform's original default.
    Correct for a single-background overlay (the whole ROI is one
    consistent background, e.g. solid black); destructive on an overlay
    whose panels mix a bright-gradient background with dark ones in the
    same ROI (see module docstring)."""

    name = "otsu_threshold"
    description = (
        "Global Otsu binarization across the whole ROI at once. Correct "
        "for a single-background overlay; washes out text on a "
        "bright-background panel sitting alongside dark ones in the same "
        "strip."
    )

    def apply(self, image: np.ndarray) -> np.ndarray:
        _, thresholded = cv2.threshold(image, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return thresholded


class AdaptiveMeanStrategy:
    """Per-neighborhood mean-adaptive binarization -- thresholds each
    local region against its own surrounding mean rather than one global
    value, so a bright-background panel and a dark-background panel in
    the same ROI can each be binarized correctly. Measured (specs/005's
    root-cause analysis, second independent match) at 44.4% exact-match
    accuracy on a broadcast where `OtsuThresholdStrategy` achieves 3.7%,
    identical source frames."""

    name = "adaptive_mean"
    description = (
        "Per-neighborhood mean-adaptive binarization (cv2.ADAPTIVE_THRESH_MEAN_C, "
        "31x31 block, C=10). Tolerates a heterogeneous-background ROI "
        "(e.g. a gold-gradient score panel beside solid-black panels) by "
        "thresholding each local region independently."
    )

    def apply(self, image: np.ndarray) -> np.ndarray:
        return cv2.adaptiveThreshold(
            image, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 31, 10
        )


PREPROCESSING_STRATEGIES: Dict[str, PreprocessingStrategy] = {
    strategy.name: strategy for strategy in (OtsuThresholdStrategy(), AdaptiveMeanStrategy())
}

#: Used during a run's warm-up window (before a specific format has been
#: identified) and as the permanent choice if warm-up never confidently
#: identifies one -- matches this platform's pre-existing default exactly,
#: so the two already-working formats see zero behavior change.
DEFAULT_STRATEGY_NAME = "otsu_threshold"
