# EvokedViewer

**Category:** Output Nodes

**Language:** Python

**Source:** `evoked_viewer.py`

## Summary
Displays MNE Evoked (ERP) data in butterfly or single-channel mode.

## Inputs
| Name | Description |
|---|---|
| evoked | mne.Evoked or list[mne.Evoked] — evoked/averaged EEG data (if list, first element is used) |
| channel | str or int — optional: force channel selection by name or index (only applies in single-channel mode) |

## Outputs
_None_

## Parameters
_None_

## Usage
Connect an mne.Evoked or list of Evoked objects. Toggle single-channel mode to inspect individual channels.

## Gotchas
- If a list of Evoked is provided, only the first is displayed.
- Single-channel mode requires the checkbox to be enabled in the UI; channel input alone does not activate it.
- The channel input accepts a string (name, case-insensitive) or integer (index).
- Butterfly mode overlays all channels on the same axes — can be dense with many channels.
- Requires MNE to be installed for Evoked data handling.

