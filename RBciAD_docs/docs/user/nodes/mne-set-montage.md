# MNE Set Montage

**Category:** Transform Nodes

**Language:** Python

**Source:** `mne_set_montage_plugin.py`

## Summary
Apply a standard electrode montage to an MNE Raw object with tolerant channel name matching.

## Inputs
| Name | Description |
|---|---|
| raw | mne.io.Raw — input EEG/MEG Raw object without or with incomplete montage |

## Outputs
| Name | Description |
|---|---|
| raw | mne.io.Raw — same Raw object with montage positions set |
| status | str — human-readable status message |

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| montage | str | standard_1020 |  | Standard montage name (e.g. "standard_1020", "standard_1005", "biosemi64", "easycap-M1"). Set via UI combo. |
| auto | bool |  |  | When True, montage is applied automatically on every incoming Raw. |

## Usage
Connect an MNE Raw node upstream. Select a montage from the dropdown; if auto is checked it applies on every data flow. Otherwise click "Appliquer" manually.

## Gotchas
- Requires MNE-Python (pip install mne).
- Channel names are canonicalized (EEG prefix stripped, punctuation removed, suffixes like -REF removed) for matching.
- Aliases are applied: T9->TP9, T10->TP10, A1->TP9, A2->TP10, M1->TP9, M2->TP10.
- If no channel names match the montage, a warning is emitted and no positions are set.
- Only matched channels get positions; unmatched channels are left without montage.
- When auto=True, montage re-applies on every new Raw — toggling montage combo also triggers re-apply.

