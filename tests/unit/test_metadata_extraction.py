"""Unit tests for src/cvip/metadata/extraction.py and
providers/ball_by_ball_json.py (T021, spec.md FR-009)."""

import json

import pytest

from cvip.metadata.errors import MetadataValidationError, MetadataValidationFailureReason
from cvip.metadata.extraction import extract_ground_truth
from cvip.metadata.providers.ball_by_ball_json import BallByBallJsonProvider


def _write_metadata(tmp_path, innings_payload):
    path = tmp_path / "metadata.json"
    path.write_text(json.dumps({"innings": innings_payload}), encoding="utf-8")
    return str(path)


def test_classifies_six_four_wicket_and_skips_non_scoring_deliveries(tmp_path):
    path = _write_metadata(
        tmp_path,
        [
            {
                "innings": 1,
                "commentary": [
                    {"ball": "19.5", "description": "Sai Kiran to Mohd Haroon, OUT Bowled (Mohd Haroon b Sai Kiran)"},
                    {"ball": "19.2", "description": "Sai Kiran to Mullai Selvan K T, FOUR, to Deep mid wicket"},
                    {"ball": "18.4", "description": "Bowler to Batter, SIX, over long-on"},
                    {"ball": "18.3", "description": "Bowler to Batter, 1 run"},
                ],
            }
        ],
    )

    events = extract_ground_truth(path)

    assert len(events) == 3
    types_by_ball = {(e.over_number, e.ball_in_over): e.event_type for e in events}
    assert types_by_ball[(19, 5)] == "WICKET"
    assert types_by_ball[(19, 2)] == "FOUR"
    assert types_by_ball[(18, 4)] == "SIX"
    assert (18, 3) not in types_by_ball


def test_events_carry_the_correct_innings_and_verbatim_description(tmp_path):
    path = _write_metadata(
        tmp_path,
        [
            {"innings": 1, "commentary": [{"ball": "1.1", "description": "X, FOUR, cover drive"}]},
            {"innings": 2, "commentary": [{"ball": "2.3", "description": "Y, SIX, over midwicket"}]},
        ],
    )

    events = extract_ground_truth(path)

    innings1 = next(e for e in events if e.over_number == 1)
    innings2 = next(e for e in events if e.over_number == 2)
    assert innings1.innings == 1
    assert innings1.description == "X, FOUR, cover drive"
    assert innings2.innings == 2


def test_single_innings_match_is_accepted(tmp_path):
    path = _write_metadata(tmp_path, [{"innings": 1, "commentary": [{"ball": "5.1", "description": "X, FOUR"}]}])

    events = extract_ground_truth(path)

    assert len(events) == 1
    assert events[0].innings == 1


def test_missing_file_raises_metadata_file_unreadable(tmp_path):
    with pytest.raises(MetadataValidationError) as exc_info:
        extract_ground_truth(str(tmp_path / "does_not_exist.json"))
    assert exc_info.value.reason == MetadataValidationFailureReason.METADATA_FILE_UNREADABLE


def test_malformed_json_raises_metadata_file_unreadable(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("not valid json {{{", encoding="utf-8")

    with pytest.raises(MetadataValidationError) as exc_info:
        extract_ground_truth(str(path))
    assert exc_info.value.reason == MetadataValidationFailureReason.METADATA_FILE_UNREADABLE


def test_json_missing_expected_shape_raises_metadata_file_unreadable(tmp_path):
    path = tmp_path / "wrong_shape.json"
    path.write_text(json.dumps({"not_innings": []}), encoding="utf-8")

    with pytest.raises(MetadataValidationError) as exc_info:
        extract_ground_truth(str(path))
    assert exc_info.value.reason == MetadataValidationFailureReason.METADATA_FILE_UNREADABLE


def test_extract_ground_truth_delegates_to_the_default_provider(tmp_path):
    path = _write_metadata(tmp_path, [{"innings": 1, "commentary": [{"ball": "1.1", "description": "X, FOUR"}]}])

    default_result = extract_ground_truth(path)
    explicit_result = extract_ground_truth(path, provider=BallByBallJsonProvider())

    assert default_result == explicit_result
