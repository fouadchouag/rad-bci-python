# MNENotchFilter

**Category:** Preprocessing

**Language:** Python

## Summary
MNENotchFilterPlugin (final)

## Inputs
| Name | Description |
|---|---|
| raw | mne.Raw (opt.) |
| segment | 2D float [ch x samples] (opt.) |
| sfreq | float (Hz if segment) |

## Outputs
| Name | Description |
|---|---|
| raw | filtered Raw |
| segment | filtered array |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| hp | float\|None | 1.0 | Hz | High-pass cutoff |
| lp | float\|None | 40.0 | Hz | Low-pass cutoff |
| notch | float\|None | 50.0 | Hz | Notch (mains) |

## Usage
Insert after a reader or inlet; tune band edges.

## Gotchas
- Choose FIR/IIR consistent with sfreq.
- Mind edge effects on short windows.

