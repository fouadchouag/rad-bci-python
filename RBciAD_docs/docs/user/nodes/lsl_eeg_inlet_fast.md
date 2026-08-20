# LSL_EEG_Inlet_Fast

**Category:** Input Nodes

**Language:** Python

**Source:** `lsl_eeg_inlet_fast.py`

## Summary
Inlet EEG non-bloquant : thread lecteur + DropOldQueue + QTimer emit.

## Inputs
| Name | Description |
|---|---|
| config_in | dict — merged configuration block (keys: emit_ms, chunk_ms, stream_name, autoconnect) |
| lsl_eeg_conf | dict — EEG-specific config (same keys as config_in, overrides config_in) |

## Outputs
| Name | Description |
|---|---|
| ch_names | List[str] — channel labels from LSL stream metadata |
| config_out | dict — current configuration (emit_ms, chunk_ms, stream_name, autoconnect) |
| data | 2D float32 [samples x channels] — latest EEG chunk |
| sfreq | float (Hz) — nominal sampling rate from LSL stream |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| emit_ms | int |  |  | Interval between emit ticks in milliseconds |
| chunk_ms | int |  |  | Duration of each LSL pull in milliseconds |
| autoconnect | bool |  |  | Automatically connect on config import |

## Usage
Use the UI to select and connect to an EEG stream, or send a config dict via config_in/lsl_eeg_conf inputs to autoconnect programmatically.

## Gotchas
- Only the latest chunk is kept (DropOldQueue); intermediate data between ticks is discarded.
- Network hiccups may cause gaps—buffering is single-slot only.
- Autoconnect triggers on import_config if the checkbox is enabled.
- Changing emit_ms/chunk_ms takes effect immediately but requires reconnection for chunk_ms.

