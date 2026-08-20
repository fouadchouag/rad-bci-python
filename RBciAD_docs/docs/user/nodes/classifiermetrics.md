# ClassifierMetrics

**Category:** ML

**Language:** Python

**Source:** `classifier_metrics_plugin.py`

## Summary
Evaluates a binary dataset {X, y, y_names} from an upstream EEGClassifier using StratifiedKFold cross-validation with a StandardScaler + LogisticRegression pipeline. Displays accuracy ± std, precision/recall, and confusion matrix.

## Inputs
| Name | Description |
|---|---|
| dataset | dict — {X: np.ndarray[N,d], y: np.ndarray[N], y_names: [str,str]} |
| config_in | dict (optional) — {"folds": int} |
| metrics_conf | dict (optional) — merged with config_in |

## Outputs
| Name | Description |
|---|---|
| config_out | dict — {"folds": int} current fold count |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| folds | int |  |  | Number of CV folds (2..10) |

## Usage
Connect a dataset dict (X, y, y_names) from EEGClassifier. Click "Evaluate (CV)" in the UI to run cross-validation. Folds can be adjusted via UI spinner or config_in.

## Gotchas
- Model-version mismatch can reduce accuracy.
- Binary classification only — labels are forced to [0, 1]; y_names is truncated to first 2 entries.
- Requires scikit-learn; shows install message if missing.
- Needs at least 6 samples and both classes present; actual folds = min(requested, smallest class count).
- Evaluation runs a StandardScaler + LogisticRegression pipeline, not the upstream model.

