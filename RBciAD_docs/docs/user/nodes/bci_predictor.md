# BCI_Predictor

**Category:** ML

**Language:** Python

**Source:** `bci_predictor_node.py`

## Summary
Online BCI predictor: applies a trained model to incoming features and outputs class predictions with confidence.

## Inputs
| Name | Description |
|---|---|
| features | dict — per-channel band values from BCI_Features |
| band_labels | list[str] — feature dimension labels |
| model | trained scikit-learn Pipeline (optional; can also load from file) |
| y_names_in | list[str] — class names (optional; overrides internal) |
| config_in | dict — generic config from BCI_Config |
| predictor_conf | dict — predictor-specific config |

## Outputs
| Name | Description |
|---|---|
| pred_idx | int — predicted class index |
| pred_label | str — predicted class name |
| pred_conf | float — confidence (max probability) |
| proba | dict — {label_name: float} per-class probabilities |
| y_names | list[str] — class names |
| config_out | dict — current parameter state |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| smooth_N | int |  |  | Smoothing window size for probability averaging (1–50) |
| smooth_enabled | bool |  |  | Enable/disable probability smoothing |

## Usage
Connect features (from BCI_Features) and a trained model (from BCI_Trainer). Outputs predicted class index, label, confidence, and per-class probabilities.

## Gotchas
- The model must be trained with the same features (same bands, same mode) used at inference.
- Smoothing (smooth_N > 1) reduces jitter but adds latency.
- If no model is connected, you can load one from a file via the properties panel.

