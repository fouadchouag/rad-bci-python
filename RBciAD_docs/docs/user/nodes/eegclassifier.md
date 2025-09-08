# EEGClassifier

**Category:** ML

**Language:** Python

## Summary
Classification 2 classes (Left/Right) simplifiée.

## Inputs
| Name | Description |
|---|---|
| features | array/dict |
| model | trained model |

## Outputs
| Name | Description |
|---|---|
| pred | labels |
| proba | optional probabilities |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| threshold | float | 0.5 |  | Decision threshold (if applicable) |

## Usage
Connect features and a compatible model.

## Gotchas
- Model-version mismatch can reduce accuracy.

