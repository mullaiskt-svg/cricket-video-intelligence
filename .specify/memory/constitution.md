<!--
Sync Impact Report
- Version change: (template, unratified) → 1.0.0
- Modified principles: N/A (initial ratification)
  - Added: I. Offline-First, Always
  - Added: II. Performance is Non-Negotiable
  - Added: III. Single-Pass Analysis Principle
  - Added: IV. Detection Accuracy Requirements
  - Added: V. Modular & Extensible Architecture
  - Added: VI. Fail Fast, Never Silently
  - Added: VII. Test-First Development
- Added sections: Technology Stack, Non-Negotiables, Governance
- Removed sections: none (all template placeholders resolved)
- Templates requiring updates:
  - ✅ .specify/templates/plan-template.md (Constitution Check gate remains generic; compatible as-is)
  - ✅ .specify/templates/spec-template.md (no constitution-specific references)
  - ✅ .specify/templates/tasks-template.md (no constitution-specific references)
  - ✅ README.md (offline/performance/accuracy claims already consistent with ratified principles)
- Follow-up TODOs: none
-->

# CVIP Constitution

## Core Principles

### I. Offline-First, Always
Every feature MUST work completely offline. The platform MUST NOT introduce cloud
dependencies or external API calls at runtime. Rationale: the target deployment
environment has no guaranteed network access, and offline operation is the product's
core value proposition, not an optional mode.

### II. Performance is Non-Negotiable
The system MUST process a 3-hour match in 40 minutes or less, MUST stay under 6 GB of
memory, and MUST run CPU-only with no GPU requirement. Rationale: the target hardware
(Intel Core i3-1115G4, 8 GB RAM) is fixed and cannot be upgraded; performance budgets
are hard constraints, not aspirational targets.

### III. Single-Pass Analysis Principle
Each match MUST be analyzed only once. The system MUST NOT reprocess the same video
and MUST persist detected events to a reusable database. Rationale: reprocessing wastes
the scarce CPU/time budget defined in Principle II and risks producing inconsistent
results across runs.

### IV. Detection Accuracy Requirements
The system MUST detect fours, sixes, and wickets with at least 95% accuracy, MUST
remove at least 90% of replay footage, and MUST attach a confidence score to every
detected event. Rationale: highlight quality is only as good as detection quality, and
confidence scores allow downstream consumers to filter low-confidence events rather
than trusting silently uncertain output.

### V. Modular & Extensible Architecture
Each module MUST be independently testable and MUST expose a clear input/output
contract. The architecture MUST remain extensible to future AI capabilities without
requiring rework of existing modules. Rationale: video analysis pipelines evolve as
detection models improve, and tightly coupled modules would make that evolution costly.

### VI. Fail Fast, Never Silently
The system MUST crash with a clear error when it cannot proceed correctly, MUST NOT
fall back to silent defaults, and MUST produce detailed logging for every stage.
Rationale: silent failures in a single-pass, offline pipeline (Principles I and III)
are far more costly than a loud, early failure, since there is no opportunity to
transparently retry against a live service.

### VII. Test-First Development
Tests MUST be written before implementation. Module boundaries MUST have contract
tests, and critical paths MUST have 100% test coverage. Rationale: given the accuracy
and performance guarantees in Principles II and IV, regressions must be caught before
they reach a full 3-hour match run, which is expensive to repeat.

## Technology Stack

- **Language:** Python 3.11+
- **Video:** OpenCV + PySceneDetect
- **OCR:** Tesseract
- **Database:** SQLite
- **Stitching:** FFmpeg
- **Platform:** Windows 11

This stack is a constraint, not a suggestion: all dependencies MUST be open-source, and
no component MUST require a GPU or network access to function.

## Non-Negotiables

- Offline-first design
- Open-source dependencies only
- No GPU requirement
- Runs on target hardware (Intel Core i3-1115G4, 8 GB RAM)
- Windows-first development

## Governance

This constitution supersedes all other project practices, templates, and ad-hoc
decisions. Any conflict between this document and a spec, plan, or task MUST be
resolved in favor of this constitution.

- **Amendments**: Proposed via updates to this file. Every amendment MUST update the
  Sync Impact Report at the top of this document and MUST identify any dependent
  templates (`plan-template.md`, `spec-template.md`, `tasks-template.md`) that require
  corresponding updates.
- **Versioning**: This constitution follows semantic versioning. MAJOR for backward
  incompatible principle removals or redefinitions, MINOR for new principles or
  materially expanded guidance, PATCH for clarifications and non-semantic wording fixes.
- **Compliance Review**: All plans MUST pass the Constitution Check gate before
  implementation begins. Any deviation MUST be explicitly justified in the plan's
  Complexity Tracking section.

**Version**: 1.0.0 | **Ratified**: 2026-07-25 | **Last Amended**: 2026-07-25
