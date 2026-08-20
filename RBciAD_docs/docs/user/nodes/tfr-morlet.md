# TFR (Morlet)

**Category:** Time-Frequency

**Language:** Python

**Source:** `mne_tfr_morlet_plugin.py`

## Summary
Compute time-frequency representation (TFR) using Morlet wavelets on mne.Epochs, with safe auto-clipping of cycles.

## Inputs
| Name | Description |
|---|---|
| epochs | mne.Epochs — epoched data to compute TFR on |
| fmin | float — minimum frequency in Hz (default 2.0) |
| fmax | float — maximum frequency in Hz (default 40.0) |
| fstep | float — frequency step in Hz (default 1.0) |
| cycles | float — base number of wavelet cycles (default 2.0); clamped per-frequency when auto_clip is on |
| average | bool — if True, return EvokedTFR (averaged across epochs); if False, return AverageTFR per epoch (default True) |
| decim | int — decimation factor for the time axis (default 1, i.e. no decimation) |
| picks_eeg_only | bool — restrict to EEG channels (default True) |
| auto_clip_cycles | bool — automatically clamp cycles and drop frequencies that are too low for the epoch length (default True) |
| min_cycles | float — minimum acceptable clamped cycle count; frequencies below this are dropped (default 0.25) |
| safety_margin | float — safety margin &lt; 1 applied to the max-cycles bound (default 0.98) |

## Outputs
| Name | Description |
|---|---|
| tfr | mne.time_frequency.AverageTFR or mne.time_frequency.EpochsTFR — the computed time-frequency representation |
| freqs | np.ndarray — the actual frequencies used (after potential dropping) |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| fmin | float |  |  | Minimum frequency (Hz) |
| fmax | float |  |  | Maximum frequency (Hz) |
| fstep | float |  |  | Frequency step (Hz) |
| cycles | float |  |  | Base number of Morlet wavelet cycles |
| average | bool |  |  | Average across epochs (EvokedTFR) |
| decim | int |  |  | Time-axis decimation factor |
| picks_eeg_only | bool |  |  | Restrict to EEG channels |
| auto_clip_cycles | bool |  |  | Clamp cycles and drop unsafe low frequencies automatically |
| min_cycles | float |  |  | Minimum clamped cycle count to keep a frequency |
| safety_margin | float |  |  | Safety margin for the max-cycles bound (&lt; 1) |

## Usage
Connect mne.Epochs. Set frequency range, step, and wavelet cycles. Output TFR and freqs for visualization or further analysis.

## Gotchas
- The auto_clip_cycles feature enforces 2·(n_cycles·sfreq/f) < n_times to prevent edge artifacts; low frequencies may be dropped.
- n_jobs is hardcoded to None for MNE compatibility (no parallel execution).
- Uses n_jobs=None instead of "auto" to avoid compatibility issues with some MNE versions.
- If no valid frequencies survive the safety checks, outputs default to (None, None).
- Caching skips re-computation when the same epochs and all parameters match.

