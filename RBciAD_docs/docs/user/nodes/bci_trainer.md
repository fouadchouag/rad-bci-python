# BCI_Trainer

**Category:** ML

**Language:** Python

**Source:** `bci_trainer_node.py`

## Summary
Train a scikit-learn classifier (LogisticRegression or LDA) in a background thread. Outputs a trained model and cross-validation report.

## Inputs
| Name | Description |
|---|---|
| dataset | dict — {"X": ndarray(N,F), "y": ndarray(N,), "y_names": list} |
| config_in | dict — generic config from BCI_Config |

## Outputs
| Name | Description |
|---|---|
| model | trained scikit-learn Pipeline (StandardScaler + classifier) |
| report | dict — cv_mean, cv_std, N, K, labels, cv_confusion, cv_acc, cv_bal_acc, cv_f1_macro, algo, etc. |
| config_out | dict — current parameter state |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| algo | str | LogisticRegression |  | Classifier: "LogisticRegression" or "LDA" |
| cv_k | int |  |  | Number of stratified k-fold CV splits (2–20) |
| balanced | bool |  |  | Use class_weight="balanced" for LogisticRegression |
| holdout | float |  |  | Hold-out test set fraction (0.0 = disabled, 0–0.49) |

## Usage
Connect a dataset dict (from BCICollector). Click "Train" to start. Results appear in the report output.

## Gotchas
- Training runs in a background thread — the UI stays responsive.
- Balance classes for best results; use the "balanced" option for imbalanced data.
- Set holdout > 0 to get a separate test-set evaluation in the report.

