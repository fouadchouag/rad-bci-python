# BCI_EuclideanAlignment

**Category:** Preprocessing

**Language:** Python

**Source:** `bci_euclidean_alignment_node.py`

## Summary
Per-subject Euclidean Alignment for cross-subject BCI.

## Inputs
| Name | Description |
|---|---|
| segment | 2D float [ch x samples] |
| sfreq | float (sampling frequency) |
| ch_names | list[str] (optional) |

## Outputs
| Name | Description |
|---|---|
| segment | aligned 2D float [ch x samples] |
| sfreq | float |
| ch_names | list[str] |
| ea_matrix | 2D float [ch x ch] whitening matrix |
| config_out | dict |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| enabled | bool |  |  | Enable/disable EA transformation |
| epsilon | float |  |  | Regularization for covariance eigendecomposition |

## Usage
Connect EEG segments. In fit mode, accumulate training trials; in transform mode, EA is applied automatically.

## Gotchas
- In fit mode, accumulate all training trials before enabling transform.
- EA requires no label information from the target subject.

