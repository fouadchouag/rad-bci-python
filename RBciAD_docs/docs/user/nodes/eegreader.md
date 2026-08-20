# EEGReader

**Category:** Input Nodes

**Language:** Python

**Source:** `eeg_reader_plugin.py`

## Summary
Load EDF EEG files using MNE-Python. Outputs an MNE Raw object.

## Inputs
_None_

## Outputs
| Name | Description |
|---|---|
| raw | mne.io.Raw — the loaded EEG recording (preloaded) |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| filepath | path |  |  | EDF file to load (set via Load button) |

## Usage
Place at the start of your pipeline. Click "Load EDF File" in the properties panel to select a file. Connect "raw" output to downstream nodes.

## Gotchas
- Uses mne.io.read_raw_edf — only EDF format is supported (not BDF/GDF/FIF).
- Large files are fully preloaded into memory.
- Ensure the file contains EEG channels (not just EOG/ECG).
- The output is an MNE Raw object — connect to MNE-compatible nodes or a slicer.

