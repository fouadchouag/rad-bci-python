# CollapsibleSection

**Category:** Custom

**Source:** `mne_ica_viewer.py`

## Summary
Visualize signals, features or predictions.

## Inputs
| Name | Description |
|---|---|
| segment | 2D float [ch x samples] (or raw/derived) |

## Outputs
_None_

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| scale_uv | float |  | µV | Vertical scale |
| speed | float |  |  | Scroll speed |
| fullscreen | bool |  |  | Show full screen |

## Usage
Connect upstream data; adjust view parameters.

## Gotchas
- High refresh can drop FPS; consider decimation.

