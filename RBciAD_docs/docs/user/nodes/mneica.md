# MNEICA

**Category:** Preprocessing

**Language:** Python

**Source:** `mne_ica_plugin.py`

## Summary
ICA decomposition with automatic EOG/ECG artifact detection and removal on Raw or Epochs.

## Inputs
| Name | Description |
|---|---|
| raw | mne.io.Raw or mne.Epochs — input data for ICA fitting and artifact rejection |
| n_components | int \| None — number of ICA components; None = auto (capped at 25 or n_EEG channels) |
| method | str — ICA algorithm: "fastica", "picard", or "infomax" (default "fastica") |
| decim | int \| None — decimation factor for fitting; None = auto-decimate if sfreq &gt; 300 Hz |
| picks_eeg_only | bool — restrict ICA to EEG channels (default True) |
| detect_eog | bool — run EOG artifact detection on ICA components (default True) |
| detect_ecg | bool — run ECG artifact detection on ICA components (default False) |
| apply | bool — if True, apply ICA cleaning to the output copy (default True) |

## Outputs
| Name | Description |
|---|---|
| raw | mne.io.Raw or mne.Epochs — cleaned copy (or original if apply=False or no bads found) |
| ica | mne.preprocessing.ICA — the fitted ICA object |
| bad_components | list[int] — indices of components flagged as artifacts |
| report | str — human-readable summary of the ICA fit |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| n_components | int\|None |  |  | Number of ICA components (0 or None = auto) |
| method | str | fastica |  | ICA method: "fastica", "picard", or "infomax" |
| decim | int\|None |  |  | Decimation factor for fitting (0 or None = auto) |
| picks_eeg_only | bool |  |  | Fit ICA on EEG channels only |
| detect_eog | bool |  |  | Auto-detect EOG artifact components |
| detect_ecg | bool |  |  | Auto-detect ECG artifact components |
| apply | bool |  |  | Apply ICA artifact removal to the output |

## Usage
Connect a Raw or Epochs object. The plugin fits ICA (with anti-freeze heuristics), detects artifact components, and optionally removes them.

## Gotchas
- For Raw data, ICA is fit on a centered 120 s window and the data is high-pass filtered at 1 Hz internally for fitting.
- For Epochs, at most 400 epochs are used for fitting to avoid excessive memory usage.
- If sfreq > 300 Hz, auto-decimation is applied unless a manual decim value is set.
- Caching avoids re-fitting when the same object and parameters are supplied again.
- The ICA object is always emitted so downstream nodes can inspect or further manipulate it.

