# RawWindowSlicer

**Category:** Processing Nodes

**Source:** `raw_window_slicer_plugin.py`

## Summary
Slices a continuous MNE Raw into overlapping windows via a QTimer.

## Inputs
| Name | Description |
|---|---|
| raw | mne.io.Raw — continuous recording to slice |
| run | bool — True=play, False=pause (optional) |
| reset | bool — True resets read position to 0 (optional) |

## Outputs
| Name | Description |
|---|---|
| segment | 2D float array [ch x samples] — windowed EEG chunk (Volts) |
| info | dict — sfreq, ch_names, file name, type |
| sfreq | float — sampling rate (Hz) |
| ch_names | list[str] — channel names |
| times | np.ndarray — time vector for the current window |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| win_s | float |  | s | Window duration |
| overlap | int |  | % | Overlap percentage between windows |
| loop | bool |  |  | Loop back to start when reaching end |
| honor_ext_run | bool |  |  | Honor external run/reset commands |

## Usage
Connect an MNE Raw; outputs streaming segments with configurable window size and overlap.

## Gotchas
- Timer-based streaming; window timing depends on system timer resolution.
- Auto-unpauses when a new Raw is connected.
- Window is aligned to the end of each step (fixed-size, not overlapping slices).
- If "Honor ext run" is unchecked, external run/reset commands are ignored.
- Loop mode restarts from sample 0 when reaching the end.

