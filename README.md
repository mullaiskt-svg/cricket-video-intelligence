# Cricket Video Intelligence Platform (CVIP)

## 🎬 Project Overview

An offline AI-powered platform that analyzes cricket match broadcasts once and generates unlimited customized highlight videos from a structured event database.

**Key Features:**
- 🎥 Analyze 3-4 hour match in ≤ 40 minutes
- 🔍 Detect events with ≥95% accuracy (fours, sixes, wickets)
- 🚫 Remove ≥90% of replay footage automatically
- 💾 Build searchable event database (SQLite)
- 🎞️ Generate unlimited highlights without reprocessing
- 🖥️ 100% offline (no cloud dependencies)
- ⚙️ CPU-only (no GPU required)

## 🎯 Target Hardware

- **CPU:** Intel Core i3-1115G4
- **RAM:** 8 GB
- **Storage:** SSD recommended
- **OS:** Windows 11
- **Network:** Offline (no internet required)

## 📋 Documentation

- [Product Requirements (PRD)](./docs/PRD.md)
- [Technical Architecture](./specs/technical_plan.md)
- [Feature Specifications](./specs/features.md)
- [CLI Reference](./specs/cli.md)
- [MVP Delivery Plan](./docs/MVP_PLAN.md)
- [Project/module status and package layout](./CLAUDE.md) — the current state of every pipeline module, kept up to date as features land
- Feature contracts live per-feature under `specs/<feature-name>/contracts/` (e.g., [specs/001-video-loader/contracts/](./specs/001-video-loader/contracts/)) — there is no single top-level contracts folder

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- uv (for installing Spec-Kit)
- Git

### Setup

```bash
# Clone repository
git clone <repo-url>
cd CVIP

# Create virtual environment
python -m venv venv

# Activate (Windows)
.\venv\Scripts\Activate.ps1

# Activate (Mac/Linux)
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install Spec-Kit (provides the `specify` CLI)
uv tool install specify-cli --from git+https://github.com/github/spec-kit.git

# Initialize Spec-Kit in this project
specify init --here
```

### Workflow

1. **Check environment:** `cvip doctor`
2. **Analyze Match:** `cvip analyze input_video.mp4 --config config/default.yaml`
3. **Generate Highlights:** `cvip generate <match_id> --template match --output output/match_highlights.mp4`
4. **Validate against ball-by-ball commentary (optional):** `cvip validate <match_id> --metadata commentary.json --recover --enrich` — cross-checks the analyzed match's OCR-detected events against externally-supplied commentary, recovering events OCR missed and attaching dismissal type/fielder detail. Fully decoupled from `analyze`/`generate` — safe to skip entirely.

See [specs/cli.md](./specs/cli.md) for the full command reference. Spec-Kit's own workflow (`claude /speckit.specify`, `/speckit.plan`, `/speckit.tasks`, `/speckit.implement`) is how each pipeline module above was built — only needed when adding a new feature, not for day-to-day use of the CLI itself.

## 📂 Directory Structure

See [specs/technical_plan.md](./specs/technical_plan.md) for detailed architecture, and [docs/MVP_PLAN.md](./docs/MVP_PLAN.md) for the phased delivery plan.

## 🧪 Testing

Tests are split into two tiers, selected via the `benchmark` pytest marker (registered in `pyproject.toml`). `tests/benchmark/` holds real-time/real-memory measurements against multi-hour synthetic fixtures — individually slow (minutes each), several dozen minutes combined. Everything else (`tests/unit/`, `tests/contract/`, `tests/integration/`) is fast (well under a minute total) and is what you run on every change.

**Fast tests + coverage (day-to-day / PR):**

```bash
# Deselects tests/benchmark by default (pyproject.toml addopts) -- no flags needed
pytest

# With the coverage gate (must stay at 100% on src/cvip/video -- Constitution Principle VII)
pytest --cov=src/cvip/video --cov-fail-under=100

# Run a specific module's tests, e.g. Video Loader
pytest tests/unit/test_video_loader_validation.py
```

**Benchmark tests (nightly / on-demand, before a release):**

```bash
# A trailing -m on the command line overrides the addopts default, so this
# runs ONLY the benchmark tier, not "everything else plus benchmarks"
pytest -m benchmark
```

## 🔧 Development

### Install Development Tools

```bash
pip install -r requirements-dev.txt
```

### Code Style

```bash
black src/ tests/
pylint src/
mypy src/
```

## 📊 Performance Targets

| Metric | Target | Status |
|--------|--------|--------|
| Processing Time (3hr video) | ≤ 40 min | 🔄 TBD |
| Memory Usage | < 6 GB | 🔄 TBD |
| Event Detection | ≥ 95% | 🔄 TBD |
| Replay Removal | ≥ 90% | 🔄 TBD |
| Highlight Generation | < 2 min | 🔄 TBD |

## 🎯 Success Criteria

✅ Detect ≥95% of fours, sixes, wickets
✅ Remove ≥90% of replay footage
✅ Generate highlights without reprocessing
✅ Process 3-hour match in ≤40 minutes
✅ Run entirely offline on target hardware

## 🤝 Contributing

This is a personal project following Spec-Driven Development (SDD) methodology using GitHub Spec-Kit and Claude Code.

## 📄 License

Private project - All rights reserved.

## 👥 Contributors

- Mullais (mullais.kt@gmail.com)

## 📞 Support

For questions or issues, please create a GitHub issue.

---

**Last Updated:** August 2026
**Status:** MVP pipeline implemented and merged — `cvip analyze`/`cvip generate` run end-to-end (Video Loader through Event Detection, then Clip Generator → Video Stitcher), backed by the Event Database. The optional Structured Match Metadata Validation Layer (`cvip validate`) is also implemented, including Anchor Validation for its `--recover` path. See [CLAUDE.md](./CLAUDE.md)'s Pipeline Modules table for per-module detail.
