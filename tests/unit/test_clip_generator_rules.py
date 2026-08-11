"""Unit tests for Clip Generator's per-stage rules: windowing, clamping,
replay filtering, the Merge Engine (overlap/gap-threshold/chain, MergeReason
tagging, tie-break), clip_id determinism, ClipEvidence completeness, and
diagnostics field coverage.
"""

from dataclasses import dataclass

from cvip.clips.generator import generate_clips
from cvip.clips.models import ClipGenerationRequest, ClipStartSource, MergeReason


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


# -- US1: windowing and clamping (FR-002, FR-003, SC-001, SC-003) ----------


def test_raw_clip_window_computed_from_pre_and_post_roll():
    request = _request([_Event("e1", 120.0)])
    with generate_clips(request) as runner:
        plan = runner.run()

    assert plan.total_clips == 1
    clip = plan.clips[0]
    assert clip.clip_start_seconds == 112.0
    assert clip.clip_end_seconds == 132.0


def test_clip_start_clamped_to_zero_when_raw_start_negative():
    request = _request([_Event("e1", 3.0)], pre_roll_seconds=8.0)
    with generate_clips(request) as runner:
        plan = runner.run()

    assert plan.clips[0].clip_start_seconds == 0.0


def test_clip_end_clamped_to_video_duration_when_raw_end_exceeds_it():
    request = _request([_Event("e1", 3595.0)], video_duration_seconds=3600.0, post_roll_seconds=12.0)
    with generate_clips(request) as runner:
        plan = runner.run()

    assert plan.clips[0].clip_end_seconds == 3600.0


def test_clip_window_wholly_beyond_video_duration_is_not_inverted():
    # timestamp=1000 with an 8s/12s pre/post-roll against a 100s video: the
    # raw window [992,1012] falls entirely past video_duration_seconds, so
    # clamping only clip_start_seconds's lower bound and clip_end_seconds's
    # upper bound (single-sided) would otherwise produce clip_start=992,
    # clip_end=100 -- an inverted window (start > end).
    request = _request([_Event("e1", 1000.0)], video_duration_seconds=100.0)
    with generate_clips(request) as runner:
        plan = runner.run()

    clip = plan.clips[0]
    assert clip.clip_start_seconds <= clip.clip_end_seconds
    assert 0.0 <= clip.clip_start_seconds <= 100.0
    assert 0.0 <= clip.clip_end_seconds <= 100.0


def test_clip_window_wholly_before_zero_is_not_inverted():
    # timestamp=-1000 with a 12s post-roll: raw_end=-988, entirely before 0
    # -- single-sided clamping would leave clip_end_seconds negative while
    # clip_start_seconds clamps to 0, again inverting the window.
    request = _request([_Event("e1", -1000.0)], video_duration_seconds=3600.0)
    with generate_clips(request) as runner:
        plan = runner.run()

    clip = plan.clips[0]
    assert clip.clip_start_seconds <= clip.clip_end_seconds
    assert 0.0 <= clip.clip_start_seconds <= 3600.0
    assert 0.0 <= clip.clip_end_seconds <= 3600.0


def test_empty_input_event_list_yields_valid_empty_clip_plan():
    request = _request([])
    with generate_clips(request) as runner:
        plan = runner.run()

    assert plan.clips == ()
    assert plan.total_clips == 0


# -- US2: replay inclusion/exclusion (FR-004, FR-005, SC-005) --------------


def test_replay_flagged_event_excluded_by_default():
    request = _request([_Event("e1", 120.0, is_replay=True)], include_replays=False)
    with generate_clips(request) as runner:
        plan = runner.run()

    assert plan.clips == ()


def test_replay_flagged_event_included_when_flag_set():
    request = _request([_Event("e1", 120.0, is_replay=True)], include_replays=True)
    with generate_clips(request) as runner:
        plan = runner.run()

    assert plan.total_clips == 1
    assert plan.clips[0].contains_replay is True


# -- US3: Merge Engine (FR-006, FR-007, FR-008, SC-002) ---------------------


def test_overlapping_windows_merge_with_overlap_reason():
    # 8s pre-roll/12s post-roll (defaults) -> e1 window [92,112], e2 window
    # [102,122]; e2's start (102) falls at/before e1's anchor end (112) -> OVERLAP
    request = _request([_Event("e1", 100.0), _Event("e2", 110.0)])
    with generate_clips(request) as runner:
        plan = runner.run()
        evidence = {e.event_id: e for e in runner.evidence}

    assert plan.total_clips == 1
    clip = plan.clips[0]
    assert clip.merged is True
    assert clip.event_count == 2
    assert evidence["e2"].merge_reasons == (MergeReason.OVERLAP,)


