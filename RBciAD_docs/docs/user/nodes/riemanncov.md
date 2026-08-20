# RiemannCov

**Category:** ML

**Language:** Python

**Source:** `riemann_cov_plugin.py`

## Summary
Compute the SPD covariance matrix from a single EEG segment.

## Inputs
| Name | Description |
|---|---|
| segment | 2D float [channels x samples] or [samples x channels] |

## Outputs
| Name | Description |
|---|---|
| cov | 2D float SPD matrix [channels x channels] — regularized sample covariance |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| epsilon | float |  |  | Diagonal regularization (εI). Prevents singularity when n_samples ≈ n_channels. Range: 1e-12 to 1e-2. |

## Usage
Connect a 2D EEG segment (channels × samples). Outputs the regularized SPD covariance matrix for downstream Riemannian geometry processing.

## Gotchas
- Segment must be 2D; a 1D or 3D input will be rejected (outputs None).
- Orientation is auto-detected: if rows > cols, the array is transposed to (n_ch, n_t).
- ε is added to the diagonal of the covariance; too large a value biases the result toward identity.
- NaN/Inf values in the segment are replaced with zero before computing covariance.
- The covariance is computed as (X @ X.T) / (n_t - 1) with mean-centering per channel.

