# MNEAverageReference

**Category:** Preprocessing

**Language:** Python

**Source:** `mne_average_reference_plugin.py`

## Summary
Apply average re-referencing to EEG channels of a Raw or Epochs object.

## Inputs
| Name | Description |
|---|---|
| raw | mne.io.Raw or mne.Epochs — input recording to re-reference |

## Outputs
| Name | Description |
|---|---|
| raw | mne.io.Raw or mne.Epochs — copy with average reference applied (or projected) |
| config_out | dict — current configuration snapshot (as_projection) |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| as_projection | bool |  |  | If True, add an average-EEG projector without applying it immediately |

## Usage
Connect an MNE Raw or Epochs object. The re-referenced copy is emitted on the "raw" output.

## Gotchas
- If no EEG channels are found, the input is passed through unchanged.
- When as_projection=True the data itself is not altered; the projector must be applied later.
- Operates on a copy — the original object is never mutated.
- Caching skips re-computation if the same object and parameters are provided again.

