# MNEResample

**Category:** Preprocessing

**Language:** Python

**Source:** `mne_resample_plugin.py`

## Summary
Resample an MNE Raw or Epochs object to a target sampling frequency.

## Inputs
| Name | Description |
|---|---|
| raw | mne.io.Raw or mne.Epochs — input data to resample |
| sfreq | float — target sampling frequency in Hz (default 256.0) |

## Outputs
| Name | Description |
|---|---|
| raw | mne.io.Raw or mne.Epochs — resampled copy |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| sfreq | float |  |  | Target sampling frequency in Hz (1–4096) |

## Usage
Connect a Raw or Epochs object. Set the target sfreq in the properties panel or via the sfreq input.

## Gotchas
- If the current sfreq already matches the target, the original object is returned unchanged (no copy).
- Force-loads data before resampling if the Raw object is not preloaded.
- Resampling changes the time axis — downstream nodes must handle the new sfreq.
- Caching skips re-computation when the same object and target sfreq arrive again.

