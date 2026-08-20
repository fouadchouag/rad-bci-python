# EEGClassifier

**Category:** ML

**Language:** Python

**Source:** `eeg_classifier_plugin.py`

## Summary
2-class (Left/Right) EEG classifier with record-train-predict workflow.

## Inputs
| Name | Description |
|---|---|
| features | dict[channel_name -&gt; {band_name: value}] — bandpower features from upstream |
| band_labels | list[str] — ordered band names matching the feature dict |

## Outputs
| Name | Description |
|---|---|
| pred_label | str — predicted class name (e.g. "Left" or "Right") |
| pred_conf | float — confidence of prediction (0..1) |
| dataset | dict {X, y, y_names, feature_mode, bands} — emitted on every sample for metrics nodes |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| feature_mode | str | mean_all |  | "mean_all" (average bandpower across all channels) or "c3c4_ab" (C3/C4 alpha+beta features). Set via UI combo. |

## Usage
Connect features and band_labels from a BandpowerExt node. Record samples for each class via the UI, train, then predictions stream on pred_label/pred_conf.

## Gotchas
- Requires scikit-learn (pip install scikit-learn) for training.
- Train button disabled until both classes have >= 4 samples.
- C3/C4 mode silently falls back to MeanAll if C3 or C4 channels are not found in the feature dict.
- Saved models are pickle files — do not load untrusted .pkl files.
- Model-version mismatch (different bands or feature_mode) can reduce accuracy.
- Class names are read from UI text fields; only two classes are supported.

