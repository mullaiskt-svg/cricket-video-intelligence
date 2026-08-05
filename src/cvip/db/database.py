"""Event Database: open_database() and EventDatabase.

See specs/010-event-database/contracts/event_database_contract.md for the
full contract this module implements.

Unlike every prior module, this is not a `request in, result out` Runner
(research.md Decision 1) -- it's a stateful, multi-method object wrapping
one open SQLite connection, used across a whole `analyze`/`generate`
invocation's lifetime. One `.sqlite` file always holds exactly one match's
data (specs/technical_plan.md's Database Schema), so every method after
`begin_analysis()`/connection-open implicitly targets "the" match this
connection represents -- only the single-pass lifecycle methods take
`file_hash` explicitly (research.md Decision 2).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Tuple

from cvip.common.diagnostics import DiagnosticsTracker, emit_diagnostics
from cvip.db import schema
from cvip.db.errors import EventDatabaseError, EventDatabaseFailureReason
from cvip.db.models import (
    AnalysisStatusCondition,
    EventLike,
    EventQueryFilter,
    MatchMetadata,
    MatchSummary,
    MatchTimelineExport,
    QueriedEvent,
    RecoveredEventLike,
    ReplaySegmentLike,
    ScoreboardReadingLike,
)

MODULE_NAME = "db.database"

_STATUS_TO_CONDITION = {
    "COMPLETE": AnalysisStatusCondition.COMPLETE,
    "IN_PROGRESS": AnalysisStatusCondition.IN_PROGRESS,
    # A FAILED prior run is not "already analyzed" in any sense that should
    # block a fresh begin_analysis() (data-model.md AnalysisStatusCondition
    # note) -- reported the same as no row at all.
    "FAILED": AnalysisStatusCondition.NOT_ANALYZED,
}


def open_database(path: Path) -> "EventDatabase":
    """Return an EventDatabase for the given, already-resolved path (this
    module never decides the path itself -- FR-002). Always use as a
    context manager:

        with open_database(path) as db:
            ...
    """
    return EventDatabase(path)


class EventDatabase:
    """Wraps one open SQLite connection for one match's database file. Not
    constructed directly -- use `open_database()`."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._conn: Optional[sqlite3.Connection] = None
        self._current_file_hash: Optional[str] = None
        self._current_status: Optional[str] = None

    def __enter__(self) -> "EventDatabase":
        self._connect_and_validate()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # -- internal: connection lifecycle -------------------------------------

    def _connect_and_validate(self) -> None:
        existed_before = self._path.exists()
        conn = sqlite3.connect(str(self._path))
        conn.row_factory = sqlite3.Row
        self._conn = conn

        if not existed_before:
            schema.create_schema(conn)
            self._run_operation(
                "open_database",
                f"path={self._path} existed=False",
                lambda: (f"schema_created=True schema_version={schema.SCHEMA_VERSION}", None),
            )
            return

        try:
            integrity_row = conn.execute("PRAGMA integrity_check").fetchone()
        except sqlite3.DatabaseError as exc:
            # A file that isn't SQLite at all (or is severely corrupted) can
            # raise directly here rather than returning a non-'ok' row --
            # e.g. "file is not a database".
            self._fail_on_open(
                EventDatabaseFailureReason.CORRUPTED_DATABASE_FILE,
                f"path={self._path} failed PRAGMA integrity_check: {exc}",
            )
        if integrity_row is None or integrity_row[0] != "ok":
            self._fail_on_open(
                EventDatabaseFailureReason.CORRUPTED_DATABASE_FILE,
                f"path={self._path} failed PRAGMA integrity_check: {integrity_row[0] if integrity_row else 'no result'}",
            )

        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if version != schema.SCHEMA_VERSION:
            self._fail_on_open(
                EventDatabaseFailureReason.SCHEMA_VERSION_MISMATCH,
                f"path={self._path} has user_version={version}, expected {schema.SCHEMA_VERSION}",
            )

        # One database file always holds exactly one match -- opportunistically
        # load its current identity/status now, so the WRITE_AGAINST_COMPLETED_MATCH
        # gate (research.md Decision 5) is correct even for a connection that
        # never calls begin_analysis() itself (a read-only `generate` process
        # reopening an already-COMPLETE database).
        match_row = conn.execute("SELECT file_hash, status FROM matches").fetchone()
        if match_row is not None:
            self._current_file_hash = match_row["file_hash"]
            self._current_status = match_row["status"]

        self._run_operation(
            "open_database",
            f"path={self._path} existed=True",
            lambda: (f"schema_created=False schema_version={schema.SCHEMA_VERSION}", None),
        )

    def _fail_on_open(self, reason: EventDatabaseFailureReason, detail: str) -> None:
        tracker = DiagnosticsTracker()
        tracker.__enter__()
        tracker.__exit__(None, None, None)
        diagnostics = tracker.build(
            module_name=MODULE_NAME,
            input_summary=f"operation=open_database path={self._path}",
            output_summary=f"schema_version={schema.SCHEMA_VERSION}",
            failure_reason=reason.value,
        )
        emit_diagnostics(diagnostics)
        if self._conn is not None:
            self._conn.close()
            self._conn = None
        raise EventDatabaseError(reason, detail)

    # -- internal: shared diagnostics/write-gate plumbing --------------------

    def _run_operation(
        self,
        operation: str,
        input_summary: str,
        work_fn: Callable[[], Tuple[str, None]],
    ) -> None:
        """Runs `work_fn()` (returning an `output_summary` fragment) inside a
        DiagnosticsTracker, emitting exactly one diagnostics record for this
        operation regardless of outcome (FR-020).

        Any exception rolls back the connection's current transaction
        before re-raising (PR #14 review finding): `sqlite3` leaves an
        implicit transaction open across a failed `executemany()`/`execute()`
        call rather than discarding it, so without an explicit rollback
        here, any *later*, unrelated `commit()` on this same connection
        (e.g. a subsequent `fail_analysis()` call) would silently persist
        whatever partial rows the failed operation had already written --
        violating the "one batch, all-or-nothing" persistence contract this
        module documents."""
        tracker = DiagnosticsTracker()
        tracker.__enter__()
        try:
            output_summary, _ = work_fn()
        except EventDatabaseError as exc:
            self._conn.rollback()
            tracker.__exit__(None, None, None)
            diagnostics = tracker.build(
                module_name=MODULE_NAME,
                input_summary=f"operation={operation} {input_summary}",
                output_summary=f"schema_version={schema.SCHEMA_VERSION}",
                failure_reason=exc.reason.value,
            )
            emit_diagnostics(diagnostics)
            raise
        except Exception as exc:
            # An unexpected failure from sqlite3 itself (e.g. a CHECK
            # constraint violation mid-batch) -- not one of this module's
            # own EventDatabaseFailureReason values, but the same
            # rollback/diagnostics discipline still applies.
            self._conn.rollback()
            tracker.__exit__(None, None, None)
            diagnostics = tracker.build(
                module_name=MODULE_NAME,
                input_summary=f"operation={operation} {input_summary}",
                output_summary=f"schema_version={schema.SCHEMA_VERSION}",
                failure_reason=type(exc).__name__,
            )
            emit_diagnostics(diagnostics)
            raise
        tracker.__exit__(None, None, None)
        diagnostics = tracker.build(
            module_name=MODULE_NAME,
            input_summary=f"operation={operation} {input_summary}",
            output_summary=f"{output_summary} schema_version={schema.SCHEMA_VERSION}",
        )
        emit_diagnostics(diagnostics)

    def _check_write_allowed(self, operation: str) -> None:
        if self._current_status == "COMPLETE":
            raise EventDatabaseError(
                EventDatabaseFailureReason.WRITE_AGAINST_COMPLETED_MATCH,
                f"{operation} attempted against a COMPLETE match (file_hash={self._current_file_hash})",
            )

    # -- Capability 1: single-pass status (US1) ------------------------------

    def check_analysis_status(self, file_hash: str) -> AnalysisStatusCondition:
        """FR-003, FR-004: NOT_ANALYZED/IN_PROGRESS/COMPLETE for this
        file_hash. Pure read -- no diagnostics record (FR-020 exempts
        read-only queries)."""
        row = self._conn.execute(
            "SELECT status FROM matches WHERE file_hash = ?", (file_hash,)
        ).fetchone()
        if row is None:
            return AnalysisStatusCondition.NOT_ANALYZED
        return _STATUS_TO_CONDITION.get(row["status"], AnalysisStatusCondition.NOT_ANALYZED)

    def begin_analysis(self, metadata: MatchMetadata) -> None:
        """FR-005: insert (or reuse an existing non-COMPLETE) `matches` row
        as IN_PROGRESS. Rejects an existing COMPLETE row with
        WRITE_AGAINST_COMPLETED_MATCH."""

        def work() -> Tuple[str, None]:
            existing = self._conn.execute(
                "SELECT status FROM matches WHERE file_hash = ?", (metadata.file_hash,)
            ).fetchone()
            if existing is not None and existing["status"] == "COMPLETE":
                raise EventDatabaseError(
                    EventDatabaseFailureReason.WRITE_AGAINST_COMPLETED_MATCH,
                    f"begin_analysis called for file_hash={metadata.file_hash}, which is already COMPLETE",
                )
            match_id = metadata.file_hash[:12]
            if existing is None:
                self._conn.execute(
                    "INSERT INTO matches (match_id, source_video_path, file_hash, duration_seconds, "
                    "resolution_width, resolution_height, frame_rate, codec, status) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'IN_PROGRESS')",
                    (
                        match_id,
                        metadata.source_video_path,
                        metadata.file_hash,
                        metadata.duration_seconds,
                        metadata.resolution_width,
                        metadata.resolution_height,
                        metadata.frame_rate,
                        metadata.codec,
                    ),
                )
            else:
                self._conn.execute(
                    "UPDATE matches SET status = 'IN_PROGRESS' WHERE file_hash = ?",
                    (metadata.file_hash,),
                )
            self._conn.commit()
            self._current_file_hash = metadata.file_hash
            self._current_status = "IN_PROGRESS"
            return "status=IN_PROGRESS", None

        self._run_operation("begin_analysis", f"file_hash={metadata.file_hash}", work)

    def complete_analysis(self) -> None:
        """FR-006: mark the current match COMPLETE."""
        self._set_status("COMPLETE")

    def fail_analysis(self) -> None:
        """FR-006: mark the current match FAILED."""
        self._set_status("FAILED")

    def _set_status(self, new_status: str) -> None:
        def work() -> Tuple[str, None]:
            self._check_write_allowed(f"set_status({new_status})")
            self._conn.execute(
                "UPDATE matches SET status = ? WHERE file_hash = ?",
                (new_status, self._current_file_hash),
            )
            self._conn.commit()
            self._current_status = new_status
            return f"status={new_status}", None

        self._run_operation(
            f"set_status_{new_status.lower()}", f"file_hash={self._current_file_hash}", work
        )

    def reset_for_forced_reanalysis(self, file_hash: str) -> None:
        """FR-007: unconditionally wipe scoreboard_readings/replays/events
        (one database file = one match) and reset the matches row to
        IN_PROGRESS. A file_hash with no prior row is a no-op besides the
        (already-empty) deletes -- treated as a fresh first-time analysis,
        not an error (Edge Cases). The one write path that bypasses the
        WRITE_AGAINST_COMPLETED_MATCH gate by design (research.md
        Decision 5)."""

        def work() -> Tuple[str, None]:
            self._conn.execute("DELETE FROM scoreboard_readings")
            self._conn.execute("DELETE FROM replays")
            self._conn.execute("DELETE FROM events")
            cursor = self._conn.execute(
                "UPDATE matches SET status = 'IN_PROGRESS' WHERE file_hash = ?", (file_hash,)
            )
            self._conn.commit()
            reset_existing_row = cursor.rowcount > 0
            if reset_existing_row:
                self._current_file_hash = file_hash
                self._current_status = "IN_PROGRESS"
            return (
                f"readings_removed=all replays_removed=all events_removed=all "
                f"matches_row_reset={reset_existing_row}",
                None,
            )

        self._run_operation("reset_for_forced_reanalysis", f"file_hash={file_hash}", work)

    # -- Capability 2: persistence (US2) -------------------------------------

    def persist_scoreboard_readings(self, readings: Sequence[ScoreboardReadingLike]) -> None:
        """FR-008: batched insert preserving every field and order. An
        empty sequence is a valid no-op (Edge Cases)."""

        def work() -> Tuple[str, None]:
            self._check_write_allowed("persist_scoreboard_readings")
            rows = [
                (
                    r.timestamp_seconds,
                    r.innings,
                    r.over_number,
                    r.ball_in_over,
                    r.runs,
                    r.wickets,
                    r.batter,
                    r.non_striker,
                    r.bowler,
                    r.run_rate,
                    r.raw_text,
                    r.ocr_confidence,
                    r.parse_confidence,
                )
                for r in readings
            ]
            if rows:
                self._conn.executemany(
                    "INSERT INTO scoreboard_readings (timestamp_seconds, innings, over_number, "
                    "ball_in_over, runs, wickets, batter, non_striker, bowler, run_rate, raw_text, "
                    "ocr_confidence, parse_confidence) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    rows,
                )
                self._conn.commit()
            return f"rows_written={len(rows)}", None

        self._run_operation(
            "persist_scoreboard_readings", f"batch_size={len(readings)}", work
        )

    def persist_replays(self, segments: Sequence[ReplaySegmentLike]) -> None:
        """FR-009: batched insert with each segment's caller-supplied
        `replay_id` as the literal primary key (not autoincrement)."""

        def work() -> Tuple[str, None]:
            self._check_write_allowed("persist_replays")
            rows = [(s.replay_id, s.start_seconds, s.end_seconds, s.confidence) for s in segments]
            if rows:
                self._conn.executemany(
                    "INSERT INTO replays (replay_id, start_seconds, end_seconds, confidence) "
                    "VALUES (?,?,?,?)",
                    rows,
                )
                self._conn.commit()
            return f"rows_written={len(rows)}", None

        self._run_operation("persist_replays", f"batch_size={len(segments)}", work)

    def persist_events(self, events: Sequence[EventLike]) -> None:
        """FR-010: batched insert; `clip_start_seconds`/`clip_end_seconds`
        always NULL on insert, populated later only via
        `update_clip_window()`."""

        def work() -> Tuple[str, None]:
            self._check_write_allowed("persist_events")
            rows = [
                (
                    e.timestamp_seconds,
                    e.innings,
                    e.over_number,
                    e.ball_in_over,
                    e.event_type,
                    e.player,
                    e.team,
                    e.confidence,
                    e.importance,
                    e.milestone_value,
                    e.is_replay,
                )
                for e in events
            ]
            if rows:
                self._conn.executemany(
                    "INSERT INTO events (timestamp_seconds, innings, over_number, ball_in_over, "
                    "event_type, player, team, confidence, importance, milestone_value, is_replay) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    rows,
                )
                self._conn.commit()
            return f"rows_written={len(rows)}", None

        self._run_operation("persist_events", f"batch_size={len(events)}", work)

    def update_clip_window(
        self, event_key: str, clip_start_seconds: float, clip_end_seconds: float
    ) -> None:
        """FR-011: updates only this event's clip_start_seconds/
        clip_end_seconds; every other column untouched. Repeated calls for
        the same event each succeed, reflecting only the most recent call
        (Edge Cases; Assumptions -- best-effort tracking).

        Deliberately NOT gated by WRITE_AGAINST_COMPLETED_MATCH (PR #14
        review finding, correcting this module's own original contract
        text): unlike persist_scoreboard_readings/persist_replays/
        persist_events (which represent analysis results and must be
        blocked once a match is COMPLETE, to prevent silently re-running
        analysis without an explicit reset), this call represents
        `cvip generate`-time bookkeeping -- and `generate` only ever runs
        *after* `cvip analyze` has already marked the match COMPLETE. Gating
        this the same way as the batch-persist methods would make the
        documented post-analysis clip-window update path permanently
        unusable for the platform's normal analyze-once-generate-later
        workflow."""

        def work() -> Tuple[str, None]:
            self._conn.execute(
                "UPDATE events SET clip_start_seconds = ?, clip_end_seconds = ? WHERE event_id = ?",
                (clip_start_seconds, clip_end_seconds, int(event_key)),
            )
            self._conn.commit()
            return (
                f"clip_start_seconds={clip_start_seconds} clip_end_seconds={clip_end_seconds}",
                None,
            )

        self._run_operation("update_clip_window", f"event_key={event_key}", work)

    # -- Capability 3: query and inspection (US3) ----------------------------

    def query_events(self, filter: EventQueryFilter) -> Tuple[QueriedEvent, ...]:
        """FR-012, FR-013: every event matching all supplied filter
        criteria, ordered by ascending timestamp_seconds. Pure read -- no
        diagnostics record. `QueriedEvent.event_key` is `str(event_id)`
        (research.md Decision 10), structurally compatible with Clip
        Generator's `ClipGenerationRequest.events` input as-is."""
        where_clause, params = _build_event_where_clause(filter)
        sql = f"SELECT * FROM events {where_clause} ORDER BY timestamp_seconds"
        rows = self._conn.execute(sql, params).fetchall()
        return tuple(
            QueriedEvent(
                event_key=str(row["event_id"]),
                timestamp_seconds=row["timestamp_seconds"],
                innings=row["innings"],
                over_number=row["over_number"],
                ball_in_over=row["ball_in_over"],
                event_type=row["event_type"],
                player=row["player"],
                team=row["team"],
                confidence=row["confidence"],
                importance=row["importance"],
                milestone_value=row["milestone_value"],
                is_replay=bool(row["is_replay"]),
                clip_start_seconds=row["clip_start_seconds"],
                clip_end_seconds=row["clip_end_seconds"],
            )
            for row in rows
        )

    def get_match_summary(self) -> MatchSummary:
        """FR-014: the aggregate read-only view for `cvip inspect-db`. Pure
        read -- no diagnostics record. An event_type with zero rows is
        simply absent from `event_counts_by_type`/`average_confidence_by_type`,
        never a synthetic `0` entry."""
        match_row = self._conn.execute("SELECT * FROM matches LIMIT 1").fetchone()
        reading_count = self._conn.execute(
            "SELECT COUNT(*) FROM scoreboard_readings"
        ).fetchone()[0]
        event_count = self._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        replay_count = self._conn.execute("SELECT COUNT(*) FROM replays").fetchone()[0]
        counts_by_type = dict(
            self._conn.execute(
                "SELECT event_type, COUNT(*) FROM events GROUP BY event_type"
            ).fetchall()
        )
        avg_confidence_by_type = dict(
            self._conn.execute(
                "SELECT event_type, AVG(confidence) FROM events GROUP BY event_type"
            ).fetchall()
        )
        return MatchSummary(
            match_id=match_row["match_id"],
            source_video_path=match_row["source_video_path"],
            file_hash=match_row["file_hash"],
            duration_seconds=match_row["duration_seconds"],
            resolution_width=match_row["resolution_width"],
            resolution_height=match_row["resolution_height"],
            frame_rate=match_row["frame_rate"],
            codec=match_row["codec"],
            status=match_row["status"],
            analyzed_at=str(match_row["analyzed_at"]),
            scoreboard_reading_count=reading_count,
            event_count=event_count,
            replay_count=replay_count,
            event_counts_by_type=counts_by_type,
            average_confidence_by_type=avg_confidence_by_type,
        )

    # -- Capability 4: metadata recovery/enrichment writes
    # (specs/013-match-metadata-validation/) -----------------------------

    def has_metadata_operation(
        self, metadata_file_hash: str, metadata_event_identifier: str, operation_type: str
    ) -> bool:
        """FR-012: the idempotency pre-check (research.md Decision 6) --
        True if a RECOVERY/ENRICHMENT operation for this exact
        (metadata_file_hash, metadata_event_identifier) pair has already
        been recorded. Pure read -- no diagnostics record."""
        row = self._conn.execute(
            "SELECT 1 FROM metadata_operations "
            "WHERE metadata_file_hash = ? AND metadata_event_identifier = ? AND operation_type = ?",
            (metadata_file_hash, metadata_event_identifier, operation_type),
        ).fetchone()
        return row is not None

    def get_recovered_event_id(
        self, metadata_file_hash: str, metadata_event_identifier: str
    ) -> Optional[int]:
        """Returns the event_id of a previously recovered event for the
        given (metadata_file_hash, metadata_event_identifier) pair, or
        None if no RECOVERY operation has been recorded. Used by
        enrichment to look up event_ids for recovered wickets so they
        can be enriched even when their alignment entry's outcome is
        still RECOVERABLE_MISS (the alignment evidence is never mutated
        after Stage 2, so recovered events remain RECOVERABLE_MISS in
        the in-memory alignment). Pure read -- no diagnostics record."""
        row = self._conn.execute(
            "SELECT affected_event_id FROM metadata_operations "
            "WHERE metadata_file_hash = ? AND metadata_event_identifier = ? "
            "AND operation_type = 'RECOVERY'",
            (metadata_file_hash, metadata_event_identifier),
        ).fetchone()
        return int(row[0]) if row is not None and row[0] is not None else None

    def persist_recovered_event(
        self,
        event: RecoveredEventLike,
        metadata_file_path: str,
        metadata_file_hash: str,
        metadata_event_identifier: str,
        recovery_version: str,
    ) -> int:
        """specs/013-match-metadata-validation/contracts/metadata_pipeline_contract.md
        Stage 5: inserts a new `events` row (`source='METADATA'`) and its
        matching `metadata_operations` audit row (`operation_type='RECOVERY'`)
        in one transaction -- both succeed or both roll back together
        (data-model.md; never a recovered event with no audit trail, or
        vice versa). Returns the new `event_id`. Deliberately NOT gated by
        `_check_write_allowed` -- recovery is meant to run precisely when
        the match IS COMPLETE (matching `update_clip_window`'s own
        established precedent), never against an in-progress analysis."""

        new_event_id: List[Optional[int]] = [None]

        def work() -> Tuple[str, None]:
            cursor = self._conn.execute(
                "INSERT INTO events (timestamp_seconds, innings, over_number, ball_in_over, "
                "event_type, confidence, is_replay, source) VALUES (?,?,?,?,?,?,?, 'METADATA')",
                (
                    event.timestamp_seconds,
                    event.innings,
                    event.over_number,
                    event.ball_in_over,
                    event.event_type,
                    event.confidence,
                    False,
                ),
            )
            event_id = cursor.lastrowid
            self._insert_metadata_operation(
                operation_type="RECOVERY",
                metadata_file_path=metadata_file_path,
                metadata_file_hash=metadata_file_hash,
                metadata_event_identifier=metadata_event_identifier,
                affected_event_id=event_id,
                recovery_version=recovery_version,
                detail=f"recovered {event.event_type} at t={event.timestamp_seconds}s",
            )
            self._conn.commit()
            new_event_id[0] = event_id
            return f"event_id={event_id}", None

        self._run_operation(
            "persist_recovered_event", f"metadata_event_identifier={metadata_event_identifier}", work
        )
        return new_event_id[0]

    def update_dismissal_detail(
        self,
        event_id: int,
        dismissal_type: Optional[str],
        fielder: Optional[str],
        metadata_file_path: str,
        metadata_file_hash: str,
        metadata_event_identifier: str,
        recovery_version: str,
    ) -> None:
        """specs/013-match-metadata-validation/contracts/metadata_pipeline_contract.md
        Stage 6: updates only `dismissal_type`/`fielder` on an existing
        `events` row and inserts a matching `metadata_operations` audit row
        (`operation_type='ENRICHMENT'`) in one transaction. Never touches
        `timestamp_seconds`/`confidence`/`event_type`/any other column."""

        def work() -> Tuple[str, None]:
            self._conn.execute(
                "UPDATE events SET dismissal_type = ?, fielder = ? WHERE event_id = ?",
                (dismissal_type, fielder, event_id),
            )
            self._insert_metadata_operation(
                operation_type="ENRICHMENT",
                metadata_file_path=metadata_file_path,
                metadata_file_hash=metadata_file_hash,
                metadata_event_identifier=metadata_event_identifier,
                affected_event_id=event_id,
                recovery_version=recovery_version,
                detail=f"dismissal_type={dismissal_type} fielder={fielder}",
            )
            self._conn.commit()
            return f"event_id={event_id} dismissal_type={dismissal_type}", None

        self._run_operation("update_dismissal_detail", f"event_id={event_id}", work)

    def _insert_metadata_operation(
        self,
        operation_type: str,
        metadata_file_path: str,
        metadata_file_hash: str,
        metadata_event_identifier: str,
        affected_event_id: Optional[int],
        recovery_version: str,
        detail: str,
    ) -> None:
        """Shared by persist_recovered_event/update_dismissal_detail --
        always called from within their own work() closure, so it shares
        the caller's transaction rather than committing independently
        (data-model.md's "both succeed or both roll back together")."""
        self._conn.execute(
            "INSERT INTO metadata_operations (operation_type, metadata_file_path, metadata_file_hash, "
            "metadata_event_identifier, affected_event_id, recovery_version, detail) VALUES (?,?,?,?,?,?,?)",
            (
                operation_type,
                metadata_file_path,
                metadata_file_hash,
                metadata_event_identifier,
                affected_event_id,
                recovery_version,
                detail,
            ),
        )

    def get_match_timeline(self) -> MatchTimelineExport:
        """FR-015: the full-detail read-only view for `cvip export-timeline`
        -- every scoreboard reading and event as plain snake_case-keyed
        dicts, ordered by timestamp_seconds, ready for direct JSON/CSV
        serialization. Pure read -- no diagnostics record."""
        match_row = self._conn.execute("SELECT match_id FROM matches LIMIT 1").fetchone()
        readings = self._conn.execute(
            "SELECT * FROM scoreboard_readings ORDER BY timestamp_seconds"
        ).fetchall()
        events = self._conn.execute("SELECT * FROM events ORDER BY timestamp_seconds").fetchall()
        return MatchTimelineExport(
            match_id=match_row["match_id"] if match_row is not None else "",
            scoreboard_readings=tuple(dict(row) for row in readings),
            events=tuple(dict(row) for row in events),
        )


def _build_event_where_clause(filter: EventQueryFilter) -> Tuple[str, List]:
    """Translates an EventQueryFilter into a parameterized SQL WHERE clause
    (research.md Decision 6) -- every value bound, never string-interpolated."""
    clauses: List[str] = []
    params: List = []
    if filter.player is not None:
        clauses.append("player = ?")
        params.append(filter.player)
    if filter.team is not None:
        clauses.append("team = ?")
        params.append(filter.team)
    if filter.event_types:
        placeholders = ",".join("?" for _ in filter.event_types)
        clauses.append(f"event_type IN ({placeholders})")
        params.extend(filter.event_types)
    if filter.min_importance is not None:
        clauses.append("importance >= ?")
        params.append(filter.min_importance)
    if filter.start_over is not None:
        clauses.append("over_number >= ?")
        params.append(filter.start_over)
    if filter.end_over is not None:
        clauses.append("over_number <= ?")
        params.append(filter.end_over)
    where = " AND ".join(clauses)
    return (f"WHERE {where}" if where else "", params)
