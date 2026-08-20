# MNE Viewer 2D (montage-free)

**Category:** Output Nodes

**Language:** Python

**Source:** `mne_viewer2d_plugin.py`

## Summary
MNE Viewer 2D — Montage-Free Plots (markers-ready)

## Inputs
| Name | Description |
|---|---|
| ch_names | List[str] — channel labels (overrides names from raw/segment) |
| markers | list or dict — vertical markers in formats: (t, label), (t, label, dur), {"t":..., "label":..., "dur":..., "mode":"rel\|sample"}, or a list thereof |
| raw | MNE Raw object — takes priority over segment if both connected |
| segment | 2D float [channels x samples] — EEG data array |
| sfreq | float (Hz) — sampling rate (used with segment, ignored for raw) |
| title | str — custom title displayed at the top |

## Outputs
| Name | Description |
|---|---|
| status | str — current viewer status message |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| scale_uv | float |  | µV | Vertical scale for signal plot |
| speed | float |  |  | Scroll speed multiplier |
| fullscreen | bool |  |  | Show full screen |
| max_ch_plot | int |  |  | Maximum number of channels displayed in traces and correlation matrix |
| fmax | float |  |  | Maximum frequency in Hz for PSD, spectrogram, and coherence plots |
| win_sec | float |  |  | Visible window duration in seconds for signal auto-scroll |
| nperseg | int |  |  | Welch segment length for PSD/coherence |
| noverlap | int |  |  | Welch overlap for PSD/coherence |

## Usage
Connect segment (or raw) plus sfreq and ch_names. Supports Signal, PSD, Spectrogram, Band-power, Correlation, and Coherence plots with optional vertical markers.

## Gotchas
- High refresh rate can drop FPS; reduce update frequency or increase window size.
- If both raw and segment are connected, raw takes priority.
- Markers are only shown when the Marqueurs checkbox is enabled; max 20 markers are drawn to avoid clutter.
- Scipy is optional; if absent, numpy fallbacks are used for PSD/coherence (slower).
- MNE is optional; if absent, only segment (numpy array) input works, not MNE Raw objects.

