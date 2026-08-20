# OnlineMetrics

**Category:** BCI/Utils

**Language:** Python

**Source:** `online_metrics_node.py`

## Summary
Computes online metrics by comparing pred_idx vs y_idx: rolling accuracy (window N), cumulative accuracy, Cohen's kappa, and cumulative confusion matrix. Auto-expands K when new class indices appear.

## Inputs
| Name | Description |
|---|---|
| pred_idx | int — predicted class index (non-negative) |
| y_idx | int — ground truth class index (non-negative) |

## Outputs
| Name | Description |
|---|---|
| metrics | dict — {acc_window, acc_cum, kappa, n_total, window_size, K} |
| confusion | np.ndarray (K,K) — cumulative confusion matrix (copy) |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| win_N | int |  |  | Rolling accuracy window size |
| auto_K | bool |  |  | Automatically expand K when new class indices appear |
| K | int |  |  | Number of classes (used when auto_K is off) |

## Usage
Connect pred_idx from classifier and y_idx from ground truth marker. Outputs a metrics dict and confusion matrix for downstream display or logging.

## Gotchas
- Both pred_idx and y_idx must be non-negative integers; negative values are silently ignored.
- Auto-K only expands K when new indices appear; use Reset to shrink back.
- Confusion matrix output is a copy — safe to mutate externally.
- Cohen's kappa returns 0.0 when total samples are zero or agreement is at chance level.

