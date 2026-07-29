"""Clip Generator: generate_clips() and ClipGeneratorRunner.

See specs/008-clip-generator/contracts/clip_generator_contract.md for the
full contract this module implements.

Like Event Detection, this feature never touches a video file, frame, or
database -- its one input (a ClipGenerationRequest) is already a structured
Python object. A two-pass process (research.md Decision 1) implements the
six-stage Processing Model (spec.md): Pass 1 runs Stages 1-4 (Filtered
Events -> Clip Window Generation -> Boundary Clamping -> Replay Filtering),
building one ClipEvidence per input event as it goes; Pass 2 runs Stage 5
(Merge Engine) as a sorted sweep over the surviving windows, then Stage 6
assembles the final ordered ClipPlan.
"""

from __future__ import annotations

import math
from dataclasses import replace
from typing import Dict, List, Optional, Tuple

from cvip.clips.errors import ClipGenerationError, ClipGenerationFailureReason
from cvip.clips.models import (
    ClipEvidence,
    ClipGenerationRequest,
    ClipPlan,
    MergeReason,
    PlannedClip,
)
from cvip.common.diagnostics import DiagnosticsTracker, ExecutionDiagnostics, emit_diagnostics

MODULE_NAME = "clips.generator"

# The project's config schema version (config/default.yaml's config_version).
# This module accepts pre_roll_seconds/post_roll_seconds/merge_gap_seconds/
# include_replays as caller-supplied parameters (data-model.md) rather than
# reading config/default.yaml itself, but still reports which schema version
# was in effect for auditability (FR-017), matching Event Detection's own
# CONFIGURATION_VERSION precedent.
CONFIGURATION_VERSION = 1


def generate_clips(request: ClipGenerationRequest) -> "ClipGeneratorRunner":
    """Return a ClipGeneratorRunner for the given request. See the contract
    doc's Usage section -- always use as a context manager:

        with generate_clips(request) as runner:
            plan = runner.run()
    """
    return ClipGeneratorRunner(request)


