# MNENotchFilter

**Category:** Preprocessing

**Language:** Python

**Source:** `mne_notch_filter_plugin.py`

## Summary
Apply FIR notch filtering to remove powerline noise (50/60 Hz) and optional harmonics from Raw or Epochs.

## Inputs
| Name | Description |
|---|---|
| raw | mne.io.Raw or mne.Epochs — input data to notch-filter |
| freqs | float \| list[float] — notch center frequency in Hz (default 50.0) |
| harmonics_max | int — include harmonics up to this multiple of the base frequency (0 = none, default 0) |
| picks_eeg_only | bool — restrict filtering to EEG channels only (default True) |
| phase | str — FIR phase type: "zero" or "zero-double" (default "zero") |

## Outputs
| Name | Description |
|---|---|
| raw | mne.io.Raw or mne.Epochs — notch-filtered copy |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| freqs | float |  |  | Base notch frequency in Hz (e.g. 50 or 60) |
| harmonics_max | int |  |  | Max harmonic multiple to also notch (0 = base only) |
| picks_eeg_only | bool |  |  | Apply notch filter to EEG channels only |
| phase | str | zero |  | FIR filter phase: "zero" or "zero-double" |

## Usage
Connect an MNE Raw or Epochs object. Set the fundamental frequency and number of harmonics in the properties panel.

## Gotchas
- Force-loads data before filtering if the Raw object is not preloaded (avoids MNE RuntimeError).
- If freqs is empty or all frequencies are ≤ 0, the input passes through unchanged.
- Caching skips re-filtering when the same object and parameters are provided again.
- On error, the original (unfiltered) object is passed through to avoid breaking the pipeline.

