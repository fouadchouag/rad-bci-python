# EEGMatReader

**Category:** Input Nodes

**Language:** Python

**Source:** `eeg_mat_reader.py`

## Summary
Read .mat EEG files (BBCI/BCI Competition/generic) and stream segments.

## Inputs
_None_

## Outputs
| Name | Description |
|---|---|
| segment | 2D float array [ch x samples] — streamed EEG chunk |
| ch_names | list[str] — channel names |
| sfreq | float — sampling rate (Hz) |
| info | dict — file metadata (path, style, mode, n_channels) |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| filepath | path |  |  | MAT file path (set via Open button) |
| chunk_s | float |  | s | Chunk duration for Continuous mode |
| overlap_s | float |  | s | Overlap between consecutive chunks |
| mode | str | Trials |  | Playback mode |
| loop | bool |  |  | Loop playback |
| auto_play | bool |  |  | Start playing immediately after load |

## Usage
Place at pipeline start; connect `segment` to streaming processors. Use "Infos fichier" to inspect loaded data.

## Gotchas
- Requires scipy (v7.2 MAT) or h5py (v7.3 HDF5-MAT).
- Auto-detects BBCI (cnt/nfo), BNCI (X/trials), and generic formats.
- Large files: prefer Continuous mode with small chunks.
- Check montage and channel units after loading.

