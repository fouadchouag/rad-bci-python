# BCI_TSFBCSPFeatures

**Category:** ML

**Language:** Python

**Source:** `bci_tsfbcsp_features_node.py`

## Summary
TS-FBCSP: Filter-bank tangent space features with OAS covariance.

## Inputs
| Name | Description |
|---|---|
| segment | 2D float [samples x channels] (EA-aligned EEG) |
| sfreq | float |
| ch_names | list[str] |
| y_idx | int (class label, optional) |

## Outputs
| Name | Description |
|---|---|
| features | 1D float array (concatenated tangent vectors) |
| features_dim | int |
| band_labels | list[str] |
| covariances | list[ndarray] (per-band covariance matrices) |
| config_out | dict |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| mode | str | transform |  | fit: compute Riemannian means; transform: project to tangent space |
| cov_estimator | str | OAS |  | Covariance estimator: OAS, LW (Ledoit-Wolf), or empirical |

## Usage
Connect preprocessed EA-aligned EEG. Set mode=fit for training, mode=transform for inference.

## Gotchas
- In fit mode, connect y_idx for supervised Riemannian mean computation.
- Requires pyriemann for full Riemannian operations (fallback: pure numpy).
- Feature dimensionality = C*(C+1)/2 * n_bands (e.g., 253*9=2277 for 22ch).

