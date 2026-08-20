# MNE Compute SSP Projs

**Category:** Transform Nodes

**Language:** Python

**Source:** `mne_ssp_projs_plugin.py`

## Summary
Compute SSP projectors for EOG/ECG artifact rejection on MNE Raw objects.

## Inputs
| Name | Description |
|---|---|
| raw | mne.io.Raw — input EEG/MEG Raw object |

## Outputs
| Name | Description |
|---|---|
| raw | mne.io.Raw — same Raw object with projectors added to raw.info["projs"] (NOT applied to signal) |
| status | str — human-readable status message |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| n_eog | int |  |  | Number of EOG SSP projectors to compute. |
| l_freq_eog | float |  |  | Low cutoff frequency (Hz) for EOG filter. |
| h_freq_eog | float |  |  | High cutoff frequency (Hz) for EOG filter. |
| ch_name_eog | str |  |  | EOG channel name (empty = auto-detect). |
| n_ecg | int |  |  | Number of ECG SSP projectors to compute. |
| l_freq_ecg | float |  |  | Low cutoff frequency (Hz) for ECG filter. |
| h_freq_ecg | float |  |  | High cutoff frequency (Hz) for ECG filter. |
| ch_name_ecg | str |  |  | ECG channel name (empty = auto-detect). |

## Usage
Connect an MNE Raw node upstream. Use the UI buttons to compute EOG/ECG projectors, or create virtual reference channels first if no dedicated EOG/ECG channel exists.

## Gotchas
- Requires MNE-Python (pip install mne).
- Projectors are ADDED to raw.info["projs"] but NOT applied to the signal — use a downstream node with raw.apply_proj() to activate them.
- If no EOG/ECG channel is found, try creating a virtual EOG (A-B) or ECG channel first.
- Virtual EOG is created as a bipolar subtraction of two channels and marked as eog type.
- Virtual ECG is created from a single channel or EEG mean and marked as ecg type.
- Calling "Compute EOG/ECG" multiple times adds projectors cumulatively (remove_existing=False).

