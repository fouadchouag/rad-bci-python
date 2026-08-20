# AcquisitionManager

**Category:** Input Nodes

**Language:** Python

**Source:** `acquisition_manager.py`

## Summary
AcquisitionManager (léger) — LSL | Emulator | Native (disabled)

## Inputs
_None_

## Outputs
| Name | Description |
|---|---|
| ch_names | List[str] — channel labels from the selected source |
| info | dict — source metadata and status updates ({sfreq, ch_names, name, type, uid, n_channels, reset, status}) |
| segment | 2D float32 [channels x samples] — windowed EEG segment |
| sfreq | float (Hz) — sampling rate of the selected source |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| source | str | LSL |  | Data source driver: LSL, Emulator, or Native (disabled) |
| seg_len_s | float |  |  | Segment length in seconds (0 = auto power-of-2) |
| hop_ratio | float |  |  | Hop ratio (0..1) as fraction of segment length |
| hop_s | float |  |  | Hop in seconds (used only when hop_ratio=0) |
| smoothing | bool |  |  | Apply Hann edge smoothing to segments |

## Usage
Select a source in the UI, scan and pick an LSL stream, then press Start. Segments are emitted automatically via the segmentation engine.

## Gotchas
- Native hardware driver is disabled (placeholder only).
- LSL stream selection requires clicking "Rechercher" then "Choisir…" before Start.
- Segment shape is always [channels x samples] (transposed from LSL convention).
- Segmentation is automatic: seg_len=0 picks a power-of-2 length based on sfreq.
- Emulator generates a 10 Hz + 20 Hz sine signal with configurable noise.

