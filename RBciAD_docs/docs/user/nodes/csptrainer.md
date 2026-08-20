# CSPTrainer

**Category:** ML

**Language:** Python

**Source:** `csp_trainer_plugin.py`

## Summary
Train a Common Spatial Patterns (CSP) spatial filter from EEG trials and labels.

## Inputs
| Name | Description |
|---|---|
| segment | 2D float [channels x samples] — a single EEG trial |
| label | int/str — class label for the trial |

## Outputs
| Name | Description |
|---|---|
| feature_transform | fitted MNE CSP object (or None until trained) |
| classes | list — class labels seen during training |
| n_samples | int — number of accumulated samples |
| counts | dict — sample count per class |
| status | str — status message |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| n_components | int |  |  | Number of CSP spatial filters (2–64). Controls how many spatial patterns are learned. |

## Usage
Connect EEG segments and their class labels. Click "Train CSP" to fit. Outputs a fitted CSP transform for downstream feature extraction.

## Gotchas
- You need at least 2 classes with multiple trials each to train.
- Balance classes for best results; keep a held-out test set.
- Training is manual — click the "Train CSP" button in the node UI.
- The execute() method is a no-op; all data accumulation and training happens via the UI buttons.
- Segment orientation is auto-detected: if rows > cols it is transposed to (n_ch, n_t).
- CSP uses OAS shrinkage regularization and log-variance features by default.
- Saved/loaded models include the label encoder classes alongside the CSP object.

