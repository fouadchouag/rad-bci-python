# Array → MNE Raw

**Category:** Input Nodes

**Language:** Python

**Source:** `array_to_mne_raw_plugin.py`

## Summary
Convert numeric arrays (segment/samples) to an MNE Raw object.

## Inputs
| Name | Description |
|---|---|
| data | 2D/3D array or list of chunks [ch x samples] |
| sfreq | float — sampling rate (Hz) |
| ch_names | list[str] — channel names |
| title | str — optional title (unused) |

## Outputs
| Name | Description |
|---|---|
| raw | mne.io.RawArray — constructed Raw object |
| status | str — conversion status message |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| units | str | µV |  | Input data units |
| montage | str | standard_1020 |  | Standard montage to apply |
| auto | bool |  |  | Automatically reconvert on input change |

## Usage
Provide data, sfreq, and ch_names; outputs an MNE Raw for downstream MNE nodes.

## Gotchas
- MNE required (pip install mne).
- Data must be numeric (2D/3D array or list of chunks).
- Unit scaling: input values are multiplied by the selected unit (default µV → V). Set to V if data is already in Volts.
- NaN/Inf values in data are replaced with 0.
- Montage is applied only for channels recognized by the standard template.
- Auto mode reconverts on every input change.