def test_gap_threshold_windows_merge_with_gap_threshold_reason():
    # e1 window [92,112]; e2 window [114,134] -- gap = 114-112 = 2, <= merge_gap_seconds (3.0)
    request = _request([_Event("e1", 100.0), _Event("e2", 122.0)], merge_gap_seconds=3.0)
    with generate_clips(request) as runner:
        plan = runner.run()
        evidence = {e.event_id: e for e in runner.evidence}

    assert plan.total_clips == 1
    assert plan.clips[0].event_count == 2
    assert evidence["e2"].merge_reasons == (MergeReason.GAP_THRESHOLD,)


def test_windows_separated_beyond_gap_threshold_stay_separate():
    # e1 window [92,112]; e2 window [292,312] -- gap = 292-112 = 180, far beyond 3.0
    request = _request([_Event("e1", 100.0), _Event("e2", 300.0)], merge_gap_seconds=3.0)
    with generate_clips(request) as runner:
        plan = runner.run()

    assert plan.total_clips == 2
    assert all(clip.event_count == 1 and not clip.merged for clip in plan.clips)
    # FR-008 postcondition, pairwise case: no overlap and gap exceeds threshold
    assert plan.clips[1].clip_start_seconds - plan.clips[0].clip_end_seconds > 3.0


def test_chained_windows_collapse_with_chain_merge_tagging():
    # e1: [92,112] (anchor); e2: [102,122] overlaps e1's anchor end (112) -> OVERLAP,
    # extending the frontier to 122; e3: [120,140] doesn't qualify directly against
    # e1's anchor end (120-112=8 > merge_gap 3), but does overlap the frontier (120<=122) -> CHAIN_MERGE
    request = _request(
        [_Event("e1", 100.0), _Event("e2", 110.0), _Event("e3", 128.0)],
        merge_gap_seconds=3.0,
    )
    with generate_clips(request) as runner:
        plan = runner.run()
        evidence = {e.event_id: e for e in runner.evidence}

    assert plan.total_clips == 1
    clip = plan.clips[0]
    assert clip.event_count == 3
    assert evidence["e2"].merge_reasons == (MergeReason.OVERLAP,)
    assert evidence["e3"].merge_reasons == (MergeReason.CHAIN_MERGE,)
    assert evidence["e3"].merge_reasons != evidence["e2"].merge_reasons


def test_chain_merge_via_frontier_gap_not_frontier_overlap():
    # e1: [92,112] (anchor); e2: [102,122] overlaps e1 -> OVERLAP, frontier becomes 122;
    # e3: [124,144] doesn't qualify directly against the anchor end (124-112=12 > 3),
    # doesn't overlap the frontier either (124 > 122), but its gap from the frontier
    # (124-122=2) is <= merge_gap_seconds (3.0) -> CHAIN_MERGE via the frontier-gap branch
    request = _request(
        [_Event("e1", 100.0), _Event("e2", 110.0), _Event("e3", 132.0)],
        merge_gap_seconds=3.0,
    )
    with generate_clips(request) as runner:
        plan = runner.run()
        evidence = {e.event_id: e for e in runner.evidence}

    assert plan.total_clips == 1
    assert plan.clips[0].event_count == 3
    assert evidence["e3"].merge_reasons == (MergeReason.CHAIN_MERGE,)


def test_same_timestamp_events_merge_with_tie_break_ordering():
    request = _request([_Event("a:FOUR", 100.0), _Event("a:TEAM_MILESTONE", 100.0)])
    with generate_clips(request) as runner:
        plan = runner.run()

    assert plan.total_clips == 1
    clip = plan.clips[0]
    assert clip.event_count == 2
    assert set(clip.source_event_ids) == {"a:FOUR", "a:TEAM_MILESTONE"}
    # Tie-break: identical start/end -> original input order preserved
    assert clip.source_event_ids == ("a:FOUR", "a:TEAM_MILESTONE")


def test_zero_merge_gap_still_merges_exactly_touching_windows():
    # pre_roll=0, post_roll=12 -> e1 window [100,112]; e2 window [112,124]
    # (e2's start exactly equals e1's end -- zero-second gap, still touching)
    request = _request([_Event("e1", 100.0), _Event("e2", 112.0)], merge_gap_seconds=0.0, pre_roll_seconds=0.0)
    with generate_clips(request) as runner:
        plan = runner.run()

    assert plan.total_clips == 1
    assert plan.clips[0].event_count == 2


# -- clip_id determinism (FR-010, SC-007) -----------------------------------


def test_clip_id_is_deterministic_and_unique_within_plan():
    request = _request([_Event("e1", 100.0), _Event("e2", 110.0), _Event("e3", 500.0)])
    with generate_clips(request) as runner1:
        plan1 = runner1.run()
    with generate_clips(request) as runner2:
        plan2 = runner2.run()

    ids1 = [c.clip_id for c in plan1.clips]
    ids2 = [c.clip_id for c in plan2.clips]
    assert ids1 == ids2
    assert len(set(ids1)) == len(ids1)  # unique within plan
    merged_clip = next(c for c in plan1.clips if c.merged)
    assert merged_clip.clip_id == "+".join(sorted(merged_clip.source_event_ids))


