# BCI_BallController

**Category:** BCI/Feedback

**Language:** Python

**Source:** `bci_ball_controller.py`

## Summary
Controls a 2D ball using classifier predictions. Maps pred_idx to directional actions (Left/Right/Up/Down/Idle) with physics simulation (velocity, friction, boundary bouncing). Supports confidence-weighted speed.

## Inputs
| Name | Description |
|---|---|
| pred_idx | int — predicted class index |
| proba | dict[str-&gt;float] (optional) — class probabilities for confidence-weighted speed |
| y_names | list[str] (optional) — class names; updates K and rebuilds mapping UI |
| config_in | dict (optional) — merged with ball_controller_conf |
| ball_controller_conf | dict (optional) — {K, map, speed, friction, prob_gain, use_prob} |

## Outputs
| Name | Description |
|---|---|
| config_out | dict — {K, map, speed, friction, prob_gain, use_prob} |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| speed | float |  |  | Ball acceleration multiplier |
| friction | float |  |  | Velocity decay per tick (0.80..0.999) |
| prob_gain | float |  |  | Confidence-based speed gain multiplier |
| use_prob | bool |  |  | Use probability dict to scale movement speed |

## Usage
Connect pred_idx from a classifier. Configure class-to-action mapping in the UI. Optionally connect proba for confidence-based speed scaling.

## Gotchas
- Ball physics runs at ~30 FPS via QTimer; timer stops automatically on widget destruction.
- Map values must be from ACTIONS: ["Idle","Left","Right","Up","Down"].
- If pred_idx is outside [0, K), ball receives no acceleration (continues with inertia/friction).
- proba-based scaling uses (p_selected - p_background) * prob_gain; low-confidence predictions move slower.

