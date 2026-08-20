# RiemannTSTrainer

**Category:** ML

**Language:** Python

**Source:** `riemann_ts_trainer_plugin.py`

## Summary
Train a Tangent Space mapping (pyRiemann) from covariance matrices and labels.

## Inputs
| Name | Description |
|---|---|
| cov | 2D float [ch x ch] — SPD covariance matrix (from RiemannCov) |
| label | str or int — class label for the trial |

## Outputs
| Name | Description |
|---|---|
| ts_transform | fitted pyriemann.TangentSpace object (or None until trained) |
| classes | list — unique class labels seen during training |
| n_samples | int — number of accumulated covariance samples |
| counts | dict — sample count per class label |

## Parameters
_None_

## Usage
Connect covariance matrices and their class labels. Click "Ajouter" to accumulate, then "Entraîner TS" to fit the tangent space. Outputs a fitted transform for RiemannTSApply.

## Gotchas
- At least 2 samples are required to train.
- Balance classes for best results; keep a held-out test set.
- Training is manual — click "Ajouter" to add samples, then "Entraîner TS" to fit.
- The TangentSpace uses the Riemannian metric by default.
- execute() is a no-op; all accumulation and training happens via UI buttons.
- Requires the pyriemann package (pip install pyriemann).
- Saved models contain only the TangentSpace object, not the training data.

