# RawfilterCPlugin

**Category:** Custom

**Language:** C

**Source:** `rawfilter_c_plugin.py`

## Summary
RawFilter_C: custom node.

## Inputs
| Name | Description |
|---|---|
| raw | 2D float [ch x samples] |
| sfreq | float (Hz) |

## Outputs
| Name | Description |
|---|---|
| raw | 2D float [ch x samples] |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| low | float | 1.0 | Hz | High-pass cutoff |
| high | float | 40.0 | Hz | Low-pass cutoff |
| notch | enum | off |  | 0=off / 50/60 Hz |
| q | float | 0.707 |  | Q factor |
| order | int | 2 |  | Filter order |

## Usage
Connect as required by its inputs/outputs; adjust parameters as needed.

