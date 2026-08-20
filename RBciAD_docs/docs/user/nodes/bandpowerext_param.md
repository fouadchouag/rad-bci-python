# BandpowerExt_param

**Category:** Processing Nodes

**Language:** Python

**Source:** `bandpower_ext_param_plugin.py`

## Summary
Extract per-channel band power features using a built-in Welch-like estimator (no SciPy required).

## Inputs
| Name | Description |
|---|---|
| segment | 2D float [channels x samples] — EEG data (auto-oriented to channels-first) |
| ch_names | list[str] — optional channel names (auto-generated as Ch1, Ch2, ... if missing) |
| sfreq | float — sampling frequency in Hz (defaults to 250 Hz if not provided) |

## Outputs
| Name | Description |
|---|---|
| features | dict — nested {channel_name: {band_name: float_value}} |
| band_labels | list[str] — band names in order for the selected preset |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| preset | str | MI (alpha,beta) |  | Band preset: "MI (alpha,beta)" → [alpha, beta] or "Full (delta,theta,alpha,beta)" → [delta, theta, alpha, beta]. Selectable from UI combo box. |
| relative | bool |  |  | If True, band powers are normalized by total power in the 1–40 Hz range (relative power). Toggle from UI checkbox. |
| nperseg | int |  |  | Welch segment length in samples (32–4096). Clamped to data length if shorter. Configurable from UI. |

## Usage
Connect an EEG segment and optionally sfreq/ch_names. Select preset and relative mode from the collapsible parameters section. Outputs per-channel band power dict.

## Gotchas
- sfreq defaults to 250 Hz if not provided — ensure upstream supplies it for correct frequency bands.
- Relative mode divides by total power in 1–40 Hz; bands outside this range are not affected by normalization.
- The Welch implementation is simplified (no SciPy); uses Hanning window and 50% hop.
- If segment is 1D, it is treated as a single channel.
- Band definitions are fixed per preset and cannot be edited freely from the UI.
- The "Full" preset uses [1–4, 4–8, 8–12, 13–30] Hz (note: alpha starts at 8 not 8.5).

