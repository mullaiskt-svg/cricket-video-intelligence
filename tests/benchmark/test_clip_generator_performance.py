"""Benchmark test for Clip Generator: SC-006 (negligible relative to the
platform's 2-minute `generate` budget). Unlike Module 5's SC-004 (a hard
<1 minute ceiling against ~12,600 samples), this feature's scale (a few
hundred events) makes this primarily a regression tripwire -- see
tasks.md's Notes. Deselected by default -- run explicitly with
`pytest -m benchmark` (see pyproject.toml).
"""

import time
from dataclasses import dataclass

import pytest

from cvip.clips.generator import generate_clips
from cvip.clips.models import ClipGenerationRequest

pytestmark = pytest.mark.benchmark

TOTAL_EVENTS = 500  # a generous full-match filtered-event count (technical_plan.md)
BUDGET_SECONDS = 5.0


@dataclass(frozen=True)
class _Event:
    event_key: str
    timestamp_seconds: float
    is_replay: bool = False


def _synthetic_events(total: int):
    # Spread events across a ~3.5-hour match (12,600 seconds), with every
    # 5th event flagged as a replay to exercise Replay Filtering at scale.
    return [
        _Event(f"e{i}", float(i * 25), is_replay=(i % 5 == 0))
        for i in range(total)
    ]


def test_generating_a_clip_plan_for_a_few_hundred_events_completes_within_budget():
    request = ClipGenerationRequest(
        events=tuple(_synthetic_events(TOTAL_EVENTS)),
        source_video_path="samples/match.mp4",
        video_duration_seconds=12_600.0,
        pre_roll_seconds=8.0,
        post_roll_seconds=12.0,
        merge_gap_seconds=3.0,
        include_replays=False,
    )

    start = time.perf_counter()
    with generate_clips(request) as runner:
        plan = runner.run()
    elapsed = time.perf_counter() - start

    assert elapsed < BUDGET_SECONDS, f"clip generation took {elapsed:.2f}s, over the {BUDGET_SECONDS}s budget (SC-006)"
    assert plan.total_clips >= 0
