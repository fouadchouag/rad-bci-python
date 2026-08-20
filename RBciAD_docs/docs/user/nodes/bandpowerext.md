# BandpowerExt

**Category:** Processing Nodes

**Language:** Python

**Source:** `bandpower_ext_plugin.py`

## Summary
Extract band power features by delegating to an external bandpower script via subprocess.

## Inputs
| Name | Description |
|---|---|
| segment | 2D float [channels x samples] — EEG data (auto-oriented to channels-first) |
| sfreq | float — sampling frequency in Hz (required) |
| ch_names | list[str] — optional channel names (auto-generated if missing or mismatched) |
| info | dict — optional {"sfreq": float, "ch_names": list[str]} bundle; sfreq/ch_names take precedence if also provided |

## Outputs
| Name | Description |
|---|---|
| features | dict or None — features dict from the external script (shape depends on script) |
| band_labels | list[str] — band names (default: delta, theta, alpha, beta, gamma) |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| bands | dict | {"delta":[1,4],"theta":[4,8],"alpha":[8,13],"beta":[13,30],"gamma":[30,45]} |  | Band definitions passed to the external script (hardcoded in payload). |

## Usage
Connect a segment and sampling frequency. The node writes input JSON, runs the external script, and reads the output JSON to emit features.

## Gotchas
- Requires an external script (bandpower_ext.py or .exe) in one of several candidate paths; missing script causes silent no-op.
- Executes the external script as a subprocess — may have latency on each call.
- The bands dict is hardcoded in the payload and cannot be changed from the UI.
- sfreq is required — the node outputs None if missing.
- Input/output are exchanged via temporary JSON files in temp_io/.
- ch_names are auto-generated (ch1, ch2, ...) if not provided or if count mismatches the data.

