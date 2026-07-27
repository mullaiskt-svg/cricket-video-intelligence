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

1. **Generate Tasks:** `claude /speckit.tasks`
2. **Implement:** `claude /speckit.implement`
3. **Test:** `pytest tests/`
4. **Check environment:** `cvip doctor`
5. **Analyze Match:** `cvip analyze input_video.mp4 --config config/default.yaml`
6. **Generate Highlights:** `cvip generate <match_id> --template match --output output/match_highlights.mp4`

See [specs/cli.md](./specs/cli.md) for the full command reference.

## 📂 Directory Structure

See [specs/technical_plan.md](./specs/technical_plan.md) for detailed architecture, and [docs/MVP_PLAN.md](./docs/MVP_PLAN.md) for the phased delivery plan.

## 🧪 Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src tests/

# Run a specific module's tests, e.g. Video Loader
pytest tests/unit/test_video_loader_validation.py
```

## 🔧 Development

### Install Development Tools

```bash
pip install -r requirements-dev.txt
```

### Run Tests

```bash
pytest tests/ -v --cov=src
```

### Code Style

```bash
black src/ tests/
pylint src/
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

**Last Updated:** July 2026
**Status:** Spec-Kit Initialization Phase
