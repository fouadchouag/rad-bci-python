# Beginner Guide

This guide walks you through installing RBciAD, understanding the interface, and building your first BCI pipelines — no prior BCI experience required.

## What is RBciAD?

RBciAD is a **visual, node-based tool** for building Brain-Computer Interface (BCI) pipelines. Instead of writing code, you drag and drop processing blocks (called **nodes**) and connect them together. Data flows automatically from one node to the next — there is no "Run" button.

Think of it like **LEGO for EEG processing**: each node is a building block, and you snap them together to create a pipeline.

### Key concepts

| Term | Meaning |
|---|---|
| **Node** | A processing block with inputs (left) and outputs (right) |
| **Pin** | A connection point on a node (colored by data type) |
| **Connection (cable)** | A line between two pins that carries data |
| **Family** | The data type of a pin (e.g., `raw`, `segment`, `features`) |
| **Workflow** | A complete graph of nodes and connections, saved as JSON |
| **Plugin** | The Python class that defines a node's behavior |

## Step 1: Installation

### Requirements

- **Python 3.9+** (3.10–3.12 recommended)
- **OS**: Windows 10/11, Ubuntu 22.04+, or macOS 13+
- No GPU required

### Install from source

```bash
# Clone the repository
git clone https://github.com/fouadchouag/rad-bci-python.git
cd rad-bci-python

# Create and activate a virtual environment
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Install in developer mode (registers the Rbciad CLI)
pip install -e .
```

### Verify installation

```bash
Rbciad
```

If the app opens, you're ready. If not, see [Troubleshooting](troubleshooting.md).

## Step 2: Understanding the Interface

When you launch RBciAD, you see three main areas:

```
┌─────────────────────────────────────────────────────┐
│  Toolbar: Save, Load, Export, Zoom controls          │
├──────────┬──────────────────────────────────────────┤
│          │                                          │
│  Palette │          Canvas                          │
│  (left)  │     (drag & drop area)                   │
│          │                                          │
│  Click   │   Nodes appear here                      │
│  to add  │   Connect them with cables               │
│  nodes   │                                          │
│          │                                          │
├──────────┴──────────────────────────────────────────┤
│  Console / Log                                      │
└─────────────────────────────────────────────────────┘
```

### The Palette (left panel)

Lists all available nodes, organized by category:

- **BCI** — preprocessing, features, training, prediction
- **MNE** — MNE-Python integration (filters, epochs, I/O)
- **EEG** — readers, filters, visualizers
- **LSL** — Lab Streaming Layer (live data streams)
- **Visualization** — plots, viewers
- **ML** — machine learning utilities

Click a node name to place it on the canvas.

### The Canvas (center)

This is where you build your pipeline:

- **Pan**: hold `Space` + drag, or middle-mouse drag
- **Zoom**: `Ctrl + Mouse Wheel`
- **Select**: click a node or drag a selection box
- **Delete**: select + `Del` key
- **Connect**: drag from an output pin (right side) to an input pin (left side)

### Nodes

Each node has:

- **Input pins** (left side) — receive data
- **Output pins** (right side) — send data
- **A title bar** — shows the node name
- **A "?" badge** — click for Quick Help (`Ctrl+F1`)
- **A properties panel** — configure parameters (click the node to see it)

### Connections

- Drag from an **output pin** to an **input pin** to create a cable
- Only pins with the **same family** (data type) can connect
- Each input accepts **only one** cable
- Hover over a pin to see its family in a tooltip

## Step 3: Your First Pipeline — Visualize EEG Data

Let's build a simple pipeline to load and display EEG data.

### 3.1 Place the nodes

1. In the **Palette**, find **EEGUniversalReader** under the EEG category
2. Click it — it appears on the canvas
3. Find **EEGVisualizer** in the Visualization category
4. Click it — it appears on the canvas

### 3.2 Connect them

1. Click the **raw** output pin on the right of EEGUniversalReader
2. Drag to the **raw** input pin on the left of EEGVisualizer
3. A cable appears connecting them

### 3.3 Load data

1. Click on **EEGUniversalReader** to select it
2. In the **properties panel**, click the **Open** button
3. Select an EEG file (`.edf`, `.bdf`, `.gdf`, or `.fif`)

