# MNEBandpassFilter

**Category:** Preprocessing

**Language:** Python

**Source:** `mne_bandpass_filter_plugin.py`

## Summary
Apply MNE-Python bandpass filtering to an MNE Raw object. Supports high-pass, low-pass, and FIR phase options.

## Inputs
| Name | Description |
|---|---|
| raw | MNE Raw object — the recording to filter |

## Outputs
| Name | Description |
|---|---|
| raw | MNE Raw object — filtered copy (in-place if possible) |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| l_freq | float |  |  | High-pass cutoff frequency (Hz); 0 = no high-pass |
| h_freq | float |  |  | Low-pass cutoff frequency (Hz); None = no low-pass |
| picks_eeg_only | bool |  |  | Restrict filtering to EEG channels only |
| phase | str | zero |  | FIR filter phase: "zero" or "zero-double" |

## Usage
Connect an MNE Raw object (from EEGReader). Set l_freq (high-pass) and h_freq (low-pass) in the properties panel.

## Gotchas
- Filter length must be appropriate for the sampling rate — too short = poor stopband.
- Edge effects are more pronounced on short segments.
- The node caches filtered results — re-filtering with same params is instant.

