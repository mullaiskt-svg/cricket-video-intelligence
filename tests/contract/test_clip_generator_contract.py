"""Contract test for Clip Generator: asserts generate_clips() matches
specs/008-clip-generator/contracts/clip_generator_contract.md's shape and
error taxonomy (FR-001, FR-015).
"""

from dataclasses import dataclass

import pytest

from cvip.clips.errors import ClipGenerationError, ClipGenerationFailureReason
from cvip.clips.generator import ClipGeneratorRunner, generate_clips
from cvip.clips.models import ClipGenerationRequest, ClipPlan


@dataclass(frozen=True)
class _Event:
    event_key: str
    timestamp_seconds: float
    is_replay: bool = False


def _valid_request(**overrides) -> ClipGenerationRequest:
    defaults = dict(
        events=(_Event("1:0.1:FOUR", 120.0),),
        source_video_path="samples/match.mp4",
        video_duration_seconds=3600.0,
        pre_roll_seconds=8.0,
        post_roll_seconds=12.0,
        merge_gap_seconds=3.0,
        include_replays=False,
    )
    defaults.update(overrides)
    return ClipGenerationRequest(**defaults)


def test_generate_clips_returns_a_runner_matching_the_contract_shape():
    runner = generate_clips(_valid_request())
    assert isinstance(runner, ClipGeneratorRunner)

    with runner:
        plan = runner.run()

    assert isinstance(plan, ClipPlan)
    assert plan.total_clips == len(plan.clips)


def test_missing_events_yields_invalid_input_before_processing():
    request = _valid_request(events=None)
    with pytest.raises(ClipGenerationError) as exc_info:
        with generate_clips(request) as runner:
            runner.run()
    assert exc_info.value.reason == ClipGenerationFailureReason.INVALID_INPUT


def test_malformed_event_element_yields_invalid_input_before_processing():
    request = _valid_request(events=(object(),))
    with pytest.raises(ClipGenerationError) as exc_info:
        with generate_clips(request) as runner:
            runner.run()
    assert exc_info.value.reason == ClipGenerationFailureReason.INVALID_INPUT


def test_missing_source_video_path_yields_invalid_input_before_processing():
    request = _valid_request(source_video_path="")
    with pytest.raises(ClipGenerationError) as exc_info:
        with generate_clips(request) as runner:
            runner.run()
    assert exc_info.value.reason == ClipGenerationFailureReason.INVALID_INPUT


@pytest.mark.parametrize(
    "field_name,invalid_value",
    [
        ("video_duration_seconds", -1.0),
        ("pre_roll_seconds", -1.0),
        ("post_roll_seconds", -1.0),
        ("merge_gap_seconds", -1.0),
        ("video_duration_seconds", float("nan")),
        ("video_duration_seconds", float("inf")),
    ],
)
def test_invalid_clip_configuration_yields_invalid_clip_configuration_before_processing(field_name, invalid_value):
    request = _valid_request(**{field_name: invalid_value})
    with pytest.raises(ClipGenerationError) as exc_info:
        with generate_clips(request) as runner:
            runner.run()
    assert exc_info.value.reason == ClipGenerationFailureReason.INVALID_CLIP_CONFIGURATION


def test_no_event_processed_before_validation_failure():
    request = _valid_request(source_video_path="")
    with pytest.raises(ClipGenerationError):
        with generate_clips(request) as runner:
            runner.run()
            assert False, "run() should have raised before returning"
