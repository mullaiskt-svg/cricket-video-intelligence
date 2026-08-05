"""Pipeline Orchestrator: analyze(), generate(), inspect_db(),
export_timeline(), run_doctor_checks().

See specs/012-pipeline-orchestrator-cli/contracts/orchestrator_contract.md
for the full contract this module implements. Pure sequencing/translation
-- no detection, persistence, or transformation logic of its own
(research.md Decision 1); every stage below delegates entirely to an
already-implemented, already-tested module.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

from loguru import logger

from cvip.clips.errors import ClipGenerationError
from cvip.clips.generator import generate_clips
from cvip.clips.models import ClipGenerationRequest
from cvip.common.diagnostics import DiagnosticsTracker
from cvip.db.database import open_database
from cvip.db.errors import EventDatabaseError
from cvip.db.models import (
    AnalysisStatusCondition,
    EventQueryFilter,
    MatchMetadata,
    MatchSummary,
    MatchTimelineExport,
)
from cvip.events.detection import detect_events
from cvip.events.errors import EventDetectionError
from cvip.events.models import EventDetectionRequest
from cvip.metadata.alignment import align
from cvip.metadata.diagnostics import emit_validation_diagnostics
from cvip.metadata.enrichment import enrich_wickets
from cvip.metadata.errors import MetadataValidationError
from cvip.metadata.extraction import extract_ground_truth
from cvip.metadata.recovery import find_recovery_candidates, recover_events
from cvip.metadata.validation import analyze_accuracy
from cvip.orchestrator_errors import OrchestratorError, OrchestratorFailureReason
from cvip.orchestrator_models import (
    AnalysisRun,
    AnalyzeRequest,
    DependencyCheckResult,
    GenerateRequest,
    GenerateResult,
    ValidateRequest,
    ValidateResult,
)
from cvip.stitcher.errors import VideoStitchingError, VideoStitchingFailureReason
from cvip.stitcher.models import StitchRequest
from cvip.stitcher.stitcher import stitch_video
from cvip.video.errors import FailureReason as VideoLoaderFailureReason
from cvip.video.loader import load_video
from cvip.video.models import LoadStatus
from cvip.video.ocr_timeline_smoother import smooth_timeline
from cvip.video.ocr_timeline_smoother_errors import OCRTimelineSmootherError
from cvip.video.ocr_timeline_smoother_models import OCRTimelineSmootherRequest
from cvip.video.replay_detection import detect_replays
from cvip.video.replay_detection_errors import ReplayDetectionError
from cvip.video.replay_detection_models import ReplayDetectionRequest
from cvip.video.scene_detection import detect_scenes
from cvip.video.scene_detection_errors import SceneDetectionError
from cvip.video.scene_detection_models import SceneDetectionRequest
from cvip.video.scoreboard_ocr import extract_scoreboard
from cvip.video.scoreboard_ocr_errors import ScoreboardOcrError
from cvip.video.scoreboard_ocr_models import ScoreboardOcrRequest

#: Only "match" actually runs for MVP -- "player"/"team"/"custom" are V1.5
#: (FR-007, specs/cli.md's own documented Template implementation status).
_IMPLEMENTED_TEMPLATES = {"match"}

_REQUIRED_PACKAGES = ("cv2", "pytesseract", "yaml", "psutil", "loguru")


# -- Capability: native-dependency preflight (research.md Decision 6, shared
# between analyze()'s own preflight and run_doctor_checks()) -----------------


def _check_native_dependencies() -> List[DependencyCheckResult]:
    results = []
    for name, binary in (("FFmpeg", "ffmpeg"), ("Tesseract", "tesseract")):
        found = shutil.which(binary) is not None
        results.append(
            DependencyCheckResult(
                name=name,
                ok=found,
                detail=None if found else f"'{binary}' not found on PATH",
            )
        )
    return results


def _require_native_dependencies() -> None:
    missing = [r for r in _check_native_dependencies() if not r.ok]
    if missing:
        names = ", ".join(r.name for r in missing)
        raise OrchestratorError(
            OrchestratorFailureReason.MISSING_NATIVE_DEPENDENCY,
            f"Missing required native dependency: {names}",
        )


# -- Capability: innings reconstruction for scoreboard_readings persistence
# (research.md Decision 9 -- neither ScoreboardSample nor
# CleanedScoreboardSample carries innings; this replicates the same
# both-runs-and-wickets-decreased heuristic Scoreboard OCR's own validation
# and Event Detection's own FR-010 already establish, applied here as a
# simple forward scan purely for persistence) --------------------------------

#: Maximum runs value that can open a new innings. A genuine innings break
#: resets runs to near 0; OCR noise only fluctuates readings by a few units
#: (e.g., 147 → 143) and will never produce a near-zero reading at mid-innings.
#: Without this guard, simultaneous small OCR-noise decreases in both runs
#: and wickets (e.g., PLATINUM CUP FINAL: 147→143 and 5→3) triggered
#: spurious innings increments, fragmenting 2 real innings into 9 fake ones.
_NEW_INNINGS_MAX_RUNS = 20


class _ScoreboardReadingWithInnings:
    """Adapter satisfying cvip.db.models.ScoreboardReadingLike -- wraps a
    ScoreboardSample with a computed `innings`, every other field passed
    through unchanged."""

    def __init__(self, sample, innings: int) -> None:
        self.timestamp_seconds = sample.timestamp_seconds
        self.innings = innings
        self.over_number = sample.over_number
        self.ball_in_over = sample.ball_in_over
        self.runs = sample.runs
        self.wickets = sample.wickets
        self.batter = sample.batter
        self.non_striker = sample.non_striker
        self.bowler = sample.bowler
        self.run_rate = sample.run_rate
        self.raw_text = sample.raw_text
        self.ocr_confidence = sample.ocr_confidence
        self.parse_confidence = sample.parse_confidence


def _tag_readings_with_innings(samples) -> List[_ScoreboardReadingWithInnings]:
    tagged = []
    innings = 1
    last_runs: Optional[int] = None
    last_wickets: Optional[int] = None
    for sample in samples:
        if sample.runs is not None and sample.wickets is not None:
            if (
                last_runs is not None
                and last_wickets is not None
                and sample.runs < last_runs
                and sample.wickets < last_wickets
                and sample.runs < _NEW_INNINGS_MAX_RUNS
            ):
                innings += 1
            last_runs, last_wickets = sample.runs, sample.wickets
        tagged.append(_ScoreboardReadingWithInnings(sample, innings))
    return tagged


# -- Capability: analyze() (US1) --------------------------------------------


def analyze(request: AnalyzeRequest) -> AnalysisRun:
    """FR-001 through FR-005: sequence Video Loader -> Scene Detection ->
    Replay Detection -> Scoreboard OCR -> OCR Timeline Smoother -> Event
    Detection, enforcing single-pass analysis via the Event Database and
    persisting each stage's output as it completes. Raises OrchestratorError
    on any failure; the match record is marked FAILED before any such
    error propagates (never left IN_PROGRESS on a stage failure it caught)."""
    logger.info(f"analyze: starting for {request.video_path}")

    load_result = load_video(request.video_path)
    if load_result.status != LoadStatus.SUCCESS:
        if load_result.failure_reason == VideoLoaderFailureReason.FILE_NOT_FOUND:
            raise OrchestratorError(
                OrchestratorFailureReason.MISSING_INPUT_FILE, load_result.failure_detail or ""
            )
        if load_result.failure_reason == VideoLoaderFailureReason.UNSUPPORTED_FORMAT:
            raise OrchestratorError(
                OrchestratorFailureReason.UNSUPPORTED_VIDEO_FORMAT, load_result.failure_detail or ""
            )
        raise OrchestratorError(
            OrchestratorFailureReason.GENERAL_FAILURE, load_result.failure_detail or "video load failed"
        )
    source = load_result.source
    logger.info(f"analyze: video_loader OK (file_hash={source.file_hash})")

    db_path = request.output_db_path or f"data/matches/{source.file_hash[:12]}.sqlite"
    match_id = Path(db_path).stem
    # PR #15 review finding: neither this module nor open_database() creates
    # the resolved path's parent directory -- on a fresh checkout, the
    # default `data/matches/` subdirectory doesn't exist yet (only
    # `data/.gitkeep` is checked in), so the first-ever default-path analyze
    # run would otherwise fail at SQLite open with "unable to open database
    # file" before any real work even starts.
    os.makedirs(Path(db_path).parent, exist_ok=True)

    try:
        with open_database(Path(db_path)) as db:
            status = db.check_analysis_status(source.file_hash)
            if status in (AnalysisStatusCondition.COMPLETE, AnalysisStatusCondition.IN_PROGRESS):
                if not request.force:
                    raise OrchestratorError(
                        OrchestratorFailureReason.ALREADY_ANALYZED,
                        f"file_hash={source.file_hash} already has status {status.value}; pass --force to reanalyze",
                    )
                db.reset_for_forced_reanalysis(source.file_hash)

            _require_native_dependencies()

            db.begin_analysis(
                MatchMetadata(
                    file_hash=source.file_hash,
                    source_video_path=request.video_path,
                    duration_seconds=source.duration_seconds,
                    resolution_width=source.resolution[0],
                    resolution_height=source.resolution[1],
                    frame_rate=source.frame_rate,
                    codec=source.codec,
                )
            )

            try:
                scene_result = _run_scene_detection(load_result, request.config)
                replay_result = _run_replay_detection(load_result, scene_result, request.config)
                db.persist_replays(replay_result.segments)

                ocr_result = _run_scoreboard_ocr(load_result, request.config)
                tagged_readings = _tag_readings_with_innings(ocr_result.samples)
                db.persist_scoreboard_readings(tagged_readings)

                cleaned_timeline = _run_ocr_timeline_smoother(ocr_result)

                event_result = _run_event_detection(cleaned_timeline, ocr_result, replay_result, request.config)
                db.persist_events(event_result.events)
            except OrchestratorError:
                db.fail_analysis()
                raise
            except EventDatabaseError as exc:
                # A persist_*() call itself failed (e.g. a corrupted file
                # detected mid-run) -- must still translate to this feature's
                # own DATABASE_FAILURE exit code, not leak the raw
                # EventDatabaseError past cli.py's `except OrchestratorError`
                # handler (which would otherwise crash unhandled instead of
                # exiting cleanly with code 7).
                db.fail_analysis()
                raise OrchestratorError(OrchestratorFailureReason.DATABASE_FAILURE, exc.detail) from exc
            except Exception:
                db.fail_analysis()
                raise

            db.complete_analysis()

            if request.timeline_path:
                _write_timeline_json(db.get_match_timeline(), request.timeline_path)
    except EventDatabaseError as exc:
        # PR #15 review finding: open_database()'s own __enter__ (corruption/
        # schema-mismatch checks) and check_analysis_status()/
        # reset_for_forced_reanalysis()/begin_analysis() all run *before*
        # the inner try block above -- a failure there was previously
        # leaking out as a raw EventDatabaseError, past cli.py's own
        # `except OrchestratorError` handler, falling back to the generic
        # exit code 1 instead of the correct database-failure exit code 7.
        # No db.fail_analysis() call here: by construction, every one of
        # these calls either runs before an IN_PROGRESS record could exist
        # yet, or *is* the reason that record's state can't be established
        # cleanly -- there is nothing well-defined to mark FAILED.
        raise OrchestratorError(OrchestratorFailureReason.DATABASE_FAILURE, exc.detail) from exc

    logger.info(f"analyze: COMPLETE (match_id={match_id}, event_count={len(event_result.events)})")
    return AnalysisRun(
        match_id=match_id,
        db_path=db_path,
        file_hash=source.file_hash,
        status="COMPLETE",
        stages_completed=(
            "video_loader",
            "scene_detection",
            "replay_detection",
            "scoreboard_ocr",
            "ocr_timeline_smoother",
            "event_detection",
        ),
        event_count=len(event_result.events),
    )


def _run_scene_detection(load_result, config):
    logger.info("analyze: scene_detection starting")
    scene_request = SceneDetectionRequest(
        load_result=load_result,
        scene_threshold=config["video"]["scene_threshold"],
    )
    try:
        with detect_scenes(scene_request) as runner:
            result = runner.run()
    except SceneDetectionError as exc:
        raise OrchestratorError(OrchestratorFailureReason.GENERAL_FAILURE, exc.detail) from exc
    logger.info(f"analyze: scene_detection OK ({result.total_boundaries} boundaries)")
    return result


def _run_replay_detection(load_result, scene_result, config):
    logger.info("analyze: replay_detection starting")
    replay_config = config["replay"]
    signals = replay_config["signals"]
    replay_request = ReplayDetectionRequest(
        load_result=load_result,
        scene_detection_result=scene_result,
        logo_weight=signals["replay_logo_weight"],
        scoreboard_weight=signals["scoreboard_absence_weight"],
        motion_weight=signals["motion_profile_weight"],
        transition_weight=signals["transition_weight"],
        camera_angle_weight=signals["camera_angle_weight"],
        confidence_threshold=replay_config["confidence_threshold"],
        min_segment_seconds=replay_config["min_segment_seconds"],
        scoreboard_region=_region_tuple(config["ocr"]["scoreboard_region"]),
        logo_template_path=replay_config.get("logo_template_path"),
    )
    try:
        with detect_replays(replay_request) as runner:
            result = runner.run()
    except ReplayDetectionError as exc:
        raise OrchestratorError(OrchestratorFailureReason.GENERAL_FAILURE, exc.detail) from exc
    logger.info(f"analyze: replay_detection OK ({result.total_segments} segments)")
    return result


def _run_scoreboard_ocr(load_result, config):
    logger.info("analyze: scoreboard_ocr starting")
    ocr_config = config["ocr"]
    preprocess = ocr_config["preprocess"]
    ocr_request = ScoreboardOcrRequest(
        load_result=load_result,
        scoreboard_region=_region_tuple(ocr_config["scoreboard_region"]),
        preprocess_grayscale=preprocess["grayscale"],
        preprocess_threshold=preprocess["threshold"],
        preprocess_upscale=preprocess["upscale"],
        min_confidence=ocr_config["min_confidence"],
    )
    try:
        with extract_scoreboard(ocr_request) as runner:
            result = runner.run()
    except ScoreboardOcrError as exc:
        raise OrchestratorError(OrchestratorFailureReason.OCR_FAILURE, exc.detail) from exc
    logger.info(f"analyze: scoreboard_ocr OK ({result.total_samples} samples)")
    return result


def _run_ocr_timeline_smoother(ocr_result):
    logger.info("analyze: ocr_timeline_smoother starting")
    smoother_request = OCRTimelineSmootherRequest(scoreboard_ocr_result=ocr_result, outlier_window=2)
    try:
        with smooth_timeline(smoother_request) as runner:
            result = runner.run()
    except OCRTimelineSmootherError as exc:
        raise OrchestratorError(OrchestratorFailureReason.GENERAL_FAILURE, exc.detail) from exc
    logger.info(f"analyze: ocr_timeline_smoother OK ({result.total_samples} samples)")
    return result


def _run_event_detection(cleaned_timeline, ocr_result, replay_result, config):
    logger.info("analyze: event_detection starting")
    events_config = config["events"]
    event_request = EventDetectionRequest(
        cleaned_timeline=cleaned_timeline,
        raw_ocr_result=ocr_result,
        replay_result=replay_result,
        team_milestone_interval=events_config["team_milestone_interval"],
        ranking=events_config["ranking"],
    )
    try:
        with detect_events(event_request) as runner:
            result = runner.run()
    except EventDetectionError as exc:
        raise OrchestratorError(OrchestratorFailureReason.GENERAL_FAILURE, exc.detail) from exc
    logger.info(f"analyze: event_detection OK ({result.total_events} events)")
    return result


def _region_tuple(region: dict) -> Tuple[float, float, float, float]:
    return (region["x"], region["y"], region["width"], region["height"])


def _write_timeline_json(timeline: MatchTimelineExport, path: str) -> None:
    payload = {
        "match_id": timeline.match_id,
        "scoreboard_readings": list(timeline.scoreboard_readings),
        "events": list(timeline.events),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, default=str)


# -- Capability: generate() (US2) -------------------------------------------


def generate(request: GenerateRequest) -> GenerateResult:
    """FR-006, FR-007: query the Event Database per request's filters, then
    sequence Clip Generator -> Video Stitcher. Never imports or calls
    Video Loader/Scene Detection/Replay Detection/Scoreboard OCR/OCR
    Timeline Smoother/Event Detection (FR-006). Only `template="match"`
    actually runs; `player`/`team`/`custom` are rejected (FR-007)."""
    if request.template not in _IMPLEMENTED_TEMPLATES:
        raise OrchestratorError(
            OrchestratorFailureReason.INVALID_ARGUMENTS,
            f"template '{request.template}' not yet implemented -- planned for V1.5",
        )

    if not os.path.exists(request.db_path):
        raise OrchestratorError(
            OrchestratorFailureReason.MISSING_INPUT_FILE,
            f"no database found for match_id={request.match_id} at {request.db_path}",
        )

    query_filter = EventQueryFilter(
        player=request.player,
        team=request.team,
        event_types=request.event_types,
        min_importance=request.min_importance,
        start_over=request.start_over,
        end_over=request.end_over,
    )
    try:
        with open_database(Path(request.db_path)) as db:
            queried_events = db.query_events(query_filter)
            # PR #15 review finding: request.match_id (e.g. "match_001") is a
            # database identifier, not the real video file path -- passing it
            # straight through as source_video_path made stitch_video()'s own
            # os.path.isfile() check fail for any non-empty plan. The real
            # path was already persisted during analyze()'s begin_analysis()
            # call; read it back from the same open connection.
            source_video_path = db.get_match_summary().source_video_path
    except EventDatabaseError as exc:
        raise OrchestratorError(OrchestratorFailureReason.DATABASE_FAILURE, exc.detail) from exc

    clip_request = ClipGenerationRequest(
        events=queried_events,
        source_video_path=source_video_path,
        video_duration_seconds=_max_timestamp(queried_events),
        pre_roll_seconds=request.pre_roll_seconds,
        post_roll_seconds=request.post_roll_seconds,
        merge_gap_seconds=request.merge_gap_seconds,
        include_replays=request.include_replays,
    )
    try:
        with generate_clips(clip_request) as runner:
            plan = runner.run()
    except ClipGenerationError as exc:
        raise OrchestratorError(OrchestratorFailureReason.GENERAL_FAILURE, exc.detail) from exc

    if plan.total_clips == 0:
        # PR #15 review finding: Video Stitcher's own validation rejects an
        # empty ClipPlan as EMPTY_CLIP_PLAN, which would otherwise turn a
        # valid "zero matching events" outcome (Edge Cases: an empty filter
        # result, or every matching event replay-excluded) into a spurious
        # EXPORT_FAILURE. Short-circuit before ever constructing a
        # StitchRequest -- nothing to stitch is not a failure.
        return GenerateResult(output_path=request.output_path, clip_count=0, event_count=len(queried_events))

    stitch_request = StitchRequest(clip_plan=plan, output_path=request.output_path)
    try:
        with stitch_video(stitch_request) as runner:
            stitch_result = runner.run()
    except VideoStitchingError as exc:
        if exc.reason == VideoStitchingFailureReason.MISSING_FFMPEG:
            raise OrchestratorError(OrchestratorFailureReason.MISSING_NATIVE_DEPENDENCY, exc.detail) from exc
        raise OrchestratorError(OrchestratorFailureReason.EXPORT_FAILURE, exc.detail) from exc

    return GenerateResult(
        output_path=stitch_result.output_path,
        clip_count=stitch_result.clip_count,
        event_count=len(queried_events),
    )


def _max_timestamp(queried_events) -> float:
    if not queried_events:
        return 0.0
    return max(e.timestamp_seconds for e in queried_events) + 60.0


# -- Capability: inspect_db()/export_timeline() (US3, US4) -------------------


def inspect_db(db_path: str) -> MatchSummary:
    """FR-010: a thin pass-through to Event Database's get_match_summary()
    for the given already-resolved database file path."""
    if not os.path.exists(db_path):
        raise OrchestratorError(OrchestratorFailureReason.MISSING_INPUT_FILE, f"no database at {db_path}")
    try:
        with open_database(Path(db_path)) as db:
            return db.get_match_summary()
    except EventDatabaseError as exc:
        raise OrchestratorError(OrchestratorFailureReason.DATABASE_FAILURE, exc.detail) from exc


def export_timeline(match_id: str, db_path: str) -> MatchTimelineExport:
    """FR-009: a thin pass-through to Event Database's get_match_timeline()
    for the given match_id/already-resolved database file path."""
    if not os.path.exists(db_path):
        raise OrchestratorError(
            OrchestratorFailureReason.MISSING_INPUT_FILE, f"no database found for match_id={match_id} at {db_path}"
        )
    try:
        with open_database(Path(db_path)) as db:
            return db.get_match_timeline()
    except EventDatabaseError as exc:
        raise OrchestratorError(OrchestratorFailureReason.DATABASE_FAILURE, exc.detail) from exc


# -- Capability: run_doctor_checks() (US5) -----------------------------------


def run_doctor_checks() -> Tuple[DependencyCheckResult, ...]:
    """FR-011: independently checks Python version, native dependencies
    (FFmpeg/Tesseract), required Python package importability, and
    data/output/logs directory writability -- one failing check never
    prevents the others from running or reporting their own result."""
    results: List[DependencyCheckResult] = []

    version_ok = sys.version_info >= (3, 11)
    results.append(
        DependencyCheckResult(
            name="Python",
            ok=version_ok,
            detail=None if version_ok else f"Python 3.11+ required, found {sys.version.split()[0]}",
        )
    )

    results.extend(_check_native_dependencies())

    for package in _REQUIRED_PACKAGES:
        try:
            importlib.import_module(package)
            results.append(DependencyCheckResult(name=package, ok=True))
        except ImportError as exc:
            results.append(DependencyCheckResult(name=package, ok=False, detail=str(exc)))

    for label, directory in (("Data directory", "data"), ("Output directory", "output"), ("Logs directory", "logs")):
        results.append(_check_directory_writable(label, directory))

    return tuple(results)


def _check_directory_writable(label: str, directory: str) -> DependencyCheckResult:
    try:
        os.makedirs(directory, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=directory, delete=True):
            pass
        return DependencyCheckResult(name=label, ok=True)
    except OSError as exc:
        return DependencyCheckResult(name=label, ok=False, detail=str(exc))


# -- Capability: validate() (specs/013-match-metadata-validation/) ----------


def _file_hash(path: str) -> str:
    """A simple whole-file digest identifying a metadata file's exact
    content -- deliberately not Video Loader's own sampled `file_hash`
    (FR-014), since a metadata file is small text, not multi-GB video; a
    full read is cheap here."""
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        digest.update(f.read())
    return digest.hexdigest()


def validate(request: ValidateRequest) -> ValidateResult:
    """specs/013-match-metadata-validation/contracts/orchestrator_validate_contract.md.
    Stages 1-3 (Ground Truth Extraction -> Timeline Alignment -> Accuracy
    Analysis) always run; Stages 4-5 (Recovery) only if `request.recover`;
    Stage 6 (Enrichment) only if `request.enrich`. With neither flag, no
    write of any kind reaches the database (FR-003's structural
    read-only-by-default guarantee).

    Emits exactly one diagnostics record per invocation regardless of
    outcome (matching db/database.py's own `_run_operation` convention of
    recording every distinguishable failure, not just successes)."""
    input_summary = (
        f"db_path={request.db_path} metadata_path={request.metadata_path} "
        f"recover={request.recover} enrich={request.enrich}"
    )
    # Manual __enter__/__exit__ (not a `with` block), matching
    # db/database.py's own _run_operation precedent exactly: __exit__ must
    # run immediately before build() on *every* exit path so its captured
    # end-time/peak-memory reflect that path's own real work, not whatever
    # ran after a `with` block's delayed, single exit point would imply.
    tracker = DiagnosticsTracker()
    tracker.__enter__()
    try:
        report, recovered_count, skipped_recovery_count, enriched_count = _run_validate(request)
    except (OrchestratorError, EventDatabaseError) as exc:
        # Both OrchestratorError and EventDatabaseError carry a `.reason`
        # enum member -- same shape, different taxonomy.
        reason = exc.reason.value
        tracker.__exit__(None, None, None)
        emit_validation_diagnostics(
            tracker,
            input_summary=input_summary,
            metadata_entries_parsed=0,
            alignment_success_rate=0.0,
            unrecoverable_events=0,
            recovered_events=0,
            enriched_wicket_events=0,
            ambiguous_alignments=0,
            failure_reason=reason,
        )
        if isinstance(exc, EventDatabaseError):
            raise OrchestratorError(OrchestratorFailureReason.DATABASE_FAILURE, exc.detail) from exc
        raise
    except Exception:
        tracker.__exit__(None, None, None)
        raise

    alignment_success_rate = (
        (report.true_positives + report.false_negatives_with_signal) / report.ground_truth_total
        if report.ground_truth_total
        else 0.0
    )
    tracker.__exit__(None, None, None)
    emit_validation_diagnostics(
        tracker,
        input_summary=input_summary,
        metadata_entries_parsed=report.ground_truth_total,
        alignment_success_rate=alignment_success_rate,
        unrecoverable_events=report.false_negatives_no_signal,
        recovered_events=recovered_count,
        enriched_wicket_events=enriched_count,
        ambiguous_alignments=0,
    )

    return ValidateResult(
        report=report,
        recovered_count=recovered_count,
        skipped_recovery_count=skipped_recovery_count,
        enriched_count=enriched_count,
    )


def _run_validate(request: ValidateRequest):
    """The actual Stage 1-6 sequence, factored out of validate() so every
    exit path (success or failure) shares one diagnostics-emission point."""
    with open_database(Path(request.db_path)) as db:
        summary = db.get_match_summary()
        if summary.status != "COMPLETE":
            raise OrchestratorError(
                OrchestratorFailureReason.INVALID_ARGUMENTS,
                "match is not COMPLETE; validate requires a fully-analyzed match",
            )

        try:
            ground_truth = extract_ground_truth(request.metadata_path)
        except MetadataValidationError as exc:
            if not os.path.exists(request.metadata_path):
                raise OrchestratorError(OrchestratorFailureReason.MISSING_INPUT_FILE, exc.detail) from exc
            raise OrchestratorError(OrchestratorFailureReason.INVALID_ARGUMENTS, exc.detail) from exc

        timeline = db.get_match_timeline()

        try:
            alignment = align(ground_truth, timeline.scoreboard_readings, timeline.events)
        except MetadataValidationError as exc:
            raise OrchestratorError(OrchestratorFailureReason.INVALID_ARGUMENTS, exc.detail) from exc

        report = analyze_accuracy(alignment, timeline.events)

        recovered_count = 0
        skipped_recovery_count = 0
        enriched_count = 0
        # Only hash the metadata file when a write operation will use it
        # (the hash is only needed for idempotency keys in metadata_operations).
        metadata_file_hash = (
            _file_hash(request.metadata_path) if (request.recover or request.enrich) else None
        )

        if request.recover:
            candidates = find_recovery_candidates(alignment)
            try:
                recovered, skipped_recovery_count = recover_events(
                    candidates, db, request.metadata_path, metadata_file_hash
                )
            except MetadataValidationError as exc:
                raise OrchestratorError(OrchestratorFailureReason.INVALID_ARGUMENTS, exc.detail) from exc
            recovered_count = len(recovered)

        if request.enrich:
            enriched = enrich_wickets(alignment, db, request.metadata_path, metadata_file_hash)
            enriched_count = len(enriched)

        return report, recovered_count, skipped_recovery_count, enriched_count
