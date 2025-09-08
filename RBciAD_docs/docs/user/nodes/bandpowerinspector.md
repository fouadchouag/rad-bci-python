# BandpowerInspector

**Category:** Output Nodes

**Language:** Python

## Summary
Inspecteur bandpower avec:

## Inputs
| Name | Description |
|---|---|
| segment | 2D float [ch x samples] or epochs |
| sfreq | float (Hz) |

## Outputs
| Name | Description |
|---|---|
| features | array/dict |
| freqs | optional freqs |
| psd | optional PSD |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| fmin | float | 1.0 | Hz | Lower frequency |
| fmax | float | 40.0 | Hz | Upper frequency |

## Usage
Connect windowed or epoched data; feed features to ML nodes.

## Gotchas
- Use adequate window length for low frequencies.

