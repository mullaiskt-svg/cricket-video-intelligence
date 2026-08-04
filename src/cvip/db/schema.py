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
SCHEMA_VERSION = 1

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
"""


def create_schema(conn: sqlite3.Connection) -> None:
    """Create every table/index (fresh database only) and stamp
    `PRAGMA user_version` with this module's `SCHEMA_VERSION`."""
    conn.executescript(_CREATE_TABLES_SQL)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    conn.commit()
