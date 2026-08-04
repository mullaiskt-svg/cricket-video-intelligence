"""The `cvip` command-line entry point.

See specs/012-pipeline-orchestrator-cli/contracts/cli_contract.md for the
full contract this module implements. Argument parsing and delegation
ONLY -- no pipeline-sequencing logic of its own (FR-015); every command
delegates to cvip.orchestrator, the sole module this file imports for
anything beyond argparse/sys/json/csv/yaml.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from typing import Optional, Sequence

import yaml

from cvip import orchestrator
from cvip.orchestrator_errors import OrchestratorError, OrchestratorFailureReason
from cvip.orchestrator_models import AnalyzeRequest, GenerateRequest


def build_parser() -> argparse.ArgumentParser:
    """The `cvip` argument parser -- five subcommands matching
    specs/012-pipeline-orchestrator-cli/contracts/cli_contract.md's
    documented command surface verbatim."""
    parser = argparse.ArgumentParser(prog="cvip")
    subparsers = parser.add_subparsers(dest="command", required=True)

    analyze_parser = subparsers.add_parser("analyze")
    analyze_parser.add_argument("video_path")
    analyze_parser.add_argument("--config", default="config/default.yaml")
    analyze_parser.add_argument("--output-db", dest="output_db")
    analyze_parser.add_argument("--timeline")
    analyze_parser.add_argument("--force", action="store_true")

    generate_parser = subparsers.add_parser("generate")
    generate_parser.add_argument("match_id")
    generate_parser.add_argument("--config", default="config/default.yaml")
    generate_parser.add_argument("--template", required=True, choices=["match", "player", "team", "custom"])
    generate_parser.add_argument("--output", required=True)
    generate_parser.add_argument("--include-replays", action="store_true")
    generate_parser.add_argument("--min-importance", type=int)
    generate_parser.add_argument("--max-duration", type=int)
    generate_parser.add_argument("--start-over", type=int)
    generate_parser.add_argument("--end-over", type=int)
    generate_parser.add_argument("--team")
    generate_parser.add_argument("--player")
    generate_parser.add_argument("--event-type", action="append", dest="event_types")
    generate_parser.add_argument("--batting", action="store_true")
    generate_parser.add_argument("--bowling", action="store_true")
    generate_parser.add_argument("--fielding", action="store_true")
    generate_parser.add_argument("--complete", action="store_true")

    export_parser = subparsers.add_parser("export-timeline")
    export_parser.add_argument("match_id")
    export_parser.add_argument("--format", required=True, choices=["json", "csv"])
    export_parser.add_argument("--output")

    inspect_parser = subparsers.add_parser("inspect-db")
    inspect_parser.add_argument("db_path")

    subparsers.add_parser("doctor")

    return parser


def _load_config(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as exc:
        raise OrchestratorError(
            OrchestratorFailureReason.INVALID_ARGUMENTS, f"could not load config at {path}: {exc}"
        ) from exc
    if not isinstance(config, dict):
        raise OrchestratorError(OrchestratorFailureReason.INVALID_ARGUMENTS, f"config at {path} is not a valid mapping")
    return config


def _resolve_match_id_and_db_path(match_id_or_path: str) -> tuple[str, str]:
    """cli.md's `generate`/`export-timeline` docs accept a single "Match ID
    or path to match database" positional. A bare match_id resolves via the
    same data/matches/{match_id}.sqlite convention analyze's own default
    --output-db uses; a value that looks like a path (contains a path
    separator, or ends in .sqlite) is used directly, so a database written
    to a custom --output-db location during analyze stays reachable here."""
    looks_like_path = os.sep in match_id_or_path or "/" in match_id_or_path or match_id_or_path.endswith(".sqlite")
    if looks_like_path:
        stem = os.path.splitext(os.path.basename(match_id_or_path))[0]
        return stem, match_id_or_path
    return match_id_or_path, f"data/matches/{match_id_or_path}.sqlite"


def _run_analyze(args: argparse.Namespace) -> int:
    config = _load_config(args.config)
    request = AnalyzeRequest(
        video_path=args.video_path,
        config=config,
        output_db_path=args.output_db,
        timeline_path=args.timeline,
        force=args.force,
    )
    run = orchestrator.analyze(request)
    print(f"match_id={run.match_id} status={run.status} event_count={run.event_count}")
    return 0


def _run_generate(args: argparse.Namespace) -> int:
    config = _load_config(args.config)
    match_id, db_path = _resolve_match_id_and_db_path(args.match_id)
    events_config = config.get("events", {})
    request = GenerateRequest(
        match_id=match_id,
        db_path=db_path,
        template=args.template,
        output_path=args.output,
        player=args.player,
        team=args.team,
        event_types=tuple(args.event_types) if args.event_types else None,
        min_importance=args.min_importance,
        start_over=args.start_over,
        end_over=args.end_over,
        include_replays=args.include_replays,
        pre_roll_seconds=events_config.get("pre_roll_seconds", 8.0),
        post_roll_seconds=events_config.get("post_roll_seconds", 12.0),
        merge_gap_seconds=events_config.get("merge_gap_seconds", 3.0),
    )
    result = orchestrator.generate(request)
    print(f"output_path={result.output_path} clip_count={result.clip_count} event_count={result.event_count}")
    return 0


def _run_export_timeline(args: argparse.Namespace) -> int:
    match_id, db_path = _resolve_match_id_and_db_path(args.match_id)
    timeline = orchestrator.export_timeline(match_id, db_path)

    if args.format == "json":
        payload = {
            "match_id": timeline.match_id,
            "scoreboard_readings": list(timeline.scoreboard_readings),
            "events": list(timeline.events),
        }
        text = json.dumps(payload, indent=2, default=str)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(text)
        else:
            print(text)
    else:
        rows = list(timeline.events)
        out = open(args.output, "w", newline="", encoding="utf-8") if args.output else sys.stdout
        try:
            if rows:
                writer = csv.DictWriter(out, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)
        finally:
            if args.output:
                out.close()
    return 0


def _run_inspect_db(args: argparse.Namespace) -> int:
    summary = orchestrator.inspect_db(args.db_path)
    print(f"Match ID: {summary.match_id}")
    print(f"Source video: {summary.source_video_path}")
    print(f"Duration: {summary.duration_seconds}")
    print(f"Resolution: {summary.resolution_width}x{summary.resolution_height}")
    print(f"Frame rate: {summary.frame_rate}")
    print(f"Status: {summary.status}")
    print(f"Analyzed at: {summary.analyzed_at}")
    print(f"Scoreboard samples: {summary.scoreboard_reading_count}")
    print(f"Events: {summary.event_count}")
    print(f"Replays: {summary.replay_count}")
    print(f"Event counts by type: {summary.event_counts_by_type}")
    print(f"Average confidence by type: {summary.average_confidence_by_type}")
    return 0


def _run_doctor(args: argparse.Namespace) -> int:
    print("CVIP Environment Check\n")
    checks = orchestrator.run_doctor_checks()
    all_ok = True
    for check in checks:
        if check.ok:
            print(f"{check.name}: OK")
        else:
            all_ok = False
            print(f"{check.name}: FAIL - {check.detail}")
    print(f"\nStatus: {'OK' if all_ok else 'FAIL'}")
    return 0 if all_ok else 1


_HANDLERS = {
    "analyze": _run_analyze,
    "generate": _run_generate,
    "export-timeline": _run_export_timeline,
    "inspect-db": _run_inspect_db,
    "doctor": _run_doctor,
}


def main(argv: Optional[Sequence[str]] = None) -> int:
    """The pyproject.toml `cvip` console-script entry point. Parses
    arguments, delegates to the matching cvip.orchestrator function, and
    translates any OrchestratorError (or, as a GENERAL_FAILURE safety net,
    any other exception) into the matching specs/cli.md exit code."""
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = _HANDLERS[args.command]
    try:
        return handler(args)
    except OrchestratorError as exc:
        print(exc.detail, file=sys.stderr)
        return exc.exit_code
    except Exception as exc:  # noqa: BLE001 -- GENERAL_FAILURE's own safety net
        # Any exception not already translated into an OrchestratorError by
        # orchestrator.py is, by definition, unanticipated -- still exits
        # cleanly with exit code 1 rather than a raw traceback (FR-012:
        # every distinguishable failure must map onto the documented
        # exit-code table, and 1 is specifically reserved for this case).
        print(f"Unexpected error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover -- pure script-entry boilerplate, no logic of its own
    sys.exit(main())
