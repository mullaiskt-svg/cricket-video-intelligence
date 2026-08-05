"""Stage 1: Ground Truth Extraction.

See specs/013-match-metadata-validation/contracts/metadata_pipeline_contract.md
Stage 1. Delegates entirely to the supplied MetadataProvider (research.md
Decision 3) -- owns no parsing logic of its own beyond choosing the
default provider.
"""

from __future__ import annotations

from typing import Tuple

from cvip.metadata.extraction_models import MetadataEvent, MetadataProvider
from cvip.metadata.providers.ball_by_ball_json import BallByBallJsonProvider


def extract_ground_truth(
    metadata_path: str, provider: MetadataProvider = None
) -> Tuple[MetadataEvent, ...]:
    """Reads `metadata_path` via `provider` (defaulting to
    BallByBallJsonProvider) and returns its FOUR/SIX/WICKET events.
    Propagates MetadataValidationError(METADATA_FILE_UNREADABLE) from the
    provider unchanged (FR-009) -- never returns a partial list silently."""
    if provider is None:
        provider = BallByBallJsonProvider()
    return provider.extract(metadata_path)
