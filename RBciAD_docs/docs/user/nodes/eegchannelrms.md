# EEGChannelRMS

**Category:** Processing Nodes

**Language:** Python

**Source:** `eeg_channel_rms_plugin.py`

## Summary
Compute per-channel RMS (Root Mean Square) values from an EEG segment or MNE Raw object.

## Inputs
| Name | Description |
|---|---|
| raw | mne.io.Raw — MNE Raw object (used if segment is not provided) |
| segment | 2D float [channels x samples] — EEG data (takes precedence over raw) |
| ch_names | list[str] — optional channel names for ordering and labeling the output |
| window_s | float — window length in seconds for Raw mode (default 1.0); 0 = full data |

## Outputs
| Name | Description |
|---|---|
| values | dict[str, float] — per-channel RMS amplitude |
| ch_names | list[str] — channel names corresponding to the values dict |
| status | str — status message |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| window_s | float |  |  | Window length in seconds for Raw mode. Uses the last N seconds of data. Set to 0 for full data. Configurable from the UI spinbox. |

## Usage
Connect an EEG segment or MNE Raw object. Outputs per-channel RMS values as a dict, suitable for driving topographic or scalp-map visualizations.

## Gotchas
- If both segment and raw are provided, segment takes precedence.
- For Raw mode, if window_s is 0 or not set, the entire recording is used.
- MNE is required for Raw mode; segment mode works without MNE.
- If ch_names is provided and its length matches the number of channels, it is used for labeling; otherwise auto-generated (Ch0, Ch1, ...).
- Segment orientation is auto-detected: if rows < cols it is treated as (n_ch, n_t).
- Designed as a simple scalar driver for ScalpTopomap3D or similar visualization nodes.

