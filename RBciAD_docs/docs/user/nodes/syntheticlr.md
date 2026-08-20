# SyntheticLR

**Category:** Input Nodes

**Language:** Python

**Source:** `synthetic_lr_plugin.py`

## Summary
Generate synthetic Left/Right motor-imagery EEG with streaming support.

## Inputs
_None_

## Outputs
| Name | Description |
|---|---|
| raw | mne.io.RawArray — one-shot synthetic recording (on Generate) |
| segment | 2D float array [ch x samples] — streaming EEG chunk |
| info | dict — sfreq, ch_names, name, type, uid, n_channels |
| run | bool — True when streaming starts, False when stops |
| reset | bool — True pulse when streaming stops |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| sfreq | float |  | Hz | Sampling rate |
| duration_s | int |  | s | Total signal duration |
| block_s | float |  | s | Block duration (Left/Right alternation) |
| win_s | float |  | s | Streaming window size |
| overlap | int |  | % | Overlap percentage |
| loop | bool |  |  | Loop streaming |

## Usage
Click "Generate" for a one-shot Raw, or "Start Streaming" for real-time chunks. Connect segment to downstream processors.

## Gotchas
- Generates a deterministic signal (RNG seed=42) for reproducibility.
- 8 channels: C3, C4, CZ, PZ, F3, F4, O1, O2.
- Mu rhythm (~10 Hz) is lateralized: Left blocks → C4 accent, Right → C3 accent.
- Streaming mode outputs raw array chunks, not MNE Raw objects.
- Start/Stop buttons control the streaming timer.

