# EEGClassifier_1

**Category:** ML

**Language:** Python

**Source:** `eeg_classifier_plugin1.py`

## Summary
Multi-class (2-6) EEG classifier with record-train-predict workflow and optional auto-feature extraction.

## Inputs
| Name | Description |
|---|---|
| features | dict[channel_name -&gt; {band_name: value}] — precomputed bandpower features |
| band_labels | list[str] — ordered band names for the feature dict |
| segment | 2D array [ch x samples] — raw EEG segment (fallback if features is None) |
| sfreq | float — sampling frequency in Hz (required when using segment fallback) |
| ch_names | list[str] — channel names (required when using segment fallback) |

## Outputs
| Name | Description |
|---|---|
| pred_label | str — predicted class name |
| pred_conf | float — max probability (0..1) |
| pred_idx | int — index of predicted class |
| proba | dict[class_name -&gt; float] — probability per class |
| dataset | dict {X, y, y_names, feature_mode, bands} — emitted on every sample for metrics nodes |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| feature_mode | str | mean_all |  | "mean_all" (average bandpower across channels) or "c3c4_ab" (C3/C4 alpha+beta). Set via UI combo. |
| num_classes | int |  |  | Number of classes (2-6), set via UI spin box. |
| min_per_class | int |  |  | Minimum samples per class required before training is enabled. |

## Usage
Connect features+band_labels (preferred) or segment+sfreq+ch_names (auto-extract). Record samples per class, train, then predictions stream on pred_label/pred_conf/pred_idx/proba.

## Gotchas
- Requires scikit-learn for training.
- If features is None but segment+sfreq+ch_names are provided, bandpower features are computed automatically (fallback).
- C3/C4 mode silently falls back to MeanAll if C3 or C4 channels are not found.
- Changing the number of classes resets the UI but does NOT clear collected data.
- Saved .pkl files contain the sklearn pipeline — do not load untrusted pickles.

