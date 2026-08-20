# PSDWelch

**Category:** Analysis

**Language:** Python

**Source:** `mne_psd_welch_plugin.py`

## Summary
Compute power spectral density via Welch's method from MNE Raw/Epochs or a raw segment array.

## Inputs
| Name | Description |
|---|---|
| raw | mne.io.Raw or mne.Epochs — input recording (primary path) |
| segment | np.ndarray (n_channels, n_samples) — alternative raw array input (requires sfreq) |
| sfreq | float — sampling frequency in Hz (required when using the segment input) |
| ch_names | list[str] — optional channel names when using the segment input |

## Outputs
| Name | Description |
|---|---|
| freqs | np.ndarray (n_freqs,) — frequency axis in Hz |
| psd | np.ndarray float32 (n_channels, n_freqs) — power spectral density |
| ch_names | list[str] — channel names used in the computation |
| info | dict — metadata: sfreq, nyquist, fmin, fmax, n_per_seg, n_overlap, average, mode, n_channels, n_freqs |
| config_out | dict — exported configuration for ConfigNode |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| fmin | float |  |  | Lower frequency bound (Hz) |
| fmax | float |  |  | Upper frequency bound (Hz) |
| seglen_s | float |  |  | Welch window length in seconds |
| overlap_s | float |  |  | Overlap between Welch segments in seconds |
| average | str | mean |  | Welch averaging method: "mean" or "median" |
| eeg_only | bool |  |  | Restrict to EEG channels when using the Raw path |
| max_points | int |  |  | Decimate output to at most this many frequency points |

## Usage
Connect either an MNE Raw/Epochs object OR a segment array with sfreq. Output freqs, psd, and ch_names feed into BandPowerExtractor or viewers.

## Gotchas
- fmax is automatically clamped to just below Nyquist (sfreq/2).
- n_per_seg is auto-reduced if it exceeds the available signal length.
- If the requested fmin–fmax band yields no frequency bins, the range is slightly relaxed.
- When using the segment path, the array is expected as (n_channels, n_samples); rows < cols convention.
- Caching skips re-computation when all parameters and the data signature match.

