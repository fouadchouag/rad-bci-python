# RBciAD — Reactive BCI Builder

A node-based **BCI pipeline** editor (PyQt5 + Rx) with **MNE / pyRiemann** integration.

- Visual **drag-and-drop** workflows
- Smooth **zoom & pan** (Ctrl+Wheel, Space to pan, toolbar +/-/100%/Fit)
- **Connection validation** by **families** (raw, segment, sfreq, ch_names, features, cov, ...)
- Save/Load workflows as **JSON**
- Optional **templates** and a **Low-code** helper
- **CLI** launcher: run the app with `Rbciad`
- **84+ built-in plugins** covering preprocessing, feature extraction, classification, visualization, and more

## Table of Contents

- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Launch the App](#launch-the-app)
- [Key Features](#key-features)
- [Controls & Shortcuts](#controls--shortcuts)
- [Connections & Families](#connections--families)
- [Sample Workflow JSON](#sample-workflow-json)
- [Developing Plugins](#developing-plugins)
- [Repository Structure](#repository-structure)
- [Troubleshooting](#troubleshooting)
- [FAQ](#faq)
- [License](#license)
- [Credits](#credits)

## Prerequisites

- **Python 3.9+**
- OS: Windows / Linux / macOS
- No GPU required (pure raster rendering)

Core dependencies (installed via pip): PyQt5, rx, numpy, scipy, and optionally mne, pyriemann, joblib, matplotlib.

## Installation

### 1) Create & activate a virtual environment

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate
```

### 2) Install dependencies

```bash
pip install -r requirements.txt
```

Or install directly:

```bash
pip install PyQt5 rx numpy scipy mne pyriemann joblib matplotlib
```

> `mne` and `pyriemann` are optional but strongly recommended for EEG/BCI workflows.

### 3) Install the project (developer mode recommended)

```bash
pip install -e .
```

This registers the **Rbciad** CLI in your environment (in `.venv/bin` on Linux/macOS or `.venv\Scripts` on Windows).

## Launch the App

After installing the package (`pip install -e .` or `pip install .`), just type:

```bash
Rbciad
```

If the command is not found:

- Make sure your venv is active (`.venv\Scripts\activate` on Windows).
- Ensure the venv's `Scripts` (Windows) or `bin` (Linux/macOS) directory is on your PATH.

**Alternative** (from the repo root):

```bash
python main.py
```

## Key Features

- **Auto-discovered plugins** by category (84+ built-in)
- **Create nodes** via palette clicks; move and connect them
- **Validated connections** by **family** (see below)
- **Embedded plugin UIs** inside nodes via QGraphicsProxyWidget
- **Save/Load** workflows as `.json`
- **Zoomable canvas** (ZoomableGraphicsView) with mouse & keyboard controls
- Optional **template** starter flows and **Low-code** node creator
- **TS-FBCSP pipeline** — Euclidean Alignment + Tangent-Space Filter-Bank CSP for Motor Imagery classification
- **Offline training** and **online inference** workflows ready to use

## Controls & Shortcuts

- **Zoom**: Ctrl + Mouse Wheel, or toolbar buttons **+**, **−**, **100%**, **Fit**
- **Pan**: hold **Space** (or use **Middle Mouse**)
- **Delete** a node/cable: select it then press **Delete**
- **Ctrl+E** — Export workflow as PNG/PDF/SVG

**Keyboard shortcuts:**

| Shortcut | Action |
|---|---|
| `Ctrl + +` / `Ctrl + =` | Zoom in |
| `Ctrl + -` | Zoom out |
| `Ctrl + 0` | Reset to 100% |
| `Ctrl + F` | Fit to scene |

## Connections & Families

Connections are validated by **family** (values are runtime-checked):

| Family | Description | Aliases |
|---|---|---|
| `raw` | MNE Raw-like streams | `data`, `eeg`, `x` |
| `segment` | 2D EEG matrices (ch x samples) | |
| `sfreq` | Sampling frequency (float) | |
| `ch_names` | Channel names (list of str) | |
| `features` | Feature vectors/matrices or dicts | |
| `cov` | SPD covariance matrices | |
| `label` | Class labels | |
| `model` | Trained model object | |
| `feature_transform` | Fitted feature transformer | |
| `ts_transform` | Tangent-space transform | |
| `status` | Status/progress signals | |

**Rules:**

- Each **input** accepts **only one** cable.
- Output and input must have the **same family**.
- Pins show their **family** in a tooltip (hinted from the pin name or from a plugin override).

Examples: `segment → segment` ✅, `raw → raw` ✅, `segment → raw` ❌

If needed, a plugin can explicitly hint families:

```python
PIN_FAMILY_HINTS = {
    "data": "raw",
    "raw": "raw",
    "sfreq": "sfreq",
    "ch_names": "ch_names",
    "features": "features",
}
```

## Sample Workflow JSON

```json
{
  "version": 2,
  "nodes": [
    {
      "name": "Array → MNE Raw",
      "type": "ArrayToMNERaw",
      "position": [200, 200],
      "config": {
        "units": "µV",
        "montage": "standard_1020",
        "auto": true
      }
    },
    {
      "name": "MNE Set Montage",
      "type": "MNERawSetMontage",
      "position": [520, 200],
      "config": {
        "montage": "standard_1020",
        "auto": true
      }
    },
    {
      "name": "MNE Compute SSP Projs",
      "type": "MNEComputeSSPProjs",
      "position": [840, 200],
      "config": {
        "n_eog": 2,
        "l_eog": 1.0,
        "h_eog": 10.0,
        "n_ecg": 2,
        "l_ecg": 8.0,
        "h_ecg": 20.0
      }
    }
  ],
  "connections": [
    { "from": "Array → MNE Raw", "from_pin": "raw", "to": "MNE Set Montage", "to_pin": "raw" },
    { "from": "MNE Set Montage", "from_pin": "raw", "to": "MNE Compute SSP Projs", "to_pin": "raw" }
  ]
}
```

This assumes **Array → MNE Raw** receives data (2D ch x n), sfreq (float), and ch_names (list of str).

## Developing Plugins

1. Inherit from `BasePlugin` (in `core/node_base.py`)
2. Expose **inputs** / **outputs** as Rx streams (e.g., `BehaviorSubject`)
3. Implement `execute()` or subscribe your logic as needed
4. Provide a `build_widget()` to render a custom UI (embedded in the node via QGraphicsProxyWidget)
5. Provide optional **family hints** via `PIN_FAMILY_HINTS` (see above) to improve tooltips/UX
6. Place your `.py` file in `plugins/` or `custom_plugins/` — it will be auto-discovered

```python
from core.node_base import BasePlugin

class MyPlugin(BasePlugin):
    name = "My Plugin"
    category = "BCI"
    PIN_FAMILY_HINTS = {"data_in": "raw", "data_out": "raw"}

    def setup(self):
        self.inputs = {"data_in": BehaviorSubject(None)}
        self.outputs = {"data_out": BehaviorSubject(None)}

    def execute(self, msg_id=None):
        data = self.inputs["data_in"].value
        # process...
        self.outputs["data_out"].on_next(result)
```

## Repository Structure

```
rad-bci-python/
├── core/                        # Core framework
│   ├── node_base.py             # BasePlugin ABC (setup/execute lifecycle)
│   ├── plugin_registry.py       # Auto-discovery of plugins
│   ├── coercers.py              # Type coercion utilities
│   ├── metrics_logger.py        # Runtime metrics logging
│   ├── rt_perf.py               # Real-time performance tracking
│   └── services/                # Background services
│
├── gui/                         # PyQt5 GUI
│   ├── main_window.py           # MainWindow + ZoomableGraphicsView
│   ├── node_item.py             # Node (pins, language badge, widget proxy)
│   ├── connection_item.py       # Validated connections + runtime checks
│   ├── pin_item.py              # Pin rendering and interaction
│   ├── lowcode_creator.py       # Low-code node creator
│   ├── workflow_templates.py    # Template workflows
│   └── node_config_dialog.py    # Node configuration dialog
│
├── plugins/                     # Built-in plugins (84+)
│   ├── bci_preproc_node.py      # Preprocessing (bandpass, notch, CAR, z-score)
│   ├── bci_epoch_node.py        # Epoch extraction
│   ├── bci_features_node.py     # Feature extraction
│   ├── bci_trainer_node.py      # Classifier training (LR/SVM/RF + cross-val)
│   ├── bci_predictor_node.py    # Online prediction
│   ├── bci_collector_node.py    # Dataset collector
│   ├── bci_euclidean_alignment_node.py  # EA preprocessing (Chapter 5)
│   ├── bci_tsfbcsp_features_node.py    # TS-FBCSP features (Chapter 5)
│   ├── riemann_cov_plugin.py    # Riemannian covariance
│   ├── mne_*.py                 # MNE-based processing nodes
│   ├── eeg_*.py                 # EEG visualization nodes
│   └── lsl_*.py                 # Lab Streaming Layer nodes
│
├── custom_plugins/              # User/extension plugins (Rust, C, Python)
│   ├── bandpower_ext_rust.py
│   ├── rawfilter_c_plugin.py
│   └── rawfilter_rs_plugin.py
│
├── workflows/                   # Example workflow JSON files
│   ├── tsfbcsp_offline_training.json   # TS-FBCSP offline training
│   ├── tsfbcsp_online_inference.json   # TS-FBCSP online inference
│   ├── ml_offline_training.json        # ML offline training
│   ├── ml_online_inference.json        # ML online inference
│   └── ...
│
├── rbciad_app/                  # App bootstrap and utilities
├── utils/                       # LSL emulators, evaluation tools
├── offline/                     # Offline analysis scripts
├── eval/                        # Evaluation/benchmarking
├── benchmark/                   # Performance benchmarks
├── main.py                      # Fallback launcher
├── launcher.py                  # CLI entry point
├── pyproject.toml               # Package config + Rbciad CLI entry
├── CITATION.cff                 # Citation metadata (Zenodo DOI)
└── README.md
```

## Troubleshooting

- **`Rbciad` not found**
  - Activate your venv (`.venv\Scripts\activate` or `source .venv/bin/activate`)
  - Ensure you ran `pip install -e .`
  - On Windows, verify `.venv\Scripts` is on PATH

- **Connection refused**
  - Check pin **families** (hover for tooltip). Only matching families can connect.

- **Array → MNE Raw issues**
  - Required inputs: `data` (coercible to 2D ch x n), `sfreq` (float), `ch_names` (list of str).
  - `mne` must be installed (`pip install mne`).

- **Visual artifacts (Windows)**
  - The app uses raster rendering and conservative viewport settings to minimize ghosting. If you still see trails, reduce scene refresh rates or update graphics drivers.

## FAQ

**Can I build vertical workflows (rotate nodes)?**
Not yet; current design is horizontal. A vertical layout is a candidate for a future update.

**Can I export and share workflows?**
Yes — they're plain JSON files. Use **Save** / **Load** from the toolbar.

**How do I add a new plugin?**
Use the low-code GUI from "Add New Node" in the toolbar, or subclass `BasePlugin`, declare Rx inputs/outputs, implement your logic and UI, and ensure it's discoverable by `discover_plugins()`.

**What is the TS-FBCSP pipeline?**
A Tangent-Space Filter-Bank Common Spatial Patterns pipeline for Motor Imagery classification. It uses Euclidean Alignment for cross-subject preprocessing, 9 overlapping filter bands (8-30 Hz), OAS shrinkage covariance estimation, Riemannian mean computation, and tangent-space projection. See the `tsfbcsp_offline_training` and `tsfbcsp_online_inference` workflows.

## License

MIT

## Credits

- [MNE-Python](https://mne.tools/)
- [pyRiemann](https://pyriemann.readthedocs.io/)
- [PyQt5](https://riverbankcomputing.com/software/pyqt/)
- And the broader open-source community

## Quick Start

```bash
pip install -e .
Rbciad
```

Build your pipelines, save as `.json`, and enjoy!

---

**Author:** Fouad Chouag — PhD Project (University of Setif, Algeria)
GitHub: [@fouadchouag](https://github.com/fouadchouag)
DOI: [10.5281/zenodo.17095850](https://doi.org/10.5281/zenodo.17095850)
