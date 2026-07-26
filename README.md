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
- [API Contracts](./contracts/)

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
4. **Analyze Match:** `python -m src.analyzer input_video.mp4`
5. **Generate Highlights:** `python -m src.highlight_generator --template match`

## 📂 Directory Structure

See docs/technical_plan.md for detailed architecture.


## 🏗️ Development Phases

| Phase | Description | Duration |
|-------|-------------|----------|
| 0 | Foundation & Setup | Week 1 |
| 1 | Video Processing Core | Weeks 2-3 |
| 2 | Detection Systems | Weeks 4-6 |
| 3 | Event Ranking | Week 7 |
| 4 | Clip Generation | Week 8 |
| 5 | Highlight Templates | Week 9 |
| 6 | Testing & Optimization | Week 10 |

## 🧪 Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src tests/

# Run specific module tests
pytest tests/test_scene_detection.py
```

## 📊 Success Metrics

- Detection accuracy: ≥95% (fours, sixes, wickets)
- Replay removal: ≥90%
- Processing time: ≤40 min for 3-hour match
- Memory usage: <6GB peak

## 🤝 Contributing

This is a personal project following Spec-Driven Development (SDD) methodology using GitHub Spec-Kit and Claude Code.

## 📄 License

Private project - All rights reserved.

---

**Status:** 🚧 In Development (Phase 0)
**Last Updated:** October 2025
