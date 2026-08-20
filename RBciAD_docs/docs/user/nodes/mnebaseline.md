# MNEBaseline

**Category:** Segmentation

**Language:** Python

**Source:** `mne_baseline_plugin.py`

## Summary
Apply a time-baseline correction to mne.Epochs via apply_baseline().

## Inputs
| Name | Description |
|---|---|
| epochs | mne.Epochs — the epochs to baseline-correct |
| baseline | tuple (start, end) in seconds, or None — e.g. (None, 0.0) means pre-stimulus to onset |

## Outputs
| Name | Description |
|---|---|
| epochs | mne.Epochs — baseline-corrected copy |
| config_out | dict — exported configuration (auto, baseline_start, baseline_end) |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| auto | bool |  |  | Use default baseline (None, 0.0); when off, manual start/end values are used |
| baseline_start | float |  |  | Manual baseline start in seconds (None = start of epoch) |
| baseline_end | float |  |  | Manual baseline end in seconds (None = end of epoch) |

## Usage
Connect mne.Epochs to the "epochs" input. Set baseline via UI or the "baseline" input tuple (start, end) in seconds.

## Gotchas
- If a baseline tuple is provided via the input pin it takes priority over the UI settings.
- On error, the unmodified epochs are passed through to avoid breaking the pipeline.
- Caching skips re-computation when the same epochs object and baseline parameters arrive again.

