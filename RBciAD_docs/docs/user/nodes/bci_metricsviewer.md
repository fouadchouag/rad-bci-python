# BCI_MetricsViewer

**Category:** BCI/Utils

**Language:** Python

**Source:** `bci_metrics_viewer.py`

## Summary
Displays trained model evaluation metrics from a BCI_Trainer report: CV accuracy ± std, balanced accuracy, F1 macro, confusion matrix, and per-class accuracy. Supports JSON and CSV export.

## Inputs
| Name | Description |
|---|---|
| report | dict — training report from BCI_Trainer (cv_mean, cv_std, cv_confusion, cv_per_class_acc, etc.) |
| dataset | dict (optional) — contains y_names for human-readable class labels |

## Outputs
_None_

## Parameters
_None_

## Usage
Connect the "report" output from BCI_Trainer. Optionally connect "dataset" for human-readable class names.

## Gotchas
- Report dict must contain expected keys (cv_mean, cv_std, cv_confusion, etc.); missing keys show as NaN or empty.
- UI updates via QTimer.singleShot(0) to avoid cross-thread Qt crashes.
- CSV export creates two files: <name>.csv (confusion matrix) and <name>_perclass.csv (per-class accuracy).
- If dataset y_names is not connected, class labels default to "Cls0", "Cls1", etc.

