# ClassifierRuntime

**Category:** ML

**Language:** Python

**Source:** `classifier_runtime_plugin.py`

## Summary
Applies a fitted sklearn classifier to a single feature vector, producing pred_idx, pred_label, and optionally a probability dict.

## Inputs
| Name | Description |
|---|---|
| model | sklearn classifier (must be fitted, with predict method) |
| features | array-like (n_feat,) — single feature vector |

## Outputs
| Name | Description |
|---|---|
| pred_label | str/int — predicted class label (from clf.classes_ if available) |
| pred_idx | int — integer index of predicted class |
| proba | dict[str-&gt;float] — class probabilities (or None if unavailable) |

## Parameters
_None_

## Usage
Connect a fitted model and a feature vector (1D). Outputs are emitted each time both inputs are available.

## Gotchas
- Model-version mismatch can reduce accuracy.
- Features must be a 1D array of length n_feat; it is reshaped to (1, -1) internally.
- proba output is None if the classifier does not support predict_proba.
- If predict() raises an error, no outputs are emitted (silent failure).

