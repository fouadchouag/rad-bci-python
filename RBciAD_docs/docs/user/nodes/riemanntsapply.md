# RiemannTSApply

**Category:** ML

**Language:** Python

**Source:** `riemann_ts_apply_plugin.py`

## Summary
Apply a trained Tangent Space transform to project covariance matrices into 1D feature vectors.

## Inputs
| Name | Description |
|---|---|
| ts_transform | trained pyRiemann TangentSpace object — must be fitted via RiemannTSTrainer |
| cov | 2D float [ch x ch] — SPD covariance matrix matching the dimensionality used during TS training |

## Outputs
| Name | Description |
|---|---|
| features | 1D float array — tangent-space feature vector of dimension n_ch*(n_ch+1)/2 |
| features_dim | int — dimensionality of the feature vector |

## Parameters
_None_

## Usage
Connect a trained ts_transform (from RiemannTSTrainer) and a covariance matrix. Outputs a 1D feature vector.

## Gotchas
- The ts_transform must be fitted (via RiemannTSTrainer) before use; otherwise transform will fail silently.
- Input covariance must be SPD and square, matching the number of channels used during TS training.
- The covariance is wrapped in a batch dimension internally: ts.transform(C[np.newaxis, ...]).
- If either ts_transform or cov is None, the node outputs nothing (no error emitted).

