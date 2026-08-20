# BandpowerFeatures

**Category:** Processing Nodes

**Language:** Python

**Source:** `bandpower_features_plugin.py`

## Summary
Extract per-band power features from EEG segments using Welch PSD estimation.

## Inputs
| Name | Description |
|---|---|
| segment | 2D float [channels x samples] — EEG data window or epoched array |
| sfreq | float — sampling frequency in Hz (required) |
| ch_names | list[str] — optional channel names (not used in computation, but accepted) |

## Outputs
| Name | Description |
|---|---|
| features | 1D float ndarray — concatenated band powers (flattened from features_matrix) |
| features_matrix | 2D float ndarray [channels x bands] — per-channel band power values |
| features_dim | int — total number of features (n_ch * n_bands) |
| band_labels | list[str] — band names in order (e.g. ["delta","theta","alpha","beta","gamma"]) |
| status | str — status message |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| bands | str | delta:1-4,theta:4-8,alpha:8-13,beta:13-30,gamma:30-45 |  | Band specification as comma-separated name:lo-hi pairs in Hz. |
| nperseg | int |  |  | Welch segment length (samples). Must be ≤ data length. Larger values give better frequency resolution. |
| overlap | float |  |  | Overlap ratio (0.0–0.9) between Welch segments. Higher overlap reduces variance. |

## Usage
Connect a windowed EEG segment and a sampling frequency. Outputs per-channel band power features for ML classification or regression.

## Gotchas
- sfreq is required — the node outputs nothing if it is missing or ≤ 0.
- nperseg is clamped to the data length if the segment is shorter.
- Falls back to a plain FFT windowed periodogram if SciPy is not installed.
- Orientation is auto-detected: if rows > cols, the segment is transposed to (n_ch, n_t).
- The flat features vector is ordered as [ch0_band0, ch0_band1, ..., ch1_band0, ...].
- Low-frequency bands (e.g. delta < 1 Hz) require a sufficiently long segment.

