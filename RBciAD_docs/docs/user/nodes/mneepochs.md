# MNEEpochs

**Category:** Segmentation

**Language:** Python

**Source:** `mne_epochs_plugin.py`

## Summary
Create mne.Epochs from an MNE Raw object plus events (explicit or auto-extracted from annotations).

## Inputs
| Name | Description |
|---|---|
| raw | mne.io.Raw — the continuous recording to segment into epochs |
| events | np.ndarray (N, 3) — optional explicit events; if None, events are extracted from annotations |
| event_id | dict \| int \| str \| None — event_id mapping for mne.Epochs; None = all events |
| tmin | float — epoch start time in seconds relative to event (default -0.2) |
| tmax | float — epoch end time in seconds relative to event (default 0.8) |
| baseline | tuple (start, end) \| None — baseline correction window in seconds; None = no baseline |
| picks_eeg_only | bool — restrict to EEG channels (default True) |
| preload | bool — load data into memory immediately (default True) |
| detrend | None \| 0 \| 1 — detrending mode; None=off, 0=constant, 1=linear |
| reject_by_annotation | bool — reject epochs overlapping annotated bad segments (default True) |

## Outputs
| Name | Description |
|---|---|
| epochs | mne.Epochs — the epoched data (or None if no valid events) |
| events | np.ndarray (N, 3) — the events array actually used |
| config_out | dict — exported configuration snapshot |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| event_id | any |  |  | dict\|int\|str\|None — event ID filter; None means use all detected events |
| tmin | float |  |  | Epoch start (s) relative to each event |
| tmax | float |  |  | Epoch end (s) relative to each event |
| baseline | tuple\|None |  |  | Baseline window (start, end) in seconds; None to skip |
| picks_eeg_only | bool |  |  | Restrict epochs to EEG channels |
| preload | bool |  |  | Load epoch data into memory immediately |
| detrend | int\|None |  |  | Detrending: None=off, 0=constant, 1=linear |
| reject_by_annotation | bool |  |  | Drop epochs that overlap bad annotations |

## Usage
Connect a Raw object. Optionally supply events array and event_id. Routed epochs go to feature extraction or classifier nodes.

## Gotchas
- If no events array is supplied, events are auto-extracted via mne.events_from_annotations — the Raw must have annotations.
- If event_id is a string and no matching annotation is found, output will be None.
- Setting preload=False may cause issues with downstream nodes that need in-memory data.
- Caching skips re-epoching if the same raw, parameters, and events signature arrive again.

