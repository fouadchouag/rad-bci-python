# ClassifierMetrics_1

**Category:** ML

**Language:** Python

**Source:** `classifier_metrics_plugin1.py`

## Summary
Evaluates a multi-class dataset {X, y, y_names} using StratifiedKFold cross-validation with a StandardScaler + LogisticRegression pipeline. Displays accuracy ± std, macro-F1, and confusion matrix.

## Inputs
| Name | Description |
|---|---|
| dataset | dict — {X: np.ndarray[N,d], y: np.ndarray[N], y_names: [str,...]} |

## Outputs
_None_

## Parameters
_None_

## Usage
Connect a dataset dict (X, y, y_names) from an upstream data source. Click "Evaluate (CV)" to run cross-validation. Folds are set via UI spinner (2..10).

## Gotchas
- Model-version mismatch can reduce accuracy.
- Multi-class: K is auto-detected from unique y values; y_names is padded with "Class{i}" if too short.
- Requires scikit-learn; shows install message if missing.
- Needs at least 2 samples per class; actual folds = min(requested, smallest class count).
- Unlike ClassifierMetrics, this node has no config_in/config_out — folds are UI-only.

