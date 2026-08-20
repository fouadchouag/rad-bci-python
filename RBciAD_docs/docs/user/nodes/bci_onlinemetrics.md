# BCI_OnlineMetrics

**Category:** BCI/Utils

**Language:** Python

**Source:** `bci_online_metrics_node.py`

## Summary
Computes online rolling accuracy and cumulative confusion matrix by comparing pred_idx vs y_idx in real time.

## Inputs
| Name | Description |
|---|---|
| pred_idx | int — predicted class index |
| y_idx | int — ground truth class index |
| y_names | list[str] (optional) — class names, can change at runtime |
| config_in | dict (optional) — merged with online_metrics_conf |
| online_metrics_conf | dict (optional) — {"roll": int} to set window size |

## Outputs
| Name | Description |
|---|---|
| config_out | dict — {"roll": int} current window size |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| roll | int |  |  | Rolling accuracy window size (5..5000) |

## Usage
Connect pred_idx and y_idx from classifier and ground truth. Window size can be adjusted via UI or config_in.

## Gotchas
- Both pred_idx and y_idx must arrive simultaneously; if either is None, the sample is skipped.
- Rolling window uses a deque with maxlen; old samples are discarded permanently.
- UI is updated by a 150 ms timer, not on every execute() call.
- Reset clears both the rolling queue and the cumulative confusion matrix.

