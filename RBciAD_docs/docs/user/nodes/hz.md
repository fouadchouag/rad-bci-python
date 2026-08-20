# {...}Hz

**Category:** BCI/Utils

**Language:** Python

**Source:** `markers_to_classidx.py`

## Summary
Convertit des marqueurs LSL (strings) en y_idx (int) et y_name (str).

## Inputs
| Name | Description |
|---|---|
| config_in | dict — merged configuration block (scenario, map, ssvep_freqs, hold_sec, auto_reset_on_idle) |
| events | list[dict] — batch of events [{"ts": float, "code": str}, ...] from LSL Markers inlet |
| markers_conf | dict — markers-specific config (same keys as config_in, overrides config_in) |

## Outputs
| Name | Description |
|---|---|
| K | int — estimated number of classes for the current scenario |
| config_out | dict — current configuration exported |
| last_event | dict — most recent event {"ts": float, "code": str} |
| y_idx | int or None — class index of the current event (None if no event or hold expired) |
| y_name | str or None — class name of the current event (None if no event or hold expired) |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| scenario | str | MI |  | Paradigm scenario: MI, P300, SSVEP, or Custom |
| map | str | 769:0; 770:1; 771:2; 772:3 |  | Semicolon-separated code:idx mapping for MI/P300/Custom |
| ssvep_freqs | str | 10,12,15 |  | Comma-separated target frequencies in Hz for SSVEP scenario |
| hold_sec | float |  |  | Duration in seconds to hold the current class index |
| auto_reset_on_idle | bool |  |  | Reset y_idx to None when hold expires |

## Usage
Connect events from an LSL Markers inlet. Outputs y_idx, y_name, K, and last_event for downstream classification or display.

## Gotchas
- P300 events are not held (hold_sec is ignored for P300 scenario).
- SSVEP codes must match the pattern FREQ<value> (e.g. "FREQ10" or "FREQ-12.5").
- If hold_sec expires and auto_reset_on_idle is off, the last y_idx persists until a new event arrives.
- K (number of classes) is estimated from the scenario, not the mapping; Custom scenario uses max mapping index + 1.

