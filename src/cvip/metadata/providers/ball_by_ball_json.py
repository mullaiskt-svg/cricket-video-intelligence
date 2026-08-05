"""V1's one MetadataProvider implementation (research.md Decision 3):
ball-by-ball JSON, one entry per delivery, structurally evolving the shape
already proven in ground_truth_v2/build_ground_truth.py (a per-innings
`{"commentary": [{"ball": "19.5", "description": "..."}]}` list) by nesting
one or two innings' worth of it under a single file's `innings` array, so
one `--metadata PATH` covers a whole match:

    {
      "innings": [
        {"innings": 1, "commentary": [{"ball": "19.5", "description": "..."}, ...]},
        {"innings": 2, "commentary": [...]}
      ]
    }

A single-innings match supplies only one entry in `innings` (Edge Cases:
"Metadata covers only one innings of a two-innings match").
"""

from __future__ import annotations

import json
import re
from typing import Tuple

from cvip.metadata.errors import MetadataValidationError, MetadataValidationFailureReason
from cvip.metadata.extraction_models import MetadataEvent


class BallByBallJsonProvider:
    """MetadataProvider (extraction_models.MetadataProvider Protocol)."""

    def extract(self, path: str) -> Tuple[MetadataEvent, ...]:
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError) as exc:
            raise MetadataValidationError(
                MetadataValidationFailureReason.METADATA_FILE_UNREADABLE,
                f"could not read metadata file at {path}: {exc}",
            ) from exc

        try:
            innings_list = data["innings"]
            events = []
            for innings_entry in innings_list:
                innings = innings_entry["innings"]
                for delivery in innings_entry["commentary"]:
                    event_type = _classify(delivery["description"])
                    if event_type is None:
                        continue
                    over_number, ball_in_over = _parse_over_ball(delivery["ball"])
                    events.append(
                        MetadataEvent(
                            innings=innings,
                            over_number=over_number,
                            ball_in_over=ball_in_over,
                            event_type=event_type,
                            description=delivery["description"],
                        )
                    )
        except (KeyError, TypeError, ValueError) as exc:
            raise MetadataValidationError(
                MetadataValidationFailureReason.METADATA_FILE_UNREADABLE,
                f"metadata file at {path} does not match the expected ball-by-ball shape: {exc}",
            ) from exc

        return tuple(events)


_OUT_RE = re.compile(r"\bOUT\b")


def _classify(description: str):
    """FOUR/SIX/WICKET keyword classification. Uses word-boundary matching
    for OUT to avoid false positives from substrings like "ABOUT" or
    "OUTSIDE" that contain "OUT" but are not wicket deliveries."""
    if "SIX" in description:
        return "SIX"
    if "FOUR" in description:
        return "FOUR"
    if _OUT_RE.search(description):
        return "WICKET"
    return None


def _parse_over_ball(over_ball: str) -> Tuple[int, int]:
    over, ball = over_ball.split(".")
    return int(over), int(ball)
