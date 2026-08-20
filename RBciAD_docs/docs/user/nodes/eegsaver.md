# EEGSaver

**Category:** Output Nodes

**Language:** Python

**Source:** `eeg_saver.py`

## Summary
Save EEG data (MNE Raw or numpy segments) to disk in multiple formats.

## Inputs
| Name | Description |
|---|---|
| raw | mne.io.Raw — continuous EEG object; saved directly to FIF/EDF/BDF/BrainVision |
| segment | 2D float [channels x samples] — numpy array segments (accumulated during recording) |
| ch_names | list[str] — channel names (used when saving numpy segments) |
| sfreq | float — sampling frequency (Hz); used when saving numpy segments |
| markers | dict or list — event markers (keys: t/time, label, dur, mode) |

## Outputs
| Name | Description |
|---|---|
| status | str — save status/error message |
| saved_path | str — path of the last successfully saved file |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| format | str | FIF |  | Output format: FIF, BrainVision, EDF, BDF, CSV, NPZ, or MAT |
| max_buffer_sec | float |  |  | Maximum recording buffer duration (seconds) before oldest data is dropped |
| auto_increment | bool |  |  | Auto-increment filename suffix (_001, _002, …) to avoid overwrites |

## Usage
Connect raw/segment data and set an output path via the UI. Supports snapshot save and continuous recording with auto-increment.

## Gotchas
- MNE is required for FIF/EDF/BDF/BrainVision formats; CSV/NPZ/MAT work without it.
- SciPy is required for MAT (Matlab) format.
- When saving numpy segments, sfreq and ch_names inputs must be connected or data will have dummy names.
- µV input checkbox: if checked, data is multiplied by 1e-6 before saving (converts µV to V for MNE).
- Markers are embedded as MNE Annotations for FIF/EDF formats, or saved as separate .markers.csv for CSV format.
- Recording buffer accumulates segment input only (not raw); raw is saved as-is on "Save now".

