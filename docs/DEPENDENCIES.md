# Native Dependency Notes

CVIP uses Python packages for orchestration, but some required tools are native system binaries. Installing `requirements.txt` is not enough by itself.

## Python Dependencies

Install development dependencies with:

```bash
pip install -r requirements-dev.txt
```

For runtime-only installation:

```bash
pip install -r requirements.txt
```

## Required Native Tools

### FFmpeg

FFmpeg is required for clip extraction, clip concatenation, and final MP4 generation.

Check whether FFmpeg is installed:

```bash
ffmpeg -version
```

If the command is not found, install FFmpeg and ensure the `ffmpeg` executable is available on your system `PATH`.

#### Windows Installation Options

Using Chocolatey:

```powershell
choco install ffmpeg
```

Using Winget:

```powershell
winget install Gyan.FFmpeg
```

Manual installation:

1. Download a Windows FFmpeg build.
2. Extract it to a permanent directory, for example `C:\ffmpeg`.
3. Add the `bin` directory, for example `C:\ffmpeg\bin`, to your system `PATH`.
4. Open a new terminal and run:

```powershell
ffmpeg -version
```

### Tesseract OCR

Tesseract is required for scoreboard OCR.

The Python package `pytesseract` is only a wrapper. The native Tesseract executable must also be installed.

Check whether Tesseract is installed:

```bash
tesseract --version
```

If the command is not found, install Tesseract and ensure the `tesseract` executable is available on your system `PATH`.

#### Windows Installation Options

Using Chocolatey:

```powershell
choco install tesseract
```

Using Winget, if available:

```powershell
winget search tesseract
```

Then install the appropriate Tesseract package shown by Winget.

Manual installation:

1. Download a Windows Tesseract installer.
2. Install Tesseract to a permanent directory, for example `C:\Program Files\Tesseract-OCR`.
3. Add the install directory to your system `PATH`.
4. Open a new terminal and run:

```powershell
tesseract --version
```

## Recommended Startup Checks

The application should fail fast if native dependencies are unavailable.

Recommended Python checks:

```python
import shutil

if shutil.which("ffmpeg") is None:
    raise RuntimeError("FFmpeg is required but was not found on PATH.")

if shutil.which("tesseract") is None:
    raise RuntimeError("Tesseract OCR is required but was not found on PATH.")
```

## Why These Checks Matter

CVIP must run offline and should not silently skip required processing steps. Missing native dependencies should produce clear startup errors rather than causing failures later in the analysis pipeline.

## Dependency Summary

| Tool | Required For | Python Package Is Enough? |
| ---- | ------------ | ------------------------- |
| FFmpeg | Clip extraction and stitching | No |
| Tesseract OCR | Scoreboard OCR | No |
| pytesseract | Python wrapper for Tesseract | Requires native Tesseract |
| ffmpeg-python | Python wrapper for FFmpeg | Requires native FFmpeg |

## Validation Commands

Run these after installation:

```bash
python -m pip install -r requirements-dev.txt
ffmpeg -version
tesseract --version
```

If all three commands succeed, the local environment has the main Python and native dependencies required for CVIP development.
