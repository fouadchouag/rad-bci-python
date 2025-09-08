# CSPTrainer

**Category:** ML / Features

**Language:** Python

## Summary
Train a machine-learning model for BCI.

## Inputs
| Name | Description |
|---|---|
| features | array/dict |
| labels | array |

## Outputs
| Name | Description |
|---|---|
| model | trained model |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| model | str | LR |  | Classifier (LR/SVM/RF/...) |
| cv | int | 5 |  | Cross-validation folds |
| scaler | str | standard |  | Feature scaling |

## Usage
Feed features and labels; connect model to runtime/apply node.

## Gotchas
- Balance classes; keep held-out test set.

