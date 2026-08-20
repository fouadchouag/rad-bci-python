# BCI_Epoch

**Category:** Segmentation

**Language:** Python

**Source:** `bci_epoch_node.py`

## Summary
Extract fixed-length epochs from continuous EEG: sliding window or event-locked mode.

## Inputs
| Name | Description |
|---|---|
| chunk | 2D float [samples x channels] — incoming data chunk |
| sfreq | float — sampling frequency (Hz) |
| ch_names | list[str] — channel names |
| events | dict — {"pos": [int], "typ": [int]} event positions and types |
| reset | any — non-None triggers buffer reset |
| flush | bool — if True, forces emission of partial epochs |
| config_in | dict — generic config from BCI_Config |
| epoch_conf | dict — epoch-specific config |

## Outputs
| Name | Description |
|---|---|
| segment | 2D float [samples x channels] — emitted epoch |
| sfreq | float — sampling frequency |
| ch_names | list[str] — channel names |
| epoch_info | dict — {"mode", "t0", "t1", "end", "epoch_idx", "event_type"?, "event_pos"?} |
| config_out | dict — current parameter state |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| mode | str | Sliding |  | Epoching mode: "Sliding" or "Event-locked" |
| win_sec | float |  |  | Sliding window length (seconds) |
| step_sec | float |  |  | Sliding window step/hop (seconds) |
| drop_incomplete | bool |  |  | Drop incomplete epochs at buffer boundary |
| pre_sec | float |  |  | Event-locked pre-stimulus duration (seconds) |
| post_sec | float |  |  | Event-locked post-stimulus duration (seconds) |
| ev_filter_text | str |  |  | Keep only these event types (comma-separated ints; empty = all) |
| buffer_sec | float |  |  | Ring buffer capacity in seconds |

## Usage
Connect a data chunk stream (from Reader or Filter). Set mode to Sliding or Event-locked.

## Gotchas
- In Event-locked mode, events must be provided via the "events" input pin.
- win_sec must be >= step_sec for sliding mode.
- Large buffer_sec values use more memory but capture longer event contexts.

