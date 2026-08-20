# MNEAverage

**Category:** Preprocessing

**Language:** Python

**Source:** `mne_average_plugin.py`

## Summary
Compute the mean across epochs to produce an MNE Evoked object.

## Inputs
| Name | Description |
|---|---|
| epochs | mne.Epochs object to average across trials |
| picks_eeg_only | bool — restrict averaging to EEG channels only (default True) |

## Outputs
| Name | Description |
|---|---|
| evoked | mne.Evoked — the result of averaging all epochs (mean method) |
| n_epochs | int — number of epochs that were averaged |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| picks_eeg_only | bool |  |  | Restrict to EEG channels before averaging |

## Usage
Connect an mne.Epochs object to the "epochs" input. The averaged Evoked is emitted on the "evoked" output.

## Gotchas
- Requires MNE-Python to be installed.
- If epochs is None or MNE is missing, outputs default to (None, 0).
- EEG-only picking silently fails if info is unavailable.

