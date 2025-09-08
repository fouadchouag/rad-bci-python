# User Guide

## 1) Install & Launch
**Requirements:** Windows 10/11, Ubuntu 22.04+, or macOS 13+; Python 3.10–3.12.  
Recommended: `numpy`, `scipy`, `matplotlib`, `rx`, `mne`.

**Install (source, dev mode):**
```bash
git clone https://github.com/<org>/rbciad.git
cd rbciad
pip install -e .[dev]
```

**Launch:**
```bash
rbciad       # or: python -m rbciad
```

## 2) UI Tour
- **Canvas:** Pan (MMB/Space+Drag), Zoom (Ctrl+Wheel), Select (Drag), Delete (Del).
- **Palette:** *Base Nodes* (official) and *Custom* (your nodes). Click to place.
- **Nodes:** Inputs on the left, outputs on the right; “?” badge opens **Quick Help**.
- **Connections:** Drag from output → input; edges follow when nodes move.
- **Properties Panel:** Parameters, file buttons (e.g., **Open**), **Enlarge** plot.

## 3) Build Your First Pipelines
### W1 — Visualize EDF (no‑code)
1. Place **EEGUniversalReader** → **EEGVisualizer**.
2. Connect `raw → raw` (or `segment → segment`).
3. Click **Open** in Reader, select an EDF.
**Expected:** TTFP ≤ 250 ms; FPS ≥ 50 on modern hardware.

### W2 — Filtering (HP/LP/Notch)
1. Insert **EEGFilter** between Reader and Visualizer.
2. Set HP=1 Hz, LP=40 Hz, Notch=50 Hz.
**Expected:** less drift & mains noise; ≤ 10% FPS impact.

### W3 — Stress Test (1‑s windows, 80% overlap)
1. Reader: segment length 1 s, hop 0.2 s.
2. Optional: **SignalLogger** to CSV.
**Expected:** FPS P50 ~45–55, CPU < 40% on mid‑range laptops.

## 4) Save / Load
Use **File → Save** to `.rbx` (JSON). **Open** to restore the graph.

## 5) Acquisition (LSL)
- Install LSL runtime; verify stream with LSL Browser.
- Use **LSLInlet** node to ingest live EEG segments.

## 6) Troubleshooting
- **Blank plot:** Check `sfreq` and EEG channel picks; try `segment` output.
- **Filter error:** Increase FIR length or relax transition bandwidth.
- **Slow UI:** Enable display decimation; prefer single Axes updates (`set_ydata`).
- **No FIRST_FRAME:** See console for exceptions in `execute()`; disable heavy nodes.
