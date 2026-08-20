# EEGUniversalReader

**Category:** Input Nodes

**Language:** Python

**Source:** `mne_universal_reader_mneonly.py`

## Summary
EEGUniversalReader — ultra-fast, tous formats MNE, avec métriques enrichies:

## Inputs
_None_

## Outputs
| Name | Description |
|---|---|
| ch_names | List[str] |
| events | array/list |
| raw | mne.Raw |
| segment | 2D float [ch x samples] |
| sfreq | float (Hz) |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| filepath | path |  |  | EDF/BDF/GDF/FIF/... file to load |
| picks | list\|None |  |  | Channels selection |
| segment_len | float |  | s | Window length for streaming output |

## Usage
Place at pipeline start; connect `raw` to MNE ops or `segment` to streaming ops.

## Gotchas
- Large files: prefer windowed output.
- Check montage and units.

