# MNESampleLoader

**Category:** Input Nodes

**Language:** Python

**Source:** `mne_sample_loader_plugin.py`

## Summary
Load the MNE sample dataset (sample_audvis_raw.fif).

## Inputs
_None_

## Outputs
| Name | Description |
|---|---|
| raw | mne.io.Raw — loaded sample recording |
| status | str — load status message |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| duration_s | float |  | s | Duration to keep (cropped from start) |
| preload | bool |  |  | Preload data into memory |

## Usage
Place at pipeline start; connect `raw` to a slicer or MNE Viewer.

## Gotchas
- First call downloads the MNE sample dataset (~2GB) via mne.datasets.sample.
- Data is loaded from sample_audvis_raw.fif (auditory/visual paradigm).
- Duration is cropped from the beginning (tmin=0).

