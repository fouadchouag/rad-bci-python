# Getting Started

Install RBciAD, run your first EEG pipeline, and verify your environment.

## Requirements

- **OS**: Windows 10/11, Ubuntu 22.04+, or macOS 13+
- **Python**: 3.9+ (3.10–3.12 recommended)
- **Core dependencies**: PyQt5, rx, numpy, scipy
- **Recommended**: mne, pyriemann, joblib, matplotlib
- **Optional**: LSL runtime for live EEG streams

## Installation

### From source (recommended)

```bash
# Clone the repository
git clone https://github.com/fouadchouag/rad-bci-python.git
cd rad-bci-python

# Create and activate a virtual environment
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install in developer mode (registers the Rbciad CLI)
pip install -e .
```

### Verify

```bash
Rbciad
```

The RBciAD window should open. If the command is not found, ensure your venv is active and `.venv/Scripts` (Windows) or `.venv/bin` (Linux/macOS) is on your PATH.

## Demo Data

A small EDF file ships with the project. If missing, use any public EEG file (EDF, BDF, GDF, or FIF format) or generate a synthetic stream using the **LSLInlet** node.

## First Pipeline (W1 — Reader → Visualizer)

1. Place **EEGUniversalReader** and **EEGVisualizer** on the canvas
2. Connect `raw → raw` (drag from the output pin to the input pin)
3. Click **Open** in the Reader and select an EDF file
4. Expect scrolling traces within ~200 ms (TTFP) and ≥50 FPS

!!! tip "If the UI stutters"
    Use `segment` output or enable display decimation in the Visualizer.

## Uninstall

```bash
pip uninstall rbciad
```
