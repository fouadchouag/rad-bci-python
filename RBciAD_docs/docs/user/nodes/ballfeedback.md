# BallFeedback

**Category:** Output Nodes

**Language:** Python

**Source:** `ball_feedback_plugin.py`

## Summary
Moves a ball left/right according to classifier prediction — real-time BCI feedback visualizer.

## Inputs
| Name | Description |
|---|---|
| pred_label | str — predicted class label (must match left_name or right_name) |
| pred_conf | float — prediction confidence in [0, 1]; ball only moves when &gt;= threshold |
| config_in | dict — optional config override (keys: left_name, right_name, threshold, speed) |
| ball_feedback_conf | dict — alternative config override (merged after config_in) |

## Outputs
| Name | Description |
|---|---|
| config_out | dict — current config state: {left_name, right_name, threshold, speed} |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| left_name | str | Left |  | Label string for left-class predictions |
| right_name | str | Right |  | Label string for right-class predictions |
| threshold | float |  |  | Minimum confidence to actuate the ball (0.0–1.0) |
| speed | float |  |  | Ball movement speed (screen-widths per second) |

## Usage
Connect pred_label and pred_conf from a classifier. Configure class names, threshold, and speed in the UI.

## Gotchas
- Ball only moves when confidence >= threshold; below threshold the ball stays still.
- Left/right class name matching is case-sensitive and must exactly match pred_label.
- Test Left/Test Right buttons override the classifier prediction while held down.
- config_in and ball_feedback_conf are merged sequentially — ball_feedback_conf wins on conflicts.
- Animation runs at ~33 FPS (30 ms timer) regardless of prediction rate.

