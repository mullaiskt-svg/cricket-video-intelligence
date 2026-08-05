"""Event Database schema: DDL verbatim from specs/technical_plan.md's
Database Schema section (the authoritative table/column definitions this
module implements, not redesigns) plus this module's own schema-version
constant.

Schema version is stored via SQLite's own `PRAGMA user_version` (research.md
Decision 3), not a dedicated table -- a zero-cost check that works even
against a database whose table schema is otherwise unreadable.
"""

import sqlite3

#: Bumped whenever the DDL below changes in a way an already-written
#: database file wouldn't be compatible with. No migration framework exists
#: yet (out of MVP scope) -- a mismatch is reported (SCHEMA_VERSION_MISMATCH),
#: never silently worked around.
#:
#: v2 (specs/013-match-metadata-validation/data-model.md): additive only --
#: events.source/dismissal_type/fielder columns and the new
#: metadata_operations table. No existing column redefined, so a v1
#: database remains readable; it is simply not writable by this feature
#: until re-analyzed (cvip analyze --force) into a fresh v2 database.
SCHEMA_VERSION = 2

_CREATE_TABLES_SQL = """
CREATE TABLE matches (
  match_id TEXT PRIMARY KEY,
  source_video_path TEXT NOT NULL,
  file_hash TEXT NOT NULL,
  duration_seconds REAL,
  resolution_width INTEGER,
  resolution_height INTEGER,
  frame_rate REAL,
  codec TEXT,
  analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  status TEXT CHECK (status IN ('IN_PROGRESS', 'COMPLETE', 'FAILED')) DEFAULT 'IN_PROGRESS'
);

CREATE UNIQUE INDEX idx_matches_file_hash ON matches (file_hash);

CREATE TABLE events (
  event_id INTEGER PRIMARY KEY,
  timestamp_seconds REAL,
  innings INTEGER,
  over_number INTEGER,
  ball_in_over INTEGER,
  event_type TEXT CHECK (event_type IN ('FOUR', 'SIX', 'WICKET', 'TEAM_MILESTONE')),
  player TEXT,
  team TEXT,
  confidence REAL,
  importance INTEGER,
  milestone_value INTEGER,
  clip_start_seconds REAL,
  clip_end_seconds REAL,
  is_replay BOOLEAN,
  source TEXT CHECK (source IN ('OCR', 'METADATA')) NOT NULL DEFAULT 'OCR',
  dismissal_type TEXT CHECK (
    dismissal_type IN ('BOWLED', 'CAUGHT', 'LBW', 'RUN_OUT', 'STUMPED', 'HIT_WICKET')
    OR dismissal_type IS NULL
  ),
  fielder TEXT,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_events_event_type ON events (event_type);
CREATE INDEX idx_events_player ON events (player);
CREATE INDEX idx_events_team ON events (team);
CREATE INDEX idx_events_over ON events (over_number, ball_in_over);

CREATE TABLE replays (
  replay_id INTEGER PRIMARY KEY,
  start_seconds REAL,
  end_seconds REAL,
  confidence REAL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_replays_time_range ON replays (start_seconds, end_seconds);

CREATE TABLE scoreboard_readings (
  reading_id INTEGER PRIMARY KEY,
  timestamp_seconds REAL,
  innings INTEGER,
  over_number INTEGER,
  ball_in_over INTEGER,
  runs INTEGER,
  wickets INTEGER,
  batter TEXT,
  non_striker TEXT,
  bowler TEXT,
  run_rate REAL,
  raw_text TEXT,
  ocr_confidence REAL,
  parse_confidence REAL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_scoreboard_readings_timestamp ON scoreboard_readings (timestamp_seconds);

-- specs/013-match-metadata-validation/data-model.md: an append-only audit
-- trail for every Recovery/Enrichment operation this feature performs --
-- written only by INSERT (never UPDATE/DELETE), so "what was added/changed,
-- when, from which metadata source" is always answerable from within the
-- database itself, with no dependency on external logs (research.md
-- Decision 5). The unique index is defense-in-depth for idempotency
-- (FR-012) -- the real check is an explicit pre-write query
-- (research.md Decision 6), not reliance on a constraint-violation catch.
CREATE TABLE metadata_operations (
  operation_id INTEGER PRIMARY KEY,
  operation_type TEXT CHECK (operation_type IN ('RECOVERY', 'ENRICHMENT')),
  metadata_file_path TEXT NOT NULL,
  metadata_file_hash TEXT NOT NULL,
  metadata_event_identifier TEXT NOT NULL,
  affected_event_id INTEGER,
  recovery_version TEXT NOT NULL,
  performed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  detail TEXT
);

CREATE UNIQUE INDEX idx_metadata_operations_dedup
  ON metadata_operations (metadata_file_hash, metadata_event_identifier, operation_type);

CREATE INDEX idx_metadata_operations_event ON metadata_operations (affected_event_id);
"""


def create_schema(conn: sqlite3.Connection) -> None:
    """Create every table/index (fresh database only) and stamp
    `PRAGMA user_version` with this module's `SCHEMA_VERSION`."""
    conn.executescript(_CREATE_TABLES_SQL)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()
