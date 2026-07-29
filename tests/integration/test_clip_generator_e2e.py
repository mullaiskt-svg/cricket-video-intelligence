"""Integration tests for Clip Generator: multi-event windowing end-to-end,
mixed replay inclusion/exclusion, determinism, and the plan-wide non-overlap
postcondition (FR-008, SC-002).
"""

from dataclasses import dataclass

from cvip.clips.generator import generate_clips
from cvip.clips.models import ClipGenerationRequest


@dataclass(frozen=True)
class _Event:
    event_key: str
    timestamp_seconds: float
    is_replay: bool = False


def _request(events, **overrides) -> ClipGenerationRequest:
    defaults = dict(
        events=tuple(events),
        source_video_path="samples/match.mp4",
        video_duration_seconds=3600.0,
        pre_roll_seconds=8.0,
        post_roll_seconds=12.0,
        merge_gap_seconds=3.0,
        include_replays=False,
    )
    defaults.update(overrides)
    return ClipGenerationRequest(**defaults)


def test_well_separated_events_produce_one_ordered_clip_each():
    events = [_Event("e1", 100.0), _Event("e2", 500.0), _Event("e3", 900.0)]
    request = _request(events)
    with generate_clips(request) as runner:
        plan = runner.run()

    assert plan.total_clips == 3
    starts = [clip.clip_start_seconds for clip in plan.clips]
    assert starts == sorted(starts)
    for clip in plan.clips:
        assert clip.event_count == 1
        assert not clip.merged


def test_mixed_replay_and_non_replay_events_yield_clips_only_for_non_replay():
    events = [
        _Event("live1", 100.0, is_replay=False),
        _Event("replay1", 500.0, is_replay=True),
        _Event("live2", 900.0, is_replay=False),
        _Event("replay2", 1300.0, is_replay=True),
    ]
    request = _request(events, include_replays=False)
    with generate_clips(request) as runner:
        plan = runner.run()

    produced_ids = {eid for clip in plan.clips for eid in clip.source_event_ids}
    assert produced_ids == {"live1", "live2"}
    assert plan.total_clips == 2


def test_repeated_runs_produce_identical_clip_plans():
    events = [
        _Event("e1", 100.0),
        _Event("e2", 110.0),
        _Event("e3", 128.0),
        _Event("e4", 900.0),
    ]
    request = _request(events)

    with generate_clips(request) as runner1:
        plan1 = runner1.run()
    with generate_clips(request) as runner2:
        plan2 = runner2.run()

    assert plan1.clips == plan2.clips
    assert [c.clip_id for c in plan1.clips] == [c.clip_id for c in plan2.clips]


def test_plan_wide_non_overlap_postcondition_across_mixed_merge_groups():
    """FR-008, SC-002: combine several independent merge groups (an overlap
    pair, a gap-threshold pair, a transitive chain) with untouched
    singletons, and assert no two output clips overlap or sit within
    merge_gap_seconds of each other -- the global postcondition, not just
    each individual merge scenario checked in isolation."""
    events = [
        # Overlap pair: [92,112] and [102,122] -> merges
        _Event("overlap_a", 100.0),
        _Event("overlap_b", 110.0),
        # Untouched singleton, far from everything else
        _Event("singleton_1", 1000.0),
        # Gap-threshold pair: [1492,1512] and [1514,1534] -> merges (gap=2 <= 3)
        _Event("gap_a", 1500.0),
        _Event("gap_b", 1522.0),
        # Transitive chain: [2092,2112], [2102,2122] (OVERLAP), [2120,2140] (CHAIN_MERGE)
        _Event("chain_a", 2100.0),
        _Event("chain_b", 2110.0),
        _Event("chain_c", 2128.0),
        # Another untouched singleton
        _Event("singleton_2", 3000.0),
    ]
    request = _request(events, merge_gap_seconds=3.0)
    with generate_clips(request) as runner:
        plan = runner.run()

    # Three merge groups collapse to one clip each, plus two singletons.
    assert plan.total_clips == 5

    ordered_clips = sorted(plan.clips, key=lambda c: c.clip_start_seconds)
    for earlier, later in zip(ordered_clips, ordered_clips[1:]):
        assert later.clip_start_seconds > earlier.clip_end_seconds, "clips must not overlap"
        gap = later.clip_start_seconds - earlier.clip_end_seconds
        assert gap > request.merge_gap_seconds, "adjacent clips must be separated by more than merge_gap_seconds"
