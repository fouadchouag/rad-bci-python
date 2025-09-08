# MNEEpochsToSegments

**Category:** Segmentation

**Language:** Python

## Summary
MNEEpochsToSegments

## Inputs
| Name | Description |
|---|---|
| events | array/list (optional) |
| raw | mne.Raw |

## Outputs
| Name | Description |
|---|---|
| epochs | mne.Epochs (if events) |
| segment | 2D float [ch x samples] |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| tmin | float | -0.2 | s | Epoch start |
| tmax | float | 0.8 | s | Epoch end |

## Usage
Connect Raw; optionally provide events; route to features/ML.

## Gotchas
- Check event alignment and baseline.

