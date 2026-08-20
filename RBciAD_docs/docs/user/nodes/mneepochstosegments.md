# MNEEpochsToSegments

**Category:** Segmentation

**Language:** Python

**Source:** `mne_epochs_to_segments.py`

## Summary
Stream mne.Epochs one-by-one as segment arrays at a configurable frame rate, for live display.

## Inputs
| Name | Description |
|---|---|
| epochs | mne.Epochs — the epoched data to stream as segments |
| fps | float — playback frame rate in Hz (default 20.0, range 1–60) |
| loop | bool — restart from the first epoch after the last one (default True) |

## Outputs
| Name | Description |
|---|---|
| segment | np.ndarray (n_channels, n_samples) — the current epoch as a 2D array |
| ch_names | list[str] — channel names (emitted once when epochs arrive) |
| sfreq | float — sampling frequency in Hz (emitted once) |
| info | dict — metadata: seg_index, seg_total, seg_len_s, reset flag |
| config_out | dict — exported configuration (fps, loop) |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| fps | float |  |  | Playback speed in frames per second (1–60) |
| loop | bool |  |  | Loop back to the first epoch after reaching the end |

## Usage
Connect mne.Epochs. The plugin buffers all epoch data and emits one segment per timer tick at the configured FPS.

## Gotchas
- All epoch data is loaded into memory (get_data()) when epochs arrive — can be large.
- The timer-based streaming requires a running Qt event loop.
- Channel names and sfreq are emitted once and retained even after streaming stops.
- Calling on_remove() stops the timer and frees the data buffer.

