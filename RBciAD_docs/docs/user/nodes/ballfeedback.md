# BallFeedback

**Category:** Output Nodes

**Language:** Python

## Summary
Déplace une balle à gauche/droite selon la prédiction du classifieur.

## Inputs
| Name | Description |
|---|---|
| segment | 2D float [ch x samples] (or raw/derived) |

## Outputs
_None_

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| scale_uv | float | 50.0 | µV | Vertical scale |
| speed | float | 1.0 |  | Scroll speed |
| fullscreen | bool | False |  | Show full screen |

## Usage
Connect upstream data; adjust view parameters.

## Gotchas
- High refresh can drop FPS; consider decimation.

