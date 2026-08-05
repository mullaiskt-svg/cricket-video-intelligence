"""Contract test for the CLI: static check that src/cvip/cli.py never
imports any pipeline/persistence module directly (FR-015) -- only
cvip.orchestrator/cvip.orchestrator_models/cvip.orchestrator_errors, plus
stdlib/PyYAML. Mirrors tests/contract/test_scoreboard_parsers_contract.py's
own precedent for a structural (not just behavioral) independence check.

specs/013-match-metadata-validation/contracts/orchestrator_validate_contract.md
extends this same independence guarantee to cvip.metadata -- cli.py's new
`cvip validate` handler must delegate through cvip.orchestrator exactly
like every other command, never importing the metadata subpackage itself.
"""

import argparse
import ast
import inspect

import cvip.cli

_FORBIDDEN_PREFIXES = (
    "cvip.video",
    "cvip.events",
    "cvip.clips",
    "cvip.stitcher",
    "cvip.db",
    "cvip.metadata",
)


def _imported_module_names(source: str) -> list[str]:
    tree = ast.parse(source)
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
    return names


def test_cli_never_imports_pipeline_or_persistence_modules_directly():
    source = inspect.getsource(cvip.cli)
    imported = _imported_module_names(source)

    violations = [name for name in imported if any(name.startswith(prefix) for prefix in _FORBIDDEN_PREFIXES)]

    assert violations == [], f"cli.py must only import cvip.orchestrator*, found: {violations}"


def test_cli_imports_orchestrator():
    source = inspect.getsource(cvip.cli)
    imported = _imported_module_names(source)

    assert any(name.startswith("cvip.orchestrator") or name == "cvip" for name in imported)


def test_every_documented_command_is_registered():
    parser = cvip.cli.build_parser()
    subparsers_action = next(
        action for action in parser._actions if isinstance(action, argparse._SubParsersAction)
    )
    assert set(subparsers_action.choices.keys()) == {
        "analyze",
        "generate",
        "export-timeline",
        "inspect-db",
        "validate",
        "doctor",
    }
