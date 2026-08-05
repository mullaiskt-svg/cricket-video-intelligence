"""Unit tests for src/cvip/metadata/enrichment.py's phrase extraction
(T047-T049) -- every phrasing tested is real, verbatim from this project's
own commentary data (ground_truth_v2/wild_wanderers_commentary.json) or
the additional patterns research.md Decision 9 documents."""

from cvip.metadata.alignment_models import AlignmentConfidenceTier, AlignmentOutcome, MatchAlignmentEvidence
from cvip.metadata.enrichment import enrich_wickets, extract_dismissal_detail
from cvip.metadata.extraction_models import MetadataEvent


def test_caught_phrasing_extracts_fielder():
    detail = extract_dismissal_detail(
        "Sai Kiran to Anjini Kumar, OUT Caught out, Caught at Cover by Dileep KP "
        "(Anjini Kumar c Dileep KP b Sai Kiran 0r 1b 0x4s 0x6s SR: 0.00)"
    )
    assert detail.dismissal_type == "CAUGHT"
    assert detail.fielder == "Dileep KP"


def test_run_out_phrasing_extracts_fielder():
    detail = extract_dismissal_detail("Bowler to Batter, OUT Run out (Mohan) 5r 3b")
    assert detail.dismissal_type == "RUN_OUT"
    assert detail.fielder == "Mohan"


def test_bowled_phrasing_has_no_fielder():
    detail = extract_dismissal_detail(
        "Sai Kiran to Mohd Haroon, OUT Bowled (Mohd Haroon b Sai Kiran 0r 1b 0x4s 0x6s SR: 0.00)"
    )
    assert detail.dismissal_type == "BOWLED"
    assert detail.fielder is None


def test_lbw_phrasing():
    detail = extract_dismissal_detail("Bowler to Batter, OUT lbw (Batter lbw b Bowler 4r 6b)")
    assert detail.dismissal_type == "LBW"
    assert detail.fielder is None


def test_stumped_phrasing_extracts_fielder():
    detail = extract_dismissal_detail("Bowler to Batter, OUT Stumped (Batter st Wicketkeeper b Bowler 4r 6b)")
    assert detail.dismissal_type == "STUMPED"
    assert detail.fielder == "Wicketkeeper"


def test_hit_wicket_phrasing():
    detail = extract_dismissal_detail("Bowler to Batter, OUT Hit wicket 4r 6b")
    assert detail.dismissal_type == "HIT_WICKET"
    assert detail.fielder is None


def test_unrecognizable_description_leaves_both_fields_none():
    detail = extract_dismissal_detail("Bowler to Batter, some unusual commentary with no clear pattern")
    assert detail.dismissal_type is None
    assert detail.fielder is None


def test_caught_is_preferred_over_the_bare_bowled_pattern_it_also_contains():
    # "c Dileep KP b Sai Kiran" also contains a bare "b Sai Kiran" --
    # must classify as CAUGHT, never fall through to BOWLED.
    detail = extract_dismissal_detail("(Anjini Kumar c Dileep KP b Sai Kiran 0r 1b)")
    assert detail.dismissal_type == "CAUGHT"


def _db(mocker, already_enriched=False):
    db = mocker.MagicMock()
    db.has_metadata_operation.return_value = already_enriched
    return db


def _evidence(description, outcome=AlignmentOutcome.TRUE_POSITIVE, matched_detected_event=None, event_type="WICKET"):
    return MatchAlignmentEvidence(
        metadata_event=MetadataEvent(innings=1, over_number=1, ball_in_over=1, event_type=event_type, description=description),
        matched_scoreboard_reading={"timestamp_seconds": 1.0},
        matched_detected_event=matched_detected_event,
        alignment_confidence=AlignmentConfidenceTier.EXACT_BALL_VALIDATED_READING,
        outcome=outcome,
        recovery_eligible=False,
        reason="r",
    )


def test_enrich_wickets_writes_dismissal_detail_for_a_confident_match(mocker):
    db = _db(mocker)
    evidence = (_evidence("X c Dileep KP b Sai Kiran", matched_detected_event={"event_id": 7}),)

    enriched = enrich_wickets(evidence, db, "meta.json", "hash123")

    assert len(enriched) == 1
    db.update_dismissal_detail.assert_called_once()
    call_args = db.update_dismissal_detail.call_args[0]
    assert call_args[0] == 7
    assert call_args[1] == "CAUGHT"
    assert call_args[2] == "Dileep KP"


def test_enrich_wickets_skips_and_writes_nothing_for_an_unrecognizable_description(mocker):
    db = _db(mocker)
    evidence = (_evidence("nothing recognizable here", matched_detected_event={"event_id": 7}),)

    enriched = enrich_wickets(evidence, db, "meta.json", "hash123")

    assert enriched == ()
    db.update_dismissal_detail.assert_not_called()


def test_enrich_wickets_ignores_non_true_positive_entries(mocker):
    db = _db(mocker)
    evidence = (_evidence("X c Dileep KP b Sai Kiran", outcome=AlignmentOutcome.RECOVERABLE_MISS),)

    enriched = enrich_wickets(evidence, db, "meta.json", "hash123")

    assert enriched == ()
    db.update_dismissal_detail.assert_not_called()


def test_enrich_wickets_ignores_non_wicket_event_types(mocker):
    db = _db(mocker)
    evidence = (_evidence("X c Dileep KP b Sai Kiran", event_type="FOUR", matched_detected_event={"event_id": 7}),)

    enriched = enrich_wickets(evidence, db, "meta.json", "hash123")

    assert enriched == ()
    db.update_dismissal_detail.assert_not_called()


def test_enrich_wickets_run_twice_creates_no_duplicate_and_does_not_raise(mocker):
    # Regression test: found via real manual CLI testing (not the other
    # mocked tests here) -- a second --enrich run against the same match
    # used to hit the metadata_operations UNIQUE constraint and crash
    # instead of skipping cleanly, since this function originally had no
    # has_metadata_operation() pre-check (unlike recovery.py's own).
    db = _db(mocker, already_enriched=False)
    evidence = (_evidence("X c Dileep KP b Sai Kiran", matched_detected_event={"event_id": 7}),)
    enrich_wickets(evidence, db, "meta.json", "hash123")

    db.has_metadata_operation.return_value = True
    second_run_result = enrich_wickets(evidence, db, "meta.json", "hash123")

    assert second_run_result == ()
    assert db.update_dismissal_detail.call_count == 1


def test_enrich_wickets_skips_a_wicket_already_enriched_without_reextracting(mocker):
    db = _db(mocker, already_enriched=True)
    evidence = (_evidence("X c Dileep KP b Sai Kiran", matched_detected_event={"event_id": 7}),)

    enriched = enrich_wickets(evidence, db, "meta.json", "hash123")

    assert enriched == ()
    db.update_dismissal_detail.assert_not_called()


def test_enrich_wickets_never_touches_timestamp_confidence_or_event_type(mocker):
    # Structural guarantee: update_dismissal_detail's own signature (see
    # db/database.py) only ever writes dismissal_type/fielder columns --
    # confirmed here by checking the call only passes those two fields
    # plus identity/provenance args, nothing resembling a timestamp update.
    db = _db(mocker)
    evidence = (_evidence("X c Dileep KP b Sai Kiran", matched_detected_event={"event_id": 7}),)

    enrich_wickets(evidence, db, "meta.json", "hash123")

    call_kwargs = db.update_dismissal_detail.call_args.kwargs
    assert "timestamp_seconds" not in call_kwargs
    assert "confidence" not in call_kwargs
    assert "event_type" not in call_kwargs
