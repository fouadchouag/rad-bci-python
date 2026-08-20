# PSDTopoViewer

**Category:** Visualization

**Language:** Python

**Source:** `psd_topo_viewer.py`

## Summary
Topomap or bar-chart of average PSD power in a configurable frequency band.

## Inputs
| Name | Description |
|---|---|
| psd | 2D float [channels x frequencies] or 3D [epochs x channels x frequencies] — power spectral density |
| freqs | 1D float array — frequency axis (Hz) |
| ch_names | list[str] — channel names; must match standard_1020 montage for topomap rendering |
| band_low | float — lower frequency bound of the band (default 8.0 Hz) |
| band_high | float — upper frequency bound of the band (default 12.0 Hz) |
| agg | str — aggregation method: "mean" or "median" (default "mean") |
| db | bool — convert power to dB before aggregation (default True) |

## Outputs
| Name | Description |
|---|---|
| noop | None — viewer-only node (output exists for pipeline compatibility) |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| band_low | float |  |  | Lower frequency bound (Hz) for the power band |
| band_high | float |  |  | Upper frequency bound (Hz) for the power band |
| agg | str | mean |  | Aggregation across frequency bins: "mean" or "median" |
| db | bool |  |  | Apply 10*log10 before aggregating |

## Usage
Connect psd, freqs, and ch_names from a PSD computation node. Adjust band range and aggregation in the collapsible panel.

## Gotchas
- Topomap requires at least 3 channels whose names match the MNE standard_1020 montage.
- Falls back to a bar chart when channel names are unrecognized or fewer than 3 match.
- 3D PSD input (epochs x channels x frequencies) is averaged across epochs automatically.
- band_low must be <= band_high; if band_high < band_low, no frequency bins are selected.
- The noop output exists only so the node can be wired into pipelines that require an output pin.

