# MNEDatasetLoader

**Category:** Input Nodes

**Language:** Python

**Source:** `mne_dataset_loader_plugin.py`

## Summary
Load EEGBCI dataset and compute per-channel metric + band powers for topomaps.

## Inputs
_None_

## Outputs
| Name | Description |
|---|---|
| pos | dict[str → tuple(x,y,z)] — 3D channel positions |
| ch_names | list[str] — channel names with montage positions |
| values | dict[str → float] — per-channel metric values (RMS or band power) |
| band_values | dict[str → dict[str → float]] — per-band per-channel power |
| status | str — load status message |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| subject | int |  |  | EEGBCI subject ID (1–109) |
| runs | str | 6 |  | Run numbers (comma-separated, e.g. "6" or "3,7,11") |
| duration_s | float |  | s | Duration of data used for metric computation |
| metric | str | RMS |  | Per-channel metric to compute |

## Usage
Click "Charger" after setting subject/runs; outputs channel positions and values for topographic map visualization.

## Gotchas
- Requires MNE + mne.datasets.eegbci (downloads EEGBCI data on first use).
- Channel names are auto-remapped to standard 10-20/10-05 equivalents.
- Montage is auto-selected from best matching standard template.
- Only EEG channels are used (EOG/ECG/EMG excluded).

