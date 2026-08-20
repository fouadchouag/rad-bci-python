# MNEBandpowerViewer

**Category:** Output Nodes

**Language:** Python

**Source:** `bandpower_viewer.py`

## Summary
Bar chart of EEG band powers (e.g. theta, alpha, beta), either averaged across channels or per-channel.

## Inputs
| Name | Description |
|---|---|
| bandpowers | 2D float array [channels x bands] — power values per channel per frequency band |
| band_labels | list[str] — labels for each frequency band (e.g. ["delta", "theta", "alpha", "beta"]) |
| ch_names | list[str] — channel names for the channel dropdown selector |

## Outputs
_None_

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| mode | str | avg |  | Display mode: "avg" (mean across all channels) or "single" (one channel via dropdown) |
| sel_ch | int |  |  | Selected channel index when in "single" mode |

## Usage
Connect bandpowers and band_labels from a band-power computation node. Switch between average and single-channel mode in the UI.

## Gotchas
- bandpowers must be 2D [n_channels x n_bands]; 1D or mismatched shapes show "No data".
- band_labels length must match bandpowers.shape[1] for correct bar alignment.
- ch_names is optional — if absent, the channel dropdown is empty and single mode uses index 0.
- No outputs — this is a viewer-only node; use it at the end of a pipeline branch.
- Popup ("Agrandir") syncs with the main view in real time.

