"""Unit tests for Event Database's single-pass status lifecycle (US1):
check_analysis_status(), begin_analysis(), complete_analysis(),
fail_analysis(), reset_for_forced_reanalysis(). See
specs/010-event-database/spec.md User Story 1.
"""

from cvip.db.database import open_database
from cvip.db.errors import EventDatabaseError, EventDatabaseFailureReason
from cvip.db.models import AnalysisStatusCondition, MatchMetadata


def _metadata(file_hash="abc123", source_video_path="match.mp4"):
    return MatchMetadata(file_hash=file_hash, source_video_path=source_video_path)


def test_check_analysis_status_reports_not_analyzed_for_unknown_file_hash(tmp_path):
    with open_database(tmp_path / "match.sqlite") as db:
        assert db.check_analysis_status("unknown") == AnalysisStatusCondition.NOT_ANALYZED


def test_begin_then_complete_analysis_reports_complete(tmp_path):
    with open_database(tmp_path / "match.sqlite") as db:
        db.begin_analysis(_metadata())
        db.complete_analysis()

        assert db.check_analysis_status("abc123") == AnalysisStatusCondition.COMPLETE


def test_begin_analysis_alone_reports_in_progress_distinct_from_complete(tmp_path):
    with open_database(tmp_path / "match.sqlite") as db:
        db.begin_analysis(_metadata())

        assert db.check_analysis_status("abc123") == AnalysisStatusCondition.IN_PROGRESS


def test_fail_analysis_reports_not_analyzed_not_complete(tmp_path):
    with open_database(tmp_path / "match.sqlite") as db:
        db.begin_analysis(_metadata())
        db.fail_analysis()

        assert db.check_analysis_status("abc123") == AnalysisStatusCondition.NOT_ANALYZED


def test_reset_for_forced_reanalysis_removes_prior_data_and_resets_status(tmp_path):
    from cvip.db.models import EventQueryFilter

    with open_database(tmp_path / "match.sqlite") as db:
        db.begin_analysis(_metadata())

        class _Event:
            timestamp_seconds = 10.0
            innings = 1
            over_number = 1
            ball_in_over = 1
            event_type = "FOUR"
            player = None
            team = None
            confidence = 0.9
            importance = 60
            milestone_value = None
            is_replay = False

        db.persist_events([_Event()])
        db.complete_analysis()

        db.reset_for_forced_reanalysis("abc123")

        assert db.query_events(EventQueryFilter()) == ()
        assert db.check_analysis_status("abc123") == AnalysisStatusCondition.IN_PROGRESS


def test_reset_for_forced_reanalysis_with_no_prior_row_is_not_an_error(tmp_path):
    with open_database(tmp_path / "match.sqlite") as db:
        db.reset_for_forced_reanalysis("never-seen-hash")  # must not raise

        assert db.check_analysis_status("never-seen-hash") == AnalysisStatusCondition.NOT_ANALYZED


def test_begin_analysis_reuses_existing_in_progress_row_silently(tmp_path):
    with open_database(tmp_path / "match.sqlite") as db:
        db.begin_analysis(_metadata())
        db.begin_analysis(_metadata())  # must not raise -- reused, not rejected

        assert db.check_analysis_status("abc123") == AnalysisStatusCondition.IN_PROGRESS


def test_begin_analysis_reuses_existing_failed_row_silently(tmp_path):
    with open_database(tmp_path / "match.sqlite") as db:
        db.begin_analysis(_metadata())
        db.fail_analysis()

        db.begin_analysis(_metadata())  # must not raise

        assert db.check_analysis_status("abc123") == AnalysisStatusCondition.IN_PROGRESS


def test_begin_analysis_rejects_existing_complete_row(tmp_path):
    with open_database(tmp_path / "match.sqlite") as db:
        db.begin_analysis(_metadata())
        db.complete_analysis()

        try:
            db.begin_analysis(_metadata())
            assert False, "expected EventDatabaseError"
        except EventDatabaseError as exc:
            assert exc.reason == EventDatabaseFailureReason.WRITE_AGAINST_COMPLETED_MATCH
