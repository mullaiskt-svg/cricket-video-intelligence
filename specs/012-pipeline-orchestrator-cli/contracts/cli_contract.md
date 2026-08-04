# Contract: CLI (`src/cvip/cli.py`)

The `main()` function `pyproject.toml`'s `cvip = "cvip.cli:main"` entry point calls. Argument parsing and delegation only (FR-015) — see [orchestrator_contract.md](./orchestrator_contract.md) for every command's actual behavior.

## Command surface (`argparse`, matching `specs/cli.md` verbatim)

| Command | Positional | Key options |
|---|---|---|
| `cvip analyze <video_path>` | `video_path` | `--config PATH` (default `config/default.yaml`), `--output-db PATH`, `--timeline PATH`, `--force` |
| `cvip generate <match_id>` | `match_id` | `--template {match,player,team,custom}` (required), `--output PATH` (required), `--include-replays`, `--min-importance N`, `--start-over N`, `--end-over N`, `--event-type TYPE` (repeatable), `--player NAME`, `--team NAME` |
| `cvip export-timeline <match_id>` | `match_id` | `--format {json,csv}` (required), `--output PATH` |
| `cvip inspect-db <db_path>` | `db_path` | none |
| `cvip doctor` | none | none |

Every option `specs/cli.md` documents for `player`/`team`/`custom` templates (`--batting`, `--bowling`, `--fielding`, `--complete`) is also accepted at the parser level (so the interface doesn't need to change once V1.5 implements them, per `specs/cli.md`'s own "Template implementation status" note) but has no effect for MVP beyond the template-rejection path (`orchestrator_contract.md`'s `generate()`).

## Behavior

1. Parse `sys.argv` via `argparse`. An `argparse`-level error (missing required argument, invalid choice) → `argparse`'s own usual `SystemExit(2)` behavior is preserved as-is (already matches this feature's exit code 2, "invalid CLI arguments" — no translation needed).
2. Load and minimally structurally validate `config/default.yaml` (or `--config`'s path) — file exists and parses as YAML. A missing/malformed config file → exit code 2 (`OrchestratorFailureReason.INVALID_ARGUMENTS`), *before* calling into `cvip.orchestrator` at all (deep per-value validation, e.g. "is `scene_threshold` a positive float," remains each downstream module's own already-established lazy-validation responsibility — not re-validated here).
3. Build the command's own request type (`AnalyzeRequest`/`GenerateRequest`, data-model.md) or plain argument (`db_path`, `match_id`) from parsed args.
4. Call the matching `cvip.orchestrator` function inside a single `try`/`except OrchestratorError` block.
5. On success: print the command's own documented output (Outputs section below), `sys.exit(0)`.
6. On `OrchestratorError`: print `error.detail` to stderr, `sys.exit(error.exit_code)`.

## Outputs

- `analyze`: prints each stage's start/outcome marker as it runs (FR-016; a plain `loguru`-backed line per stage, not a progress bar), then a final one-line summary (`match_id`, `event_count`, elapsed time) on success.
- `generate`: prints the resolved `clip_count`/`event_count` and final `output_path` on success.
- `export-timeline`: writes the requested format to `--output` (or stdout if omitted); JSON via `json.dumps` on `MatchTimelineExport`'s already-dict-shaped fields, CSV via the stdlib `csv` module over the same data — both directly from `orchestrator.export_timeline()`'s return value, no extra transformation.
- `inspect-db`: prints every `MatchSummary` field (`specs/cli.md`'s documented example format) to stdout.
- `doctor`: prints one line per `DependencyCheckResult` (`specs/cli.md`'s documented example format: `"{name}: {'OK' if ok else 'FAIL - ' + detail}"`) plus a final `Status: {OK|FAIL}` line; `sys.exit(0)` if every check passed, `sys.exit(1)` otherwise (doctor's own failures are advisory diagnostics, not one of the nine specific `OrchestratorFailureReason` conditions — plain exit 1 is the correct "general, non-zero" signal here, not a `sys.exit(5)` that would imply only the dependency checks specifically failed when e.g. a directory-writability check could fail instead).

## Consumer obligation

None beyond what `orchestrator_contract.md` already requires of `cli.py` — this is the platform's outermost layer; nothing consumes it programmatically except a human at a terminal or a script invoking the `cvip` executable.
