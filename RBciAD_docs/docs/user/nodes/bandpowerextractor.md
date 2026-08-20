# BandPowerExtractor

**Category:** Features

**Language:** Python

**Source:** `mne_bandpower_extractor_plugin.py`

## Summary
Aggregate PSD into canonical frequency bands (delta/theta/alpha/beta/gamma) as absolute or relative power.

## Inputs
| Name | Description |
|---|---|
| psd | np.ndarray (n_channels, n_freqs) — power spectral density |
| freqs | np.ndarray (n_freqs,) — frequency axis corresponding to the PSD columns |
| ch_names | list[str] — optional channel names for labeling |
| psd_is_db | bool — set True if PSD values are in dB (10·log10); will be converted back to linear before integration |
| relative | bool — if True, normalize each band by total power per channel (sums to 1) |

## Outputs
| Name | Description |
|---|---|
| bandpowers | np.ndarray float32 (n_channels, n_bands) — power per channel per band |
| band_labels | list[str] — band names (e.g. ["delta","theta","alpha","beta","gamma"]) |
| ch_names | list[str] — channel names (passed through or auto-generated) |
| info | dict — metadata: relative, psd_is_db, bands list of (label, lo, hi) |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| psd_is_db | bool |  |  | Set True if PSD input is in dB; linear conversion is applied internally |
| relative | bool |  |  | Normalize band power by total power per channel |
| bands | list[tuple] |  |  | Frequency band definitions as (label, f_lo, f_hi) |

## Usage
Connect PSD and freqs outputs from a PSDWelch node. Adjust band edges and options in the properties panel.

## Gotchas
- Band integration is done by summing PSD bins (not trapezoidal); this is appropriate for Welch PSD which is already averaged.
- If psd_is_db=True, values are converted to linear (10^(x/10)) before summing — summing dB directly would be meaningless.
- When a band range contains no frequency bins, that band gets zero power.
- The number of output bands equals the number of entries in the band list.

