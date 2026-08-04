"""Unit tests for Event Database's fail-fast reliability (US4): corrupted
file, schema-version mismatch, write against a COMPLETE match, and
diagnostics emission on every failure path. See
specs/010-event-database/spec.md User Story 4.
"""

import sqlite3

import pytest

from cvip.db import schema
from cvip.db.database import open_database
from cvip.db.errors import EventDatabaseError, EventDatabaseFailureReason
from cvip.db.models import EventQueryFilter, MatchMetadata


def _begin(db, file_hash="abc123"):
    db.begin_analysis(MatchMetadata(file_hash=file_hash, source_video_path="match.mp4"))


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


class _Reading:
    timestamp_seconds = 1.0
    innings = 1
    over_number = 1
    ball_in_over = 1
    runs = 10
    wickets = 0
    batter = None
    non_striker = None
    bowler = None
    run_rate = None
    raw_text = ""
    ocr_confidence = 0.9
    parse_confidence = 1.0


class _Replay:
    replay_id = 1
    start_seconds = 1.0
    end_seconds = 2.0
    confidence = 0.8


def test_opening_a_non_sqlite_file_raises_corrupted_database_file(tmp_path):
    db_path = tmp_path / "match.sqlite"
    db_path.write_bytes(b"this is not a sqlite database file at all, just noise")

    with pytest.raises(EventDatabaseError) as exc_info:
        with open_database(db_path):
            pass

    assert exc_info.value.reason == EventDatabaseFailureReason.CORRUPTED_DATABASE_FILE


def test_opening_a_structurally_corrupted_but_readable_file_raises_corrupted_database_file(tmp_path):
    """Distinct from the totally-non-SQLite case above: a file SQLite can
    still open and connect to, but whose PRAGMA integrity_check reports a
    structural inconsistency via its *return value* rather than raising --
    e.g. a damaged data page deep in the file. Constructed by flipping bytes
    well past the header/schema region of a real database with enough rows
    to have real data pages to damage."""
    db_path = tmp_path / "match.sqlite"
    with open_database(db_path) as db:
        _begin(db)
        db.persist_scoreboard_readings([_Reading() for _ in range(500)])

    raw_bytes = bytearray(db_path.read_bytes())
    corrupt_start = len(raw_bytes) - 200
    for i in range(corrupt_start, corrupt_start + 50):
        raw_bytes[i] ^= 0xFF
    db_path.write_bytes(raw_bytes)

    with pytest.raises(EventDatabaseError) as exc_info:
        with open_database(db_path):
            pass

    assert exc_info.value.reason == EventDatabaseFailureReason.CORRUPTED_DATABASE_FILE


def test_opening_a_file_with_mismatched_schema_version_raises(tmp_path):
    db_path = tmp_path / "match.sqlite"
    with open_database(db_path):
        pass  # creates the schema at the current SCHEMA_VERSION

    conn = sqlite3.connect(str(db_path))
    conn.execute(f"PRAGMA user_version = {schema.SCHEMA_VERSION + 1}")
    conn.commit()
    conn.close()

    with pytest.raises(EventDatabaseError) as exc_info:
        with open_database(db_path):
            pass

    assert exc_info.value.reason == EventDatabaseFailureReason.SCHEMA_VERSION_MISMATCH


@pytest.mark.parametrize(
    "operation",
    [
        lambda db: db.persist_events([_Event()]),
        lambda db: db.persist_replays([_Replay()]),
        lambda db: db.persist_scoreboard_readings([_Reading()]),
    ],
)
def test_write_against_a_completed_match_is_rejected(tmp_path, operation):
    with open_database(tmp_path / "match.sqlite") as db:
        _begin(db)
        db.complete_analysis()

        with pytest.raises(EventDatabaseError) as exc_info:
            operation(db)

        assert exc_info.value.reason == EventDatabaseFailureReason.WRITE_AGAINST_COMPLETED_MATCH
        # No row was written by the rejected attempt.
        assert db.query_events(EventQueryFilter()) == ()


def test_update_clip_window_succeeds_against_a_completed_match(tmp_path):
    """PR #14 review finding: update_clip_window() represents `cvip
    generate`-time bookkeeping, which only ever runs *after* `cvip analyze`
    has already marked the match COMPLETE -- unlike the three batch-persist
    methods above, it must NOT be blocked by the WRITE_AGAINST_COMPLETED_MATCH
    gate, or the platform's normal analyze-once-generate-later workflow
    would be permanently broken."""
    with open_database(tmp_path / "match.sqlite") as db:
        _begin(db)
        db.persist_events([_Event()])
        db.complete_analysis()
        event_key = db.query_events(EventQueryFilter())[0].event_key

        db.update_clip_window(event_key, 5.0, 15.0)  # must not raise

        updated = db.query_events(EventQueryFilter())[0]
        assert (updated.clip_start_seconds, updated.clip_end_seconds) == (5.0, 15.0)


def test_a_failed_batch_write_rolls_back_and_is_not_persisted_by_a_later_commit(tmp_path):
    """PR #14 review finding: sqlite3 leaves an implicit transaction open
    across a failed executemany() rather than discarding it -- without an
    explicit rollback, a later, unrelated commit on the same connection
    (e.g. fail_analysis()) would silently persist whatever partial rows the
    failed batch had already written, violating the "one batch, all-or-
    nothing" persistence contract."""

    class _BadEvent(_Event):
        event_type = "NOT_A_REAL_EVENT_TYPE"  # violates the events.event_type CHECK constraint

    with open_database(tmp_path / "match.sqlite") as db:
        _begin(db)

        with pytest.raises(Exception):
            db.persist_events([_Event(), _BadEvent()])  # first row would insert, second fails

        db.fail_analysis()  # a later, unrelated commit on the same connection

    with open_database(tmp_path / "match.sqlite") as db:
        assert db.query_events(EventQueryFilter()) == ()


def test_reset_for_forced_reanalysis_bypasses_the_write_gate_by_design(tmp_path):
    with open_database(tmp_path / "match.sqlite") as db:
        _begin(db)
        db.persist_events([_Event()])
        db.complete_analysis()

        db.reset_for_forced_reanalysis("abc123")  # must not raise

        from cvip.db.models import AnalysisStatusCondition

        assert db.check_analysis_status("abc123") == AnalysisStatusCondition.IN_PROGRESS


def test_every_failure_path_emits_exactly_one_diagnostics_record(tmp_path, mocker):
    emit_spy = mocker.patch("cvip.db.database.emit_diagnostics")

    with open_database(tmp_path / "match.sqlite") as db:
        _begin(db)
        db.complete_analysis()
        emit_spy.reset_mock()

        with pytest.raises(EventDatabaseError):
            db.persist_events([_Event()])

    assert emit_spy.call_count == 1
    diagnostics = emit_spy.call_args[0][0]
    assert diagnostics.failure_reason == EventDatabaseFailureReason.WRITE_AGAINST_COMPLETED_MATCH.value
