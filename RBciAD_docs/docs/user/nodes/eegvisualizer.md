# EEGVisualizer

**Category:** Output Nodes

**Language:** Python

**Source:** `eeg_visualizer_plugin.py`

## Summary
Simple real-time EEG viewer — displays raw MNE Raw data with selectable channels.

## Inputs
| Name | Description |
|---|---|
| raw | MNE Raw object — the continuous EEG signal to display |

## Outputs
_None_

## Parameters
_None_

## Usage
Connect an MNE Raw object to the raw input. Select channels in the collapsible panel to focus on specific traces.

## Gotchas
- Only accepts MNE Raw objects (not raw numpy arrays); use EEGLiveDisplay for segment arrays.
- Displays up to 1500 samples from the beginning of the Raw buffer — not a scrolling window.
- Channel list auto-populates on first data or when channel count changes.

