# LSL_Markers_Inlet

**Category:** Input Nodes

**Language:** Python

**Source:** `lsl_markers_inlet.py`

## Summary
Inlet LSL pour flux de marqueurs (strings).

## Inputs
| Name | Description |
|---|---|
| config_in | dict — merged configuration block (keys: emit_ms, auto_connect, stream_name) |
| lsl_markers_conf | dict — markers-specific config (same keys as config_in, overrides config_in) |

## Outputs
| Name | Description |
|---|---|
| config_out | dict — current configuration (emit_ms, auto_connect, stream_name) |
| events | list[dict] — batch of events [{"ts": float, "code": str}, ...] since last tick |
| last_event | dict — most recent event {"ts": float, "code": str} |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| emit_ms | int |  |  | Interval between emit ticks in milliseconds |
| auto_connect | bool |  |  | Automatically connect on config import |

## Usage
Use the UI to refresh and connect to a Markers LSL stream, or send a config dict via config_in/lsl_markers_conf inputs to autoconnect programmatically.

## Gotchas
- Resolves only LSL streams with type="Markers" (not EEG).
- Events are pulled one sample at a time and buffered; emitted in bursts on the QTimer tick.
- Network hiccups may cause gaps—use buffering.
- Auto-connect triggers after import_config if enabled.

