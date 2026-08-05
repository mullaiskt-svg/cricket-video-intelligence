"""Structured Match Metadata Validation Layer.

See specs/013-match-metadata-validation/. Not part of the frame-analysis
chain (src/cvip/video/) -- consumes Event Detection's already-persisted
output from the Event Database (Module 10), per CLAUDE.md's package-layout
convention for a later module outside that chain.
"""

#: research.md Decision 7 -- a fixed version marker for this subpackage's
#: own alignment/recovery/enrichment logic, recorded on every
#: metadata_operations row (db/schema.py) so a future logic change is a
#: visible, inspectable signal across old and new audit rows, never a
#: silent behavior change. Bump only when align()/recover_events()/
#: enrich_wickets()'s own decision-making logic changes.
METADATA_PIPELINE_VERSION = "1.0"
