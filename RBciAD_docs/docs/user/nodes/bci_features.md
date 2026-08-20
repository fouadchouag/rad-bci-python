# BCI_Features

**Category:** ML

**Language:** Python

**Source:** `bci_features_node.py`

## Summary
Extract EEG features: PSD band power, ERP mean windows, or time-domain statistics.

## Inputs
| Name | Description |
|---|---|
| X | 2D float [channels x samples] or 3D [trials x channels x samples] — EEG data (aliases: segment, data) |
| sfreq | float — sampling frequency (Hz) |
| ch_names | list[str] — channel names |
| config_in | dict — generic config from BCI_Config |
| features_conf | dict — features-specific config |

## Outputs
| Name | Description |
|---|---|
| features | dict — {channel_name: {band_name: float}, "GLOBAL": {band_name: float}} |
| band_labels | list[str] — feature dimension labels |
| feature_mode | str — "PSD_bands_rel", "PSD_bands_abs", "ERP_mean_windows", or "TimeStats" |
| config_out | dict — current parameter state |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| mode | str | PSD (bands) |  | Feature mode: "PSD (bands)", "ERP mean windows", or "TimeStats" |
| preset | str | MI |  | Band preset: "MI", "P300", "SSVEP", or "Full" |
| bands_text | str |  |  | Custom bands (e.g. "alpha:8-12; beta:13-30"); empty = use preset |
| relative | bool |  |  | Compute relative PSD (normalized by total power 1–40 Hz) |
| nperseg | int |  |  | Welch PSD window length (samples) |
| erp_wins_text | str | P3:300-450 |  | ERP time windows (e.g. "N1:-100-0; P3:300-450" in ms) |
| erp_t0 | float |  |  | ERP epoch time-zero offset (seconds) |

## Usage
Connect preprocessed EEG segments. Choose mode (PSD/ERP/TimeStats) and band preset (MI/P300/SSVEP).

## Gotchas
- PSD mode requires sufficient segment length (>= nperseg samples).
- Relative PSD normalizes by total power in 1–40 Hz; absolute mode returns raw µV²/Hz.
- ERP mode expects epoch-aligned segments with a defined time-zero.

