# PSDBandFeaturesLite

**Category:** Features

**Language:** Python

**Source:** `psd_band_features_lite.py`

## Summary
Compute per-band power features from precomputed frequency arrays and PSD matrix.

## Inputs
| Name | Description |
|---|---|
| freqs | 1D float ndarray — frequency axis in Hz (from upstream PSD node) |
| psd | 2D float [channels x freqs] or 3D [epochs x channels x freqs] — power spectral density |
| ch_names | list[str] — optional channel names (auto-generated as ch1, ch2, ... if missing) |

## Outputs
| Name | Description |
|---|---|
| features | list[dict] — per-channel band power dict, each with keys: ch, delta, theta, alpha, beta, gamma (and *_rel if relative mode is on) |
| config_out | dict — current configuration {"use_relative": bool, "bands": list} |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| use_relative | bool |  |  | If True, adds *_rel keys to output (each band power divided by total integrated power). Toggle from UI checkbox. |

## Usage
Connect a freqs array and PSD matrix from an upstream PSD computation node (e.g., a Welch or FFT node). Outputs per-channel band power features as a list of dicts.

## Gotchas
- This node does NOT compute PSD — it expects precomputed freqs and psd from an upstream PSD node.
- If psd is 3D (epochs), it is averaged across the epoch axis before computing band powers.
- Band definitions are hardcoded: delta [0.5–4], theta [4–8], alpha [8–13], beta [13–30], gamma [30–45] Hz.
- Relative power divides by total integrated power (trapz over full spectrum); if total is 0, relative values are 0.
- The output features list has one dict per channel, each containing the band name as a key.
- Bands are editable via ConfigNode (import_config/export_config), not directly in the UI.
- Frequency axis and PSD matrix dimensions must be compatible (n_freqs must match).

