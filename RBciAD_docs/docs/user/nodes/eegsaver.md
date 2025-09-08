# EEGSaver

**Category:** Output Nodes

**Language:** Python

## Summary
EEGSaver — sauvegarde EEG (Raw MNE ou segment numpy) en plusieurs formats.

## Inputs
| Name | Description |
|---|---|
| epochs | mne.Epochs (opt.) |
| features | array/dict (opt.) |
| raw | mne.Raw (opt.) |
| segment | 2D float [ch x samples] (opt.) |

## Outputs
_None_

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| out_path | path | ./out |  | Target folder |
| format | str | csv |  | File format |
| append | bool | True |  | Append to existing files |

## Usage
Wire any stream you need to archive; set path/format.

## Gotchas
- Ensure write permissions and disk space.