# -- ClipEvidence completeness (FR-016, SC-008) ------------------------------


def test_clip_evidence_accounts_for_every_input_event_exactly_once():
    request = _request(
        [_Event("e1", 100.0), _Event("e2", 110.0), _Event("replay1", 500.0, is_replay=True)],
        include_replays=False,
    )
    with generate_clips(request) as runner:
        runner.run()
        evidence = {e.event_id: e for e in runner.evidence}

    assert len(evidence) == 3
    for event_id, record in evidence.items():
        linked = record.resulting_clip_id is not None
        excluded = record.excluded_due_to_replay
        assert linked != excluded, f"{event_id}: must be linked to a clip XOR excluded, never neither/both"
    assert evidence["replay1"].excluded_due_to_replay is True
    assert evidence["replay1"].resulting_clip_id is None
    assert evidence["e1"].resulting_clip_id is not None
    assert evidence["e1"].excluded_due_to_replay is False


# -- diagnostics (FR-017, research.md Decision 6) ----------------------------


def test_diagnostics_output_summary_contains_all_fr017_fields(mocker):
    emit_spy = mocker.patch("cvip.clips.generator.emit_diagnostics")
    request = _request([_Event("e1", 100.0), _Event("e2", 110.0)])
    with generate_clips(request) as runner:
        runner.run()

    output_summary = emit_spy.call_args[0][0].output_summary
    for field_name in (
        "events_received",
        "replay_events_excluded",
        "clip_windows_generated",
        "merge_operations_performed",
        "final_clip_count",
        "average_clip_duration",
        "total_planned_duration",
        "config_version",
    ):
        assert field_name in output_summary, f"{field_name!r} missing from diagnostics output_summary"
    assert "events_received=2" in output_summary
    assert "final_clip_count=1" in output_summary


def test_average_clip_duration_is_zero_when_no_clips_produced(mocker):
    emit_spy = mocker.patch("cvip.clips.generator.emit_diagnostics")
    request = _request([_Event("e1", 100.0, is_replay=True)], include_replays=False)
    with generate_clips(request) as runner:
        runner.run()

    output_summary = emit_spy.call_args[0][0].output_summary
    assert "average_clip_duration=0.0" in output_summary
    assert "final_clip_count=0" in output_summary


# -- specs/016-scene-cut-clip-windows: nearest-before-cut search -----------
# (Foundational: the search algorithm in isolation, per research.md Decision 1)


def test_nearest_before_search_returns_largest_qualifying_cut_not_earliest():
    # event at t=120, pre_roll=8 -> fixed fallback would be 112; two cuts
    # (100, 115) both qualify within max_cut_search_seconds=20 -- the
    # nearest (115), not the earliest (100), must be used.
    request = _request([_Event("e1", 120.0)], scene_cuts=(50.0, 100.0, 115.0), max_cut_search_seconds=20.0)
    with generate_clips(request) as runner:
        runner.run()

    evidence = runner.evidence[0]
    assert evidence.original_window[0] == 115.0
    assert evidence.start_source == ClipStartSource.CUT_MATCHED


def test_cut_exactly_at_max_search_distance_qualifies_one_second_further_does_not():
    # event at t=120, max_cut_search_seconds=20 -> boundary is exactly t=100.
    request_at_boundary = _request([_Event("e1", 120.0)], scene_cuts=(100.0,), max_cut_search_seconds=20.0)
    with generate_clips(request_at_boundary) as runner:
        runner.run()
    assert runner.evidence[0].start_source == ClipStartSource.CUT_MATCHED
    assert runner.evidence[0].original_window[0] == 100.0

    request_beyond_boundary = _request([_Event("e1", 120.0)], scene_cuts=(99.0,), max_cut_search_seconds=20.0)
    with generate_clips(request_beyond_boundary) as runner:
        runner.run()
    assert runner.evidence[0].start_source == ClipStartSource.FIXED_OFFSET


def test_cut_exactly_at_event_timestamp_qualifies():
    request = _request([_Event("e1", 120.0)], scene_cuts=(120.0,), max_cut_search_seconds=20.0)
    with generate_clips(request) as runner:
        runner.run()

    evidence = runner.evidence[0]
    assert evidence.start_source == ClipStartSource.CUT_MATCHED
    assert evidence.original_window[0] == 120.0


