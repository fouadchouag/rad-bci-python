# BandpowerInspector

**Category:** Output Nodes

**Language:** Python

**Source:** `bandpower_inspector_plugin.py`

## Summary
Visual inspector for band power features — displays per-channel band powers as a table or bar chart.

## Inputs
| Name | Description |
|---|---|
| features | dict — nested {channel_name: {band_name: float}} from a BandpowerFeatures or BandpowerExt node |
| band_labels | list[str] — band names to display (auto-inferred from features if not provided) |

## Outputs
_None_

## Parameters
_None_

## Usage
Connect the features output from a BandpowerFeatures, BandpowerExt, or BandpowerExt_param node. Use the toolbar to switch between Table and Bar views, pick channels, or toggle relative percentages.

## Gotchas
- This is a display-only node; it produces no downstream outputs.
- The "Pick channel" dialog filters the table/bars to a single channel; re-clicking the same row resets to All.
- Relative % mode shows each band as a percentage of the total power of the displayed channel(s).
- When "All" is selected in the bar chart, values are averaged across all channels.
- Input features must be a dict of dicts — other formats (list of dicts, array) are normalized but may lose info.
- The node starts hidden (start_hidden = True) to avoid cluttering the canvas.

