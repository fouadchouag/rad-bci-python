# LSL_EEG_Inlet

**Category:** Input Nodes

**Language:** Python

**Source:** `lsl_eeg_inlet.py`

## Summary
Inlet LSL générique pour flux EEG (float32, multi-canaux).

## Inputs
_None_

## Outputs
| Name | Description |
|---|---|
| ch_names | List[str] — channel labels from LSL stream metadata |
| data | 2D float32 [samples x channels] — aggregated chunk since last tick |
| last_ts | float — LSL timestamp of the most recent sample |
| sfreq | float (Hz) — nominal sampling rate from LSL stream |
| timestamps | 1D float64 [samples] — LSL timestamps for the emitted chunk |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| chunk_ms | int |  |  | Duration of each LSL pull in milliseconds |
| emit_ms | int |  |  | Interval between emit ticks in milliseconds (QTimer) |
| buffer_max_s | float |  |  | Maximum buffer duration in seconds before dropping old data |

## Usage
Use the UI to refresh/connect to an EEG LSL stream; outputs are emitted periodically via QTimer.

## Gotchas
- Verify channels and sampling rate after connecting.
- Network hiccups may cause gaps—use buffering.
- Outputs are emitted on a QTimer (emit_ms), not synchronously with the pull thread.
- Buffer max is in seconds; old chunks are dropped when exceeded.

