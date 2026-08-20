# LSL Outlet

**Category:** Output Nodes

**Language:** Python

**Source:** `lsl_outlet_plugin.py`

## Summary
LSL Outlet — publish pipeline output as LSL stream (sink node).

## Inputs
| Name | Description |
|---|---|
| segment | 2D float [channels x samples] — EEG data to push |
| sfreq | float (Hz) — sampling rate for outlet creation |
| ch_names | List[str] — channel labels written into LSL stream metadata |

## Outputs
_None_

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| stream_name | str | BenchmarkOutput |  | LSL stream name to publish |
| stream_type | str | EEG |  | LSL stream type |
| source_id | str | rbciad_lsl_outlet |  | Source ID for LSL (unique per device) |

## Usage
Connect segment, sfreq, and ch_names from any upstream node. The outlet is created automatically on the first segment arrival.

## Gotchas
- Requires pylsl installed (pip install pylsl).
- The outlet is created lazily on first incoming segment; changing parameters after creation requires disconnecting the input.
- Segment must be 2D numpy array (n_channels x n_samples); 1D arrays are rejected.
- Sfreq and ch_names are cached from the most recent execute() call; if they arrive after segment, the first push uses defaults (250 Hz, auto-generated names).
- This is a sink node with no outputs.

