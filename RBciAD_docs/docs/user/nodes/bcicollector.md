# BCICollector

**Category:** BCI/Utils

**Language:** Python

**Source:** `bci_collector_node.py`

## Summary
Collect features and labels into a dataset dict for training. Supports manual recording or marker-based assignment.

## Inputs
| Name | Description |
|---|---|
| features | dict — per-channel band values from BCI_Features |
| band_labels | list[str] — feature dimension labels |
| y_idx | int — class index from external markers (when use_markers=True) |
| feature_mode | str — feature mode identifier |
| config_in | dict — generic config from BCI_Config |

## Outputs
| Name | Description |
|---|---|
| dataset | dict — {"X": ndarray(N,F), "y": ndarray(N,), "y_names": list, "bands": list, "feature_mode": str\|None} |
| config_out | dict — current parameter state |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| K | int |  |  | Number of classes (2–8) |
| y_names | list |  |  | Class label names |
| use_markers | bool |  |  | Use y_idx input for class assignment instead of manual buttons |

## Usage
Connect BCI_Features output. Press Record buttons to assign class labels, or enable use_markers for automatic assignment.

## Gotchas
- Ensure features are consistent (same bands, same mode) across all recorded trials.
- Press "Reset" to clear accumulated data before starting a new recording session.
- The dataset output is ready to connect to BCI_Trainer.

