Getting Started

Purpose. Install RBciAD, run your first EEG pipeline, and verify your environment.

Requirements

OS: Windows 10/11, Ubuntu 22.04+, macOS 13+

Python: 3.10–3.12

Recommended: numpy, scipy, matplotlib, rx, mne

Optional: LSL runtime for live streams

Installation
# From PyPI (after publication)
pip install rbciad


# From source (development)
git clone https://github.com/<org>/rbciad.git
cd rbciad
pip install -e .[dev]
Launch
rbciad
# or
python -m rbciad
Demo data

A small EDF ships with the app. If missing, use any public EDF (e.g., TUH samples) or generate a synthetic stream via LSLInlet.

First pipeline (W1 — Reader → Visualizer)

Place EEGUniversalReader and EEGVisualizer.

Connect raw → raw (or segment → segment).

Click Open in the Reader and select an EDF.

Expect scrolling traces within ~200 ms (TTFP) and ≥50 FPS on modern hardware.

!!! tip "If the UI stutters" Use segment output or enable display decimation in the Visualizer.

Uninstall
pip uninstall rbciad