# MAT → MNE Raw

**Category:** Input Nodes

**Language:** Python

**Source:** `mat_to_mne_raw_plugin.py`

## Summary
Load .mat EEG files (BBCI/BCI-Compatible) and convert to MNE Raw.

## Inputs
_None_

## Outputs
| Name | Description |
|---|---|
| raw | mne.io.RawArray — loaded and scaled recording |
| status | str — load status message |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| filepath | path |  |  | MAT file to load |
| montage | str | standard_1020 |  | Standard montage to apply |
| force_uV | bool |  |  | Force µV → V scaling |

## Usage
Browse and load a .mat file; connects `raw` to downstream MNE-compatible nodes.

## Gotchas
- Requires MNE (pip install mne) plus scipy (v7.2) or h5py (v7.3).
- Auto-detects BBCI (cnt/mrk/nfo), BNCI (X/y/trial), and generic formats.
- "Forcer µV → V" multiplies all data by 1e-6; use if data is in microvolts.
- Int16 data (common in BBCI) is auto-scaled at 0.1 µV per count.
- Montage is applied after loading; non-matching channel names are ignored.

