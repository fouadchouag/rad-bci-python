# EEGLiveDisplay

**Category:** Output Nodes

**Language:** Python

**Source:** `eeg_live_display_plugin.py`

## Summary
Real-time EEG display with scrolling traces. Supports both raw (continuous) and segment modes.

## Inputs
| Name | Description |
|---|---|
| raw | MNE Raw object — for continuous raw display mode |
| segment | 2D float [channels x samples] — for segment display mode |
| ch_names | list[str] — channel names (used to populate channel selector) |
| sfreq | float — sampling frequency (Hz) |
| info | dict — metadata keys: reset (bool), seg_index (int), seg_total/total_segments (int), seg_len_s (float) |

## Outputs
| Name | Description |
|---|---|
| config_out | dict — current parameter state (loop, window_s, step_s, seg_len_auto, seg_len_manual, force_nch, max_points, max_fps) |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| loop | bool |  |  | Loop playback for RAW mode |
| window_s | float |  |  | Display window duration (seconds) |
| step_s | float |  |  | RAW scroll step (seconds) |
| seg_len_auto | bool |  |  | Auto-detect segment length from incoming data |
| seg_len_manual | float |  |  | Manual segment length override (seconds); only used when seg_len_auto is False |
| max_points | int |  |  | Max plot points per trace (decimation limit) |
| max_fps | int |  |  | Max rendering frame rate (5–120) |
| force_nch | int |  |  | Force number of displayed channels (0 = auto/all) |

## Usage
Connect upstream EEG data (raw or segment). Adjust window size, scroll speed, and FPS in the properties panel.

## Gotchas
- High max_fps can drop performance on slow machines; start with 20–30.
- max_points controls decimation — lower values = smoother but less detail.
- In RAW mode, data must be streamed continuously (e.g., from LSLInlet).
- Requires MNE for raw mode; segment mode accepts plain numpy arrays.
- Segment mode needs sfreq input to compute time axis; without it, time display is broken.
- force_nch truncates channels from the top — use channel selector to pick specific channels.

