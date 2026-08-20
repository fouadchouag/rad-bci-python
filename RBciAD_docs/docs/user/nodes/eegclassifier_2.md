# EEGClassifier_2

**Category:** ML

**Language:** Python

**Source:** `eeg_classifier_2.py`

## Summary
Advanced BCI trainer: multi-class (2-8) collect, CV cross-validation, train, predict, and dataset import/export.

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
| proba | dict[class_name -&gt; float] — full probability distribution across classes |
| dataset | dict {X, y, y_names, feature_mode, bands} — emitted on every sample |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| feature_mode | str | mean_all |  | "mean_all" or "c3c4_ab" (C3/C4 alpha+beta features). Set via UI combo. |
| num_classes | int |  |  | Number of classes (2-8), set via UI spin box. |
| min_per_class | int |  |  | Minimum samples per class required before training. |
| cv_folds | int |  |  | Number of stratified CV folds (2-12) for cross-validation scoring. |
| class_weight_balanced | bool |  |  | Use sklearn class_weight="balanced" to handle imbalanced classes. |

## Usage
Connect features+band_labels or segment+sfreq+ch_names. Use Collect tab to record samples (Record for continuous, Snap for one-shot). Train tab for cross-validation and model training. Predict tab shows live predictions.

## Gotchas
- Requires scikit-learn for training and cross-validation.
- Segment fallback (segment+sfreq+ch_names) computes bandpower automatically if features is None.
- C3/C4 mode falls back to MeanAll if C3/C4 channels are missing from the feature dict.
- Snap button captures exactly one sample on the next execute(); Record button captures continuously.
- CV folds may be reduced automatically if any class has fewer samples than the requested fold count.
- Export/import uses .npz format (NumPy) — not compatible with .pkl model files.
- Loaded models override current class count and names from the saved file.

