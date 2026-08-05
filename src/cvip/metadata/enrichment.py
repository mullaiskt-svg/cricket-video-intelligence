"""Stage 6: Optional Enrichment.

See specs/013-match-metadata-validation/contracts/metadata_pipeline_contract.md
Stage 6, research.md Decision 9. Phrase matching against a small, fixed
set of known commentary phrasings -- every one already attested verbatim
in this project's own real commentary data (ground_truth_v2/
wild_wanderers_commentary.json / phoenix_firehawks_commentary.json), not a
hypothetical format. No NLP/ML dependency (research.md Decision 9's own
rationale).

Checked in order of specificity (a more specific pattern must be tried
before a more general one that would otherwise also match its text --
"c X b Y"/"st X b Y" both contain a bare "b Y" that must not be
misclassified as a plain BOWLED dismissal).
"""

from __future__ import annotations

import re
from typing import Sequence, Tuple

from cvip.metadata import METADATA_PIPELINE_VERSION
from cvip.metadata.alignment_models import AlignmentOutcome, MatchAlignmentEvidence
from cvip.metadata.enrichment_models import DismissalDetail
from cvip.metadata.extraction_models import metadata_event_identifier

_NAME = r"[A-Za-z][A-Za-z .'\-]*?"

_CAUGHT_RE = re.compile(rf"\bc\s+({_NAME})\s+b\s+{_NAME}")
_STUMPED_RE = re.compile(rf"\bst\s+({_NAME})\s+b\s+{_NAME}")
_RUN_OUT_RE = re.compile(rf"run\s*out\s*\(({_NAME})\)", re.IGNORECASE)
_LBW_RE = re.compile(r"\blbw\b", re.IGNORECASE)
_HIT_WICKET_RE = re.compile(r"hit\s+wicket", re.IGNORECASE)
_BOWLED_RE = re.compile(rf"\bb\s+{_NAME}")


def extract_dismissal_detail(description: str) -> DismissalDetail:
    """research.md Decision 9's phrase-matching rules, tried in order of
    specificity. No match -> both fields None (FR-014 -- never guessed)."""
    match = _CAUGHT_RE.search(description)
    if match:
        return DismissalDetail(dismissal_type="CAUGHT", fielder=match.group(1).strip())

    match = _STUMPED_RE.search(description)
    if match:
        return DismissalDetail(dismissal_type="STUMPED", fielder=match.group(1).strip())

    match = _RUN_OUT_RE.search(description)
    if match:
        return DismissalDetail(dismissal_type="RUN_OUT", fielder=match.group(1).strip())

    if _LBW_RE.search(description):
        return DismissalDetail(dismissal_type="LBW", fielder=None)

    if _HIT_WICKET_RE.search(description):
        return DismissalDetail(dismissal_type="HIT_WICKET", fielder=None)

    if _BOWLED_RE.search(description):
        return DismissalDetail(dismissal_type="BOWLED", fielder=None)

    return DismissalDetail(dismissal_type=None, fielder=None)


def enrich_wickets(
    alignment: Sequence[MatchAlignmentEvidence],
    db,
    metadata_file_path: str,
    metadata_file_hash: str,
) -> Tuple[DismissalDetail, ...]:
    """Stage 6 (FR-014, FR-017). Only ever targets TRUE_POSITIVE WICKET
    entries (an event already confirmed to exist -- recovered events are
    enriched in the same pass that recovers them via their own
    alignment entry, not a separate lookup). Never touches
    timestamp_seconds/confidence/event_type -- only ever writes
    dismissal_type/fielder on a row that already exists.

    Idempotent re-run (FR-012's same requirement, applied here too --
    caught via real manual CLI testing, not the mocked unit tests: without
    this pre-check, a second `--enrich` run against the same match hit the
    metadata_operations UNIQUE constraint defense-in-depth backstop
    (research.md Decision 6) and crashed instead of skipping cleanly)."""
    enriched = []
    for item in alignment:
        if item.metadata_event.event_type != "WICKET":
            continue

        identifier = metadata_event_identifier(item.metadata_event)

        if item.outcome == AlignmentOutcome.TRUE_POSITIVE:
            event_id = int(item.matched_detected_event["event_id"])
        elif item.outcome == AlignmentOutcome.RECOVERABLE_MISS:
            # Alignment evidence is never mutated after Stage 2, so a
            # wicket recovered in Stage 5 still shows RECOVERABLE_MISS
            # here. Look up whether recovery already ran by checking
            # metadata_operations for a matching RECOVERY row.
            event_id = db.get_recovered_event_id(metadata_file_hash, identifier)
            if event_id is None:
                continue  # not yet recovered (--recover not used, or skipped)
        else:
            continue  # UNRECOVERABLE_MISS -- no event to enrich

        if db.has_metadata_operation(metadata_file_hash, identifier, "ENRICHMENT"):
            continue

        detail = extract_dismissal_detail(item.metadata_event.description)
        if detail.dismissal_type is None:
            # FR-014: nothing confidently readable -- leave unset, no
            # audit row either, since nothing was actually changed.
            continue

        db.update_dismissal_detail(
            event_id,
            detail.dismissal_type,
            detail.fielder,
            metadata_file_path=metadata_file_path,
            metadata_file_hash=metadata_file_hash,
            metadata_event_identifier=identifier,
            recovery_version=METADATA_PIPELINE_VERSION,
        )
        enriched.append(detail)

    return tuple(enriched)
