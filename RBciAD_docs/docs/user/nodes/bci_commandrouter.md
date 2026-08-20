# BCI_CommandRouter

**Category:** BCI/Utils

**Language:** Python

**Source:** `bci_command_router.py`

## Summary
Transforms classifier predictions into stable directional commands (LEFT/RIGHT/UP/DOWN/STOP) with confidence threshold, dwell time, majority smoothing, and refractory period. Optionally emits an LSL stream.

## Inputs
| Name | Description |
|---|---|
| pred_idx | int — predicted class index |
| pred_conf | float (optional) — prediction confidence |
| proba | dict[str-&gt;float] (optional) — class probabilities; max used if pred_conf absent |
| pred_label | str (optional) — predicted label (not used in routing logic) |

## Outputs
| Name | Description |
|---|---|
| command | str — stable command (LEFT/RIGHT/UP/DOWN/STOP) |
| dx | float — horizontal component (-1.0, 0.0, or 1.0) |
| dy | float — vertical component (-1.0, 0.0, or 1.0) |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| map_text | str | 0:LEFT; 1:RIGHT; 2:UP; 3:DOWN; *:STOP |  | Index-to-command mapping (idx:CMD; ...; *:default) |
| conf_thr | float |  |  | Minimum confidence to accept a prediction |
| dwell_ms | int |  |  | Dwell time in ms — prediction must persist this long |
| refr_ms | int |  |  | Refractory period in ms after a command is emitted |
| smooth_N | int |  |  | Majority smoothing window (last N valid predictions) |
| nc_idx | int |  |  | Class index used when confidence is below threshold (-1 = drop) |
| emit_lsl | bool |  |  | Emit LSL stream "BCI_CMD" (type=Markers) |

## Usage
Connect pred_idx (and optionally pred_conf/proba) from a classifier. Outputs dx/dy for ball controllers or command strings for other consumers.

## Gotchas
- LSL output requires pylsl; if missing, stream is silently skipped.
- Mapping must follow format "idx:CMD; ..." (e.g. "0:LEFT; 1:RIGHT; 2:UP; 3:DOWN; *:STOP").
- If confidence < conf_thr and nc_idx is -1, the prediction is silently dropped (no command emitted).
- Refractory period suppresses ALL command outputs, including STOP transitions.

