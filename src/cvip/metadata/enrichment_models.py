"""Data model for Stage 6: Optional Enrichment.

See specs/013-match-metadata-validation/data-model.md "DismissalDetail
(Story 3)".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class DismissalDetail:
    """FR-014. `dismissal_type`/`fielder` are both None when the
    description wasn't confidently readable -- never guessed."""

    dismissal_type: Optional[str]
    fielder: Optional[str]
