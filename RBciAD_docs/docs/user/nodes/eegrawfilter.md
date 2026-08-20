# EEGRawFilter

**Category:** Processing Nodes

**Language:** Python

**Source:** `eeg_raw_filter_plugin.py`

## Summary
Temporal filtering (HP/LP/BP/Notch) for MNE Raw objects, with async background thread.

## Inputs
| Name | Description |
|---|---|
| raw | mne.io.Raw — input recording (EEG) |

## Outputs
| Name | Description |
|---|---|
| raw | mne.io.Raw — filtered recording (copy or in-place) |
| info | dict — sfreq, ch_names, filter note |
| sfreq | float — sampling rate (Hz) |
| ch_names | list[str] — channel names |
| config_out | dict — current filter configuration |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| enable_hp | bool |  |  | Enable high-pass filter |
| hp | float |  | Hz | High-pass cutoff frequency |
| enable_lp | bool |  |  | Enable low-pass filter |
| lp | float |  | Hz | Low-pass cutoff frequency |
| enable_notch | bool |  |  | Enable notch filter(s) |
| notch_freqs | str | 50, 100 | Hz | Notch frequencies (comma-separated) |
| method | str | fir |  | Filter method (fir or iir) |
| phase | str | zero |  | Filter phase (fir only) |
| fir_taps | int |  |  | Number of FIR taps (fir only) |
| picks | str | all |  | Channel picks to filter |
| in_place | bool |  |  | Modify Raw object in place |

## Usage
Connect an MNE Raw from a reader; tune HP/LP/Notch and method. Runs in a background thread to keep UI responsive.

## Gotchas
- Runs filtering in a background thread (QThread).
- If a filter is running when params change, the new run is queued.
- "In-place" modifies the source Raw object — use with care.
- Notch frequencies are comma-separated (e.g. "50, 100").
- FIR taps only apply when method=fir; IIR uses Butterworth order.
- Filtering an unloaded Raw will trigger raw.load_data().