class ClipGeneratorRunner:
    """Two-pass clip generation over an already-filtered event sequence,
    implementing the six-stage Processing Model (research.md Decision 1).

    Not constructed directly -- use `generate_clips()`. Validation of the
    inputs and configuration (FR-015) happens lazily, when `.run()` is
    called, not at construction time.
    """

    def __init__(self, request: ClipGenerationRequest) -> None:
        self._request = request
        self._finished = False
        self._diagnostics_emitted = False
        self._tracker = DiagnosticsTracker()
        self._tracker_entered = False
        self._failure_reason: Optional[str] = None

        self._events_received = 0
        self._replay_events_excluded = 0
        self._clip_windows_generated = 0
        self._merge_operations_performed = 0
        self._final_clip_count = 0
        self._total_planned_duration = 0.0

        self._plan: Optional[ClipPlan] = None
        self._evidence_list: List[ClipEvidence] = []

    def __enter__(self) -> "ClipGeneratorRunner":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self._finish()

    @property
    def evidence(self) -> List[ClipEvidence]:
        """The full internal `ClipEvidence` list, one entry per input
        event -- including replay-excluded ones -- in the same order as
        `request.events`, readable at any point, primarily for
        testing/debugging (FR-016)."""
        return self._evidence_list

    def run(self) -> ClipPlan:
        """Perform the full clip-generation operation and return a
        ClipPlan."""
        self._tracker.__enter__()
        self._tracker_entered = True

        self._validate_input()
        self._validate_configuration()

        request = self._request
        self._events_received = len(request.events)
        is_replay_by_id: Dict[str, bool] = {event.event_key: event.is_replay for event in request.events}

        # -- Pass 1 (Stages 2-4): window every event, clamp, filter replays --
        surviving: List[Tuple[int, ClipEvidence]] = []
        for index, event in enumerate(request.events):
            raw_start = event.timestamp_seconds - request.pre_roll_seconds
            raw_end = event.timestamp_seconds + request.post_roll_seconds
            self._clip_windows_generated += 1

            # Clamp both bounds on both sides -- an event far enough outside
            # [0, video_duration_seconds] would otherwise clamp only its
            # "near" side (e.g. a timestamp beyond the video's end clamps
            # clamped_start up to video_duration_seconds via the first
            # min(), while clamped_end is separately capped at the same
            # value), producing an inverted clamped_start > clamped_end
            # window that corrupts downstream duration/merge math.
            clamped_start = min(max(0.0, raw_start), request.video_duration_seconds)
            clamped_end = max(min(request.video_duration_seconds, raw_end), 0.0)

            excluded = event.is_replay and not request.include_replays
            evidence = ClipEvidence(
                event_id=event.event_key,
                original_window=(raw_start, raw_end),
                clamped_window=(clamped_start, clamped_end),
                excluded_due_to_replay=excluded,
            )
            self._evidence_list.append(evidence)

            if excluded:
                self._replay_events_excluded += 1
                continue

            surviving.append((index, evidence))

        # -- Pass 2 (Stage 5): sorted-sweep Merge Engine --
        clips = self._merge(surviving, is_replay_by_id)

        # -- Stage 6: Ordered Clip Plan --
        self._final_clip_count = len(clips)
        self._total_planned_duration = sum(clip.clip_end_seconds - clip.clip_start_seconds for clip in clips)

        self._plan = ClipPlan(
            source_video_path=request.source_video_path,
            clips=tuple(clips),
            total_clips=len(clips),
        )
        self._finished = True
        self._finish()
        return self._plan

    # -- internal: Merge Engine (research.md Decision 2) -------------------

    def _merge(
        self,
        surviving: List[Tuple[int, ClipEvidence]],
        is_replay_by_id: Dict[str, bool],
    ) -> List[PlannedClip]:
        if not surviving:
            return []

        # FR-009 tie-break: ascending clip_start_seconds, then ascending
        # clip_end_seconds, then original input position. Python's sort is
        # stable and `surviving` is already in original input order, so
        # sorting by (start, end) alone correctly implements the full
        # three-level tie-break.
        ordered = sorted(surviving, key=lambda item: (item[1].clamped_window[0], item[1].clamped_window[1]))

        clips: List[PlannedClip] = []
        merge_gap = self._request.merge_gap_seconds

        group_start, group_end = ordered[0][1].clamped_window
        group_anchor_end = group_end
        # (original_index, evidence, join_reason) -- join_reason is None for the anchor.
        group_entries: List[Tuple[int, ClipEvidence, Optional[MergeReason]]] = [(ordered[0][0], ordered[0][1], None)]

        for original_index, evidence in ordered[1:]:
            window_start, window_end = evidence.clamped_window
            reason = self._classify_join(group_anchor_end, group_end, window_start, merge_gap)

            if reason is not None:
                self._merge_operations_performed += 1
                group_end = max(group_end, window_end)
                group_entries.append((original_index, evidence, reason))
            else:
                clips.append(self._close_group(group_start, group_end, group_entries, is_replay_by_id))
                group_start, group_end = window_start, window_end
                group_anchor_end = group_end
                group_entries = [(original_index, evidence, None)]

        clips.append(self._close_group(group_start, group_end, group_entries, is_replay_by_id))
        return clips

    @staticmethod
    def _classify_join(
        anchor_end: float, frontier_end: float, window_start: float, merge_gap: float
    ) -> Optional[MergeReason]:
        """Whether/why a sorted window joins the current group (research.md
        Decision 2): a direct overlap/gap-threshold relationship to the
        group's own anchor end is OVERLAP/GAP_THRESHOLD; a relationship that
        only holds against the running merged frontier (past the anchor) is
        CHAIN_MERGE; no relationship at all returns None (group closes)."""
        if window_start <= anchor_end:
            return MergeReason.OVERLAP
        if window_start - anchor_end <= merge_gap:
            return MergeReason.GAP_THRESHOLD
        if window_start <= frontier_end:
            return MergeReason.CHAIN_MERGE
        if window_start - frontier_end <= merge_gap:
            return MergeReason.CHAIN_MERGE
        return None

    def _close_group(
        self,
        group_start: float,
        group_end: float,
        group_entries: List[Tuple[int, ClipEvidence, Optional[MergeReason]]],
        is_replay_by_id: Dict[str, bool],
    ) -> PlannedClip:
        """Assemble one closed merge group into a PlannedClip (FR-010,
        FR-011) and back-fill each contributing event's ClipEvidence
        (research.md Decision 4)."""
        source_event_ids = tuple(evidence.event_id for _, evidence, _ in group_entries)
        clip_id = "+".join(sorted(source_event_ids))
        event_count = len(source_event_ids)
        contains_replay = any(is_replay_by_id[event_id] for event_id in source_event_ids)

        for original_index, _, reason in group_entries:
            merge_reasons = (reason,) if reason is not None else ()
            self._evidence_list[original_index] = replace(
                self._evidence_list[original_index],
                resulting_clip_id=clip_id,
                merge_reasons=merge_reasons,
            )

        return PlannedClip(
            clip_id=clip_id,
            clip_start_seconds=group_start,
            clip_end_seconds=group_end,
            source_video_path=self._request.source_video_path,
            source_event_ids=source_event_ids,
            event_count=event_count,
            merged=event_count > 1,
            contains_replay=contains_replay,
        )

    # -- internal: validation ---------------------------------------------

    def _validate_input(self) -> None:
        request = self._request
        if request.events is None:
            self._fail(ClipGenerationFailureReason.INVALID_INPUT, "events is missing (None)")
        for index, event in enumerate(request.events):
            if (
                event is None
                or getattr(event, "event_key", None) is None
                or getattr(event, "timestamp_seconds", None) is None
                or getattr(event, "is_replay", None) is None
            ):
                self._fail(
                    ClipGenerationFailureReason.INVALID_INPUT,
                    f"events[{index}] does not expose event_key/timestamp_seconds/is_replay",
                )
        if not request.source_video_path:
            self._fail(ClipGenerationFailureReason.INVALID_INPUT, "source_video_path is missing or empty")

    def _validate_configuration(self) -> None:
        request = self._request
        for name, value in (
            ("video_duration_seconds", request.video_duration_seconds),
            ("pre_roll_seconds", request.pre_roll_seconds),
            ("post_roll_seconds", request.post_roll_seconds),
            ("merge_gap_seconds", request.merge_gap_seconds),
        ):
            if (
                value is None
                or isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value < 0
            ):
                self._fail(
                    ClipGenerationFailureReason.INVALID_CLIP_CONFIGURATION,
                    f"{name} {value!r} must be a finite number >= 0",
                )

    # -- internal: failure/diagnostics --------------------------------------

    def _fail(self, reason: ClipGenerationFailureReason, detail: str):
        self._failure_reason = reason.value
        self._finished = True
        self._finish()
        raise ClipGenerationError(reason, detail)

    def _finish(self) -> None:
        if self._tracker_entered and not self._diagnostics_emitted:
            self._tracker.__exit__(None, None, None)
            diagnostics = self._build_diagnostics()
            emit_diagnostics(diagnostics)
            self._diagnostics_emitted = True

    def _build_diagnostics(self) -> ExecutionDiagnostics:
        """Build the one ExecutionDiagnostics record for this run (FR-017)."""
        request = self._request
        total_input_events = len(getattr(request, "events", None) or [])
        source_video_path = getattr(request, "source_video_path", None)
        video_duration_seconds = getattr(request, "video_duration_seconds", None)
        pre_roll_seconds = getattr(request, "pre_roll_seconds", None)
        post_roll_seconds = getattr(request, "post_roll_seconds", None)
        merge_gap_seconds = getattr(request, "merge_gap_seconds", None)
        include_replays = getattr(request, "include_replays", None)

        input_summary = (
            f"events_count={total_input_events} source_video_path={source_video_path!r} "
            f"video_duration_seconds={video_duration_seconds} pre_roll_seconds={pre_roll_seconds} "
            f"post_roll_seconds={post_roll_seconds} merge_gap_seconds={merge_gap_seconds} "
            f"include_replays={include_replays}"
        )

        # FR-017 / research.md Decision 6: a successful zero-clip run reports
        # 0.0, never a ZeroDivisionError -- the guard is the whole point of this line.
        average_clip_duration = (
            (self._total_planned_duration / self._final_clip_count) if self._final_clip_count else 0.0
        )

        output_summary = (
            f"events_received={self._events_received} "
            f"replay_events_excluded={self._replay_events_excluded} "
            f"clip_windows_generated={self._clip_windows_generated} "
            f"merge_operations_performed={self._merge_operations_performed} "
            f"final_clip_count={self._final_clip_count} "
            f"average_clip_duration={average_clip_duration} "
            f"total_planned_duration={self._total_planned_duration} "
            f"config_version={CONFIGURATION_VERSION}"
        )
        return self._tracker.build(
            module_name=MODULE_NAME,
            input_summary=input_summary,
            output_summary=output_summary,
            warnings=[],
            failure_reason=self._failure_reason,
        )