### 3.4 See the result

The EEGVisualizer starts showing scrolling EEG traces automatically. There is no "Run" button — data flows as soon as connections are made.

!!! tip "No EEG file?"
    Use the **LSLInlet** node with a synthetic stream, or download a sample EDF from [physionet.org](https://physionet.org/content/sleep-edfx/1.0.0/).

## Step 4: Add Filtering

Let's add a filter between the reader and the visualizer.

### 4.1 Insert a filter node

1. Find **EEGFilter** (or **MNEBandpassFilter**) in the Palette
2. Place it on the canvas between the Reader and Visualizer
3. Disconnect the existing cable (select it + `Del`)
4. Connect: `Reader(raw) → Filter(raw) → Visualizer(raw)`

### 4.2 Configure the filter

1. Click on the Filter node
2. In the properties panel, set:
   - **High-pass**: 1 Hz (removes drift)
   - **Low-pass**: 40 Hz (removes high-frequency noise)
   - **Notch**: 50 Hz (removes power line noise; use 60 Hz in the US)

### 4.3 Observe

The visualizer now shows cleaner EEG. You can toggle the filter on/off by disconnecting/reconnecting the cable.

## Step 5: Save Your Workflow

1. Go to **File → Save** (or `Ctrl+S`)
2. Choose a location and name (e.g., `my_first_pipeline.json`)
3. The workflow is saved as a JSON file

To reload it later:

1. **File → Open** (or `Ctrl+O`)
2. Select your `.json` file
3. The entire graph is restored — nodes, positions, and connections

## Step 6: Build a BCI Training Pipeline

Now let's build something more advanced: a complete Motor Imagery classification pipeline.

### 6.1 The pipeline

```
EEGReader → Preprocessing → Epochs → Features → Trainer
```

### 6.2 Place and connect nodes

1. **EEGReader** — loads your EEG recording
2. **BCI_Preproc** — bandpass filter + CAR + z-score normalization
3. **BCI_Epoch** — extracts fixed-length epochs from the continuous signal
4. **BCI_Features** — extracts features (bandpower, CSP, etc.)
5. **BCI_Trainer** — trains a classifier (LR, SVM, or Random Forest)

Connect them in order: `raw → raw → segment → segment → features → features → model`

### 6.3 Configure each node

- **BCI_Preproc**: bandpass 8–30 Hz, notch 50 Hz, CAR reference
- **BCI_Epoch**: window length 2s, overlap 50%
- **BCI_Trainer**: select classifier type, enable cross-validation

### 6.4 Run training

Click **Train** on the BCI_Trainer node. It processes all the data flowing through the pipeline and outputs a trained model.

### 6.5 Save the model

The trained model is available as an output. You can use it in an online inference pipeline.

## Step 7: Online Inference

For real-time classification, you need a different pipeline:

```
LSLInlet → Preprocessing → EA → TS-FBCSP → Predictor
```

### Key differences from offline

- **Input**: LSLInlet receives live EEG data (not a file)
- **Euclidean Alignment**: normalizes incoming data to match the training subject
- **TS-FBCSP**: extracts tangent-space features from filter-bank CSP
- **Predictor**: applies the trained model to classify each trial in real-time

See the workflow `tsfbcsp_online_inference.json` for a complete example.

## Step 8: Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `Ctrl+S` | Save workflow |
| `Ctrl+O` | Open workflow |
| `Ctrl+E` | Export as PNG/PDF/SVG |
| `Ctrl+F` | Fit to scene |
| `Ctrl+0` | Reset zoom to 100% |
| `Ctrl++` | Zoom in |
| `Ctrl+-` | Zoom out |
| `Space` + drag | Pan the canvas |
| `Del` | Delete selected node/cable |
| `F1` | Open full documentation |
| `Shift+F1` | Open docs for selected node |
| `Ctrl+F1` | Quick Help dialog |
| `F9` | Start/stop metrics |

## Next Steps

- Explore the [Nodes Catalog](nodes/index.md) to see all available nodes
- Read the [User Guide](guide.md) for detailed workflow examples
- Check the [Glossary](glossary.md) for BCI/EEG terminology
- Try the pre-built workflows in the `workflows/` directory
