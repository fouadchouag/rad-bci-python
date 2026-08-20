# BCI_Preproc

**Category:** Preprocessing

**Language:** Python

**Source:** `bci_preproc_node.py`

## Summary
Generic causal preprocessing for EEG: bandpass, notch, CAR, EOG regression, resample, z-score.

## Inputs
| Name | Description |
|---|---|
| segment | 2D float [samples x channels] — raw EEG segment |
| sfreq | float — sampling frequency (Hz) |
| ch_names | list[str] — channel names (optional, for auto EOG detection) |
| config_in | dict — generic config from BCI_Config |
| preproc_conf | dict — preprocessing-specific config |

## Outputs
| Name | Description |
|---|---|
| segment | 2D float [samples x channels] — processed EEG segment |
| sfreq | float — sampling frequency (may change if resampled) |
| ch_names | list[str] — channel names (pass-through) |
| config_out | dict — current parameter state |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| bandpass_lo | float |  |  | Bandpass lower cutoff (Hz) |
| bandpass_hi | float |  |  | Bandpass upper cutoff (Hz) |
| bandpass_order | int |  |  | Butterworth filter order |
| causal | bool |  |  | Use causal (forward-only) filtering |
| notch_base | str | None |  | Notch frequency: "None", "50", or "60" (Hz) |
| notch_harmonics | int |  |  | Number of notch harmonics (0–3) |
| reref_mode | str | NONE |  | Re-referencing: "NONE" or "CAR" |
| eog_idx | str |  |  | Comma-separated EOG channel indices (e.g. "22,23,24") |
| auto_eog | bool |  |  | Auto-detect EOG channels by name |
| target_fs | float |  |  | Target sampling rate after resample; 0 = keep original |
| zscore | bool |  |  | Z-score normalization per channel |

## Usage
Connect upstream EEG segment. Configure filter bands, notch, reref, and z-score in the properties panel.

## Gotchas
- Causal filtering avoids phase distortion but has weaker stopband attenuation.
- EOG regression requires EOG channels to be selected (manually or via auto_eog).
- Resampling changes sfreq — downstream nodes must handle the new rate.

