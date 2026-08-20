# LSLInletPlugin

**Category:** Input Nodes

**Source:** `lsl_inlet_plugin.py`

## Summary
LSL Inlet — compatible LiveDisplay / SliceFilter

## Inputs
_None_

## Outputs
| Name | Description |
|---|---|
| ch_names | List[str] — channel labels from LSL stream metadata |
| info | dict — stream metadata ({sfreq, ch_names, name, type, uid, n_channels, reset}) |
| segment | 2D float64 [channels x samples] — EEG data chunk |
| sfreq | float (Hz) — nominal sampling rate from LSL stream |
| timestamps | list[float] — LSL timestamps for the emitted chunk |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| chunk_len | int |  |  | Number of samples per LSL pull (chunk length) |

## Usage
Use the UI to search for and connect to any LSL stream. Outputs segment, sfreq, ch_names, timestamps, and info for downstream processing.

## Gotchas
- Segment is transposed to [channels x samples] (n_ch x n_samples) from LSL convention.
- Data is read as float64 (not float32) to match downstream precision.
- Stream selection requires clicking "Rechercher" then "Connecter" in the UI.
- Network hiccups may cause gaps in the stream; the reader loop sleeps 10ms between empty pulls.
- Disconnecting emits None on segment and timestamps outputs to notify downstream.

