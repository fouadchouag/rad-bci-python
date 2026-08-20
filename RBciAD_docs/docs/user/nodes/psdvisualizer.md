# PSDVisualizer

**Category:** Output Nodes

**Language:** Python

**Source:** `psd_visualizer.py`

## Summary
Displays Welch PSD curves per channel with optional averaging and dB scaling.

## Inputs
| Name | Description |
|---|---|
| freqs | 1D float array — frequency axis (Hz) from Welch computation |
| psd | 2D float array [channels x frequencies] — power spectral density values |
| ch_names | list[str] — channel names for the channel selector |
| info | dict — optional metadata (not currently used) |

## Outputs
| Name | Description |
|---|---|
| config_out | dict — current config: {average_channels, use_db, max_points} |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| average_channels | bool |  |  | Average PSD across all selected channels into a single curve |
| use_db | bool |  |  | Display power on a logarithmic dB scale (10*log10) |
| max_points | int |  |  | Visual decimation limit — frequencies are downsampled if above this count |

## Usage
Connect freqs and psd outputs from a PSD computation node. Toggle averaging and dB in the collapsible panel.

## Gotchas
- psd must be 2D [n_ch x n_freqs]; 1D or 3D inputs are rejected as shape mismatches.
- freqs and psd shapes must be compatible (psd.shape[1] == freqs.shape[0]).
- dB mode clamps values at 1e-20 floor to avoid log(0) issues.
- Channel selector syncs with upstream ch_names; if names are missing, generic ch1/ch2 labels are used.
- Drawing is throttled to ~25 FPS to avoid UI lag on rapid updates.

