# EEGSliceFilter

**Category:** Processing Nodes

**Language:** Python

**Source:** `eeg_filter_plugin.py`

## Summary
Streaming windowed filter (HP/LP/Notch) with persistent state (FIR or IIR).

## Inputs
| Name | Description |
|---|---|
| segment | 2D float array [ch x samples] — EEG data chunk |
| info | dict — metadata (sfreq, ch_names); optional |
| sfreq | float — sampling rate in Hz (alternative to info) |
| ch_names | list[str] — channel names (alternative to info) |

## Outputs
| Name | Description |
|---|---|
| segment | 2D float array — filtered EEG chunk (same shape) |
| info | dict — metadata passthrough |
| sfreq | float — sampling rate passthrough |
| ch_names | list[str] — channel names passthrough |
| config_out | dict — current filter config snapshot |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| enable_hp | bool |  |  | Enable high-pass filter |
| hp | float |  | Hz | High-pass cutoff frequency |
| enable_lp | bool |  |  | Enable low-pass filter |
| lp | float |  | Hz | Low-pass cutoff frequency |
| enable_notch | bool |  |  | Enable notch filter(s) |
| notch_freqs | str | 50, 100 | Hz | Notch frequencies (comma-separated) |
| notch_q | float |  |  | Notch filter quality factor |
| method | str | fir |  | Filter design method |
| fir_taps | int |  |  | Number of FIR taps (must be odd) |
| iir_order | int |  |  | IIR (Butterworth) filter order |
| bypass | bool |  |  | Bypass all filtering |

## Usage
Connect after a slicer/inlet to filter streaming EEG chunks. Tune HP/LP band edges, notch frequencies, and FIR/IIR method.

## Gotchas
- SciPy required (pip install scipy).
- Filter state persists across chunks; use "Reset state" or change params to reset.
- FIR notch is applied via IIR cascade before FIR HP/LP.
- Mind edge effects on short windows.
- HP cutoff must be < LP cutoff and both < Nyquist (sfreq/2).
- Bypass mode passes data through unfiltered.
- Filters are re-designed when sfreq or ch_names change.

