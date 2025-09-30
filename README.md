**RBciAD**** — Reactive BCI Builder**

A node-based **BCI pipeline** editor (PyQt5 + Rx) with **MNE / ****pyRiemann** integration.

- Visual **drag-and-drop** workflows

- Smooth **zoom & pan** (Ctrl+Wheel, Space to pan, toolbar +/−/100%/Fit)

- **Connection validation** by **families** (raw, segment, sfreq, ch_names, features, cov, …)

- Save/Load workflows as **JSON**

- Optional **templates** and a **Low-code** helper

- **CLI** launcher: run the app with Rbciad

**Table of Contents**

- Prerequisites

- Installation

- Launch the App

- Key Features

- Controls & Shortcuts

- Connections & Families

- Sample Workflow JSON

- Developing Plugins

- Repository Structure

- Troubleshooting

- FAQ

- License

- Credits

**Prerequisites**

- **Python 3.9+**

- OS: Windows / Linux / macOS

- No GPU required (pure raster rendering)

Core dependencies (installed via pip): PyQt5, rx, numpy, scipy, and optionally mne, pyriemann, joblib, matplotlib.

**Installation**

**1) Create & activate a virtual environment**

python -m venv .venv

# Windows

.venv\Scripts\activate

# macOS / Linux

source .venv/bin/activate

**2) Install dependencies**

pip install -r requirements.txt

Or install directly:

pip install PyQt5 rx numpy scipy mne pyriemann joblib matplotlib

mne and pyriemann are optional but strongly recommended for EEG/BCI workflows.

**3) Install the project (developer mode recommended)**

pip install -e .

This registers the **Rbciad** CLI in your environment (in .venv/bin on Linux/macOS or .venv\Scripts on Windows).


**Launch the App**

After installing the package (either pip install -e . or pip install .), just type :

Rbciad

If the command is not found:

- Make sure your venv is active (e.g., .venv\Scripts\activate on Windows).

- Ensure the venv’s Scripts (Windows) or bin (Linux/macOS) directory is on your PATH.

**Alternatives (if you don’t use the CLI entry point)**

- Directly from the repo root (fallback):

- python main.py

**Key Features**

- **Auto-discovered plugins** (by category)

- **Create nodes** via palette clicks; move and connect them

- **Validated connections** by **family** (see below)

- **Embedded plugin UIs** inside nodes via QGraphicsProxyWidget

- **Save/Load** workflows as .json

- **Zoomable canvas** (ZoomableGraphicsView) with mouse & keyboard controls

- Optional **template** starter flows and **Low-code** node creator

**Controls & Shortcuts**

- **Zoom**: Ctrl + Mouse Wheel, or toolbar buttons **+**, **−**, **100%**, **Fit**

- **Pan**: hold **Space** (or use **Middle Mouse**)

- **Delete** a node/cable: select it then press **Delete**

- **Shortcuts**:

  - Ctrl + = / Ctrl + + — Zoom in

  - Ctrl + - — Zoom out

  - Ctrl + 0 — Reset to 100%

  - Ctrl + F — Fit to scene

**Connections & Families**

Connections are validated by **family** (and values are **runtime-checked** in ConnectionItem):

- raw — MNE Raw-like streams (aliases: **data**, eeg, x)

- segment — 2D EEG matrices (ch × samples)

- sfreq — sampling frequency (float)

- ch_names — channel names (list of str)

- features — feature vectors/matrices or dicts

- cov — SPD covariance matrices

- label, model, feature_transform, ts_transform, status, …

**Rules:**

- Each **input** accepts **only one** cable.

- Output and input must have the **same family**.

- Pins show their **family** in a tooltip (hinted from the pin name or from a plugin override).

Examples: segment → segment ✅, raw → raw ✅, segment → raw ❌

If needed, a plugin can explicitly hint families:

# inside  plugin class

PIN_FAMILY_HINTS = {

    "data": "raw",

    "raw": "raw",

    "sfreq": "sfreq",

    "ch_names": "ch_names",

    "features": "features",

}

**Sample Workflow JSON**

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

This assumes **Array → MNE Raw** receives data (2D ch × n), sfreq (float), and ch_names (list of str).

**Developing Plugins**

- Inherit from BasePlugin
- Expose **inputs** / **outputs** as Rx streams (e.g., BehaviorSubject)
- Implement execute() or subscribe your logic as needed
- Provide a build_widget() to render a custom UI (embedded in the node via QGraphicsProxyWidget)
- Provide optional **family hints** via PIN_FAMILY_HINTS (see above) to improve tooltips/UX

**Repository Structure**

rad-bci-python/
├─ gui/
│  ├─ main_window.py          # MainWindow + ZoomableGraphicsView
│  ├─ node_item.py            # Node (pins, language badge, widget proxy)
│  ├─ connection_item.py      # Validated connections + runtime checks
│  ├─ workflow_templates.py   # (optional)
│  └─ ...
├─ core/
│  ├─ node_base.py
│  ├─ plugin_registry.py
│  └─ ...
├─ plugins/                   #  plugins or nodes
│  ├─ array_to_mne_raw.py
│  └─ ...
├─ workflows/
│  └─ xxxxxx.json               # example flow
├─ main.py                    # fallback launcher if no entry point
├─ pyproject.toml             # (recommended) exposes [project.scripts] Rbciad
└─ README.md

**Troubleshooting**

- **Rbciad**** not found**

  - Activate your venv (.venv\Scripts\activate or source .venv/bin/activate)
  - Ensure you ran pip install -e .
  - On Windows, verify .venv\Scripts is on PATH

- **Connection refused**

  - Check pin **families** (hover for tooltip). Only matching families can connect.

- **Array → MNE Raw issues**

  - Required inputs: data (coercible to 2D ch × n), sfreq (float), ch_names (list of str).
  - mne must be installed (pip install mne).

- **Visual artifacts (Windows)**

  - The app uses raster rendering and conservative viewport settings to minimize ghosting. If you still see trails, reduce scene refresh rates or update graphics drivers.

**FAQ**

**Can I build vertical workflows (rotate nodes)?**
Not yet; current design is horizontal. A vertical layout is a candidate for a future update.

**Can I export and share workflows?**
Yes — they’re plain JSON files. Use **Save** / **Load** from the toolbar.

**How do I add a new plugin?**
just use low-code GUI from "add new node" in toolbar or
Subclass BasePlugin, declare Rx inputs/outputs, implement your logic and UI, and ensure it’s discoverable by discover_plugins().

**License**

MIT.

**Credits**

- MNE-Python
- pyRiemann
- PyQt5
- And the broader open-source community ❤️

**Quick start:**

- pip install -e .
- Launch with **Rbciad**
- Build your pipelines, save as .json, and enjoy!