def test_unsorted_scene_cuts_produce_same_result_as_sorted():
    request_unsorted = _request([_Event("e1", 120.0)], scene_cuts=(115.0, 50.0, 100.0), max_cut_search_seconds=20.0)
    with generate_clips(request_unsorted) as runner:
        runner.run()
    unsorted_result = runner.evidence[0].original_window[0]

    request_sorted = _request([_Event("e1", 120.0)], scene_cuts=(50.0, 100.0, 115.0), max_cut_search_seconds=20.0)
    with generate_clips(request_sorted) as runner:
        runner.run()
    sorted_result = runner.evidence[0].original_window[0]

    assert unsorted_result == sorted_result == 115.0


def test_empty_scene_cuts_finds_no_candidate():
    request = _request([_Event("e1", 120.0)], scene_cuts=())
    with generate_clips(request) as runner:
        runner.run()
    assert runner.evidence[0].start_source == ClipStartSource.FIXED_OFFSET


def test_scene_cuts_all_after_event_finds_no_candidate():
    request = _request([_Event("e1", 120.0)], scene_cuts=(121.0, 150.0), max_cut_search_seconds=20.0)
    with generate_clips(request) as runner:
        runner.run()
    assert runner.evidence[0].start_source == ClipStartSource.FIXED_OFFSET


# -- specs/016-scene-cut-clip-windows US1: wiring into Pass 1 ---------------


def test_event_with_qualifying_cut_uses_cut_as_raw_start():
    request = _request([_Event("e1", 120.0)], pre_roll_seconds=8.0, scene_cuts=(115.0,), max_cut_search_seconds=20.0)
    with generate_clips(request) as runner:
        plan = runner.run()

    evidence = runner.evidence[0]
    assert evidence.original_window[0] == 115.0
    assert evidence.start_source == ClipStartSource.CUT_MATCHED
    assert plan.clips[0].clip_start_seconds == 115.0


def test_event_with_no_qualifying_cut_falls_back_to_fixed_pre_roll():
    request = _request([_Event("e1", 120.0)], pre_roll_seconds=8.0, scene_cuts=(1.0,), max_cut_search_seconds=20.0)
    with generate_clips(request) as runner:
        plan = runner.run()

    evidence = runner.evidence[0]
    assert evidence.original_window[0] == 112.0  # 120 - 8, unchanged from specs/008
    assert evidence.start_source == ClipStartSource.FIXED_OFFSET
    assert plan.clips[0].clip_start_seconds == 112.0


def test_scene_cut_snapping_never_affects_raw_end_post_roll():
    request = _request(
        [_Event("e1", 120.0)], pre_roll_seconds=8.0, post_roll_seconds=12.0, scene_cuts=(115.0,), max_cut_search_seconds=20.0
    )
    with generate_clips(request) as runner:
        runner.run()
    assert runner.evidence[0].original_window[1] == 132.0  # 120 + 12, unaffected by snapping

    request_fallback = _request([_Event("e1", 120.0)], pre_roll_seconds=8.0, post_roll_seconds=12.0, scene_cuts=())
    with generate_clips(request_fallback) as runner:
        runner.run()
    assert runner.evidence[0].original_window[1] == 132.0


def test_mixed_run_some_events_cut_matched_others_fixed_offset():
    # e1 has a qualifying cut nearby; e2 does not.
    request = _request(
        [_Event("e1", 120.0), _Event("e2", 500.0)],
        pre_roll_seconds=8.0,
        merge_gap_seconds=3.0,
        scene_cuts=(115.0,),
        max_cut_search_seconds=20.0,
    )
    with generate_clips(request) as runner:
        runner.run()
        evidence = {e.event_id: e for e in runner.evidence}

    assert evidence["e1"].start_source == ClipStartSource.CUT_MATCHED
    assert evidence["e2"].start_source == ClipStartSource.FIXED_OFFSET
    assert evidence["e2"].original_window[0] == 492.0  # 500 - 8, plain fallback


def test_merge_engine_unaffected_by_mixed_start_source_windows():
    # e1 (cut-matched, start snaps to 95 instead of fixed-offset 92) and e2
    # (fixed-offset, start 102 -- the cut at 95 is 15s before e2's own
    # timestamp of 110, beyond the 6s search distance used here, so e2 falls
    # back) still merge under OVERLAP exactly as specs/008's existing merge
    # rule dictates, regardless of how each window's start was produced.
    request = _request(
        [_Event("e1", 100.0), _Event("e2", 110.0)],
        pre_roll_seconds=8.0,
        post_roll_seconds=12.0,
        merge_gap_seconds=3.0,
        scene_cuts=(95.0,),
        max_cut_search_seconds=6.0,
    )
    with generate_clips(request) as runner:
        plan = runner.run()
        evidence = {e.event_id: e for e in runner.evidence}

    assert evidence["e1"].start_source == ClipStartSource.CUT_MATCHED
    assert evidence["e2"].start_source == ClipStartSource.FIXED_OFFSET
    assert plan.total_clips == 1
    assert plan.clips[0].event_count == 2
    assert plan.clips[0].clip_start_seconds == 95.0
