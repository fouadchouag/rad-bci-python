# MNEEpochsLite

**Category:** Segmentation

**Language:** Python

**Source:** `mne_epochs_lite.py`

## Summary
Minimal, robust epoching with automatic event detection (annotations → STIM → fixed-length → manual fallback).

## Inputs
| Name | Description |
|---|---|
| raw | mne.io.Raw — the continuous recording to epoch |
| use_annotations | bool — attempt to extract events from Raw annotations first (default True) |
| epoch_len_s | float — duration of each epoch in seconds (default 1.0) |
| step_s | float — step between epoch onsets in seconds (default 1.0, i.e. no overlap) |

## Outputs
| Name | Description |
|---|---|
| epochs | mne.Epochs — the epoched data (or None if no events found) |
| events | np.ndarray (N, 3) — the events array that was used |
| config_out | dict — exported configuration (use_annotations, epoch_len_s, step_s) |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| use_annotations | bool |  |  | Try to extract events from Raw annotations before falling back |
| epoch_len_s | float |  |  | Duration of each epoch in seconds (minimum 0.05) |
| step_s | float |  |  | Step between epoch onsets in seconds (minimum 0.05) |

## Usage
Connect a Raw object. The plugin auto-detects events and creates fixed-duration epochs. Route output to feature or display nodes.

## Gotchas
- Event detection follows a strict fallback: annotations → STIM channel → fixed-length → manual regular spacing.
- All epochs use tmin=0.0 (no pre-stimulus period) and no baseline correction.
- Picks are always restricted to EEG channels if available.
- epoch_len_s and step_s are clamped to a minimum of 0.05 s.
- If step_s < epoch_len_s the resulting epochs overlap in time.

