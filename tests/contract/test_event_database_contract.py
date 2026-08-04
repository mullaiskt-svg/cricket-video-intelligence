"""Contract test for Event Database: asserts open_database() matches
specs/010-event-database/contracts/event_database_contract.md's shape.
See tests/unit/test_event_database_{lifecycle,persistence,query,failures}.py
for per-capability behavioral tests.
"""

from cvip.db.database import EventDatabase, open_database


def test_open_database_returns_a_working_context_manager_over_a_fresh_path(tmp_path):
    db_path = tmp_path / "match.sqlite"

    with open_database(db_path) as db:
        assert isinstance(db, EventDatabase)
        # A fresh database is immediately usable without error.
        assert db.check_analysis_status("nonexistent") is not None

    assert db_path.exists()


def test_open_database_on_an_existing_valid_database_reopens_cleanly(tmp_path):
    db_path = tmp_path / "match.sqlite"
    with open_database(db_path):
        pass  # creates the schema

    with open_database(db_path) as db:
        assert isinstance(db, EventDatabase)
