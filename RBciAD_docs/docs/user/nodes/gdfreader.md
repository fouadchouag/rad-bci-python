# GDFReader

**Category:** Input Nodes

**Language:** Python

**Source:** `gdf_reader_plugin.py`

## Summary
Read GDF EEG files using MNE-Python; emits an MNE Raw object.

## Inputs
_None_

## Outputs
| Name | Description |
|---|---|
| raw | mne.io.Raw — loaded GDF recording (preloaded) |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| filepath | path |  |  | GDF file path (set via Load button) |

## Usage
Place at pipeline start; connect `raw` output to slicer or MNE-compatible nodes.

## Gotchas
- Uses mne.io.read_raw_gdf — GDF format only.
- Large files are fully preloaded into memory.
- Check montage and units after loading.

