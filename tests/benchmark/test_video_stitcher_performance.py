"""Benchmark test for Video Stitcher: SC-005 (well within the platform's
2-minute `generate` budget). T033's concrete threshold exists primarily as
a regression tripwire (e.g. an accidental fallback to re-encoding), not
because the budget is actually tight -- see tasks.md Notes. Deselected by
default -- run explicitly with `pytest -m benchmark` (see pyproject.toml).
"""

import time
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from cvip.stitcher.models import StitchRequest
from cvip.stitcher.stitcher import stitch_video

pytestmark = pytest.mark.benchmark

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "video_stitcher"
SOURCE_LONG = str(FIXTURES_DIR / "source_long.mp4")

CLIP_COUNT = 36  # "a few dozen clips" (spec.md SC-005)


@pytest.fixture(autouse=True)
def _require_video_stitcher_fixtures():
    """Skip with an actionable message on a fresh checkout (*.mp4 is
    gitignored) rather than failing confusingly with SOURCE_VIDEO_UNAVAILABLE."""
    if not Path(SOURCE_LONG).exists():
        pytest.skip(
            "Video Stitcher fixtures not found -- run "
            "`python tests/fixtures/video_stitcher/generate_fixtures.py` first."
        )
BUDGET_SECONDS = 30.0


@dataclass(frozen=True)
class _Clip:
    clip_id: str
    clip_start_seconds: float
    clip_end_seconds: float
    source_video_path: str
    source_event_ids: tuple = field(default_factory=tuple)


@dataclass(frozen=True)
class _ClipPlan:
    clips: tuple


def _synthetic_clip_plan() -> _ClipPlan:
    # source_long.mp4 is 120s; spread 36 non-overlapping 2s clips across it.
    clips = tuple(
        _Clip(f"c{i}", float(i * 3), float(i * 3 + 2), SOURCE_LONG) for i in range(CLIP_COUNT)
    )
    return _ClipPlan(clips=clips)


def test_stitching_a_few_dozen_clips_completes_within_budget(tmp_path):
    clip_plan = _synthetic_clip_plan()
    output_path = tmp_path / "highlights.mp4"
    request = StitchRequest(clip_plan=clip_plan, output_path=str(output_path))

    start = time.perf_counter()
    with stitch_video(request) as runner:
        result = runner.run()
    elapsed = time.perf_counter() - start

    assert elapsed < BUDGET_SECONDS, f"stitching took {elapsed:.1f}s, over the {BUDGET_SECONDS}s budget (SC-005)"
    assert result.clip_count == CLIP_COUNT
