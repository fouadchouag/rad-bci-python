# EEGFilterStateful

**Category:** Processing Nodes

**Language:** Python

**Source:** `eeg_filter_stateful.py`

## Summary
Stateful IIR bandpass filter for streaming EEG chunks.

## Inputs
| Name | Description |
|---|---|
| segment | 2D float array [ch x samples] — EEG data chunk |
| sfreq | float — sampling rate in Hz |
| ch_names | list[str] — channel names (passthrough) |

## Outputs
| Name | Description |
|---|---|
| segment | 2D float array — bandpass-filtered chunk |
| sfreq | float — sampling rate passthrough |
| ch_names | list[str] — channel names passthrough |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| low | float |  | Hz | Bandpass lower cutoff (Hz) |
| high | float |  | Hz | Bandpass upper cutoff (Hz) |
| order | int |  |  | Butterworth filter order |

## Usage
Insert after a reader/slicer to bandpass-filter streaming data. Preserves filter state across chunks for phase continuity.

## Gotchas
- SciPy required (pip install scipy).
- IIR bandpass only — no FIR, no separate HP/LP/Notch.
- Filter state persists across chunks; redesign resets state.
- If sfreq changes, filters are re-designed automatically.
- Edge effects on very short windows (< ~5x filter order).

