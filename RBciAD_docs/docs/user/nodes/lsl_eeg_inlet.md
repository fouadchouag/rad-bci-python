# LSL_EEG_Inlet

**Category:** Input Nodes

**Language:** Python

## Summary
Inlet LSL générique pour flux EEG (float32, multi-canaux).

## Inputs
_None_

## Outputs
| Name | Description |
|---|---|
| ch_names | List[str] |
| segment | 2D float [ch x samples] |
| sfreq | float (Hz) |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| stream_name | str | EEG |  | LSL stream name to subscribe to |
| chunk_size | int | 256 |  | Samples per pull |
| timeout | float | 0.1 | s | Pull timeout |

## Usage
Start external LSL stream; connect this inlet to processing pipeline.

## Gotchas
- Verify channels and sampling rate.
- Network hiccups may cause gaps—use buffering.

