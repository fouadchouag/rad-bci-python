# TFRViewer

**Category:** Output Nodes

**Language:** Python

**Source:** `tfr_viewer.py`

## Summary
TFRViewer — robuste au changement de fichier / nbre de canaux

## Inputs
| Name | Description |
|---|---|
| tfr | mne.time_frequency.AverageTFR\|EpochsTFR |
| channel | str\|int (opt.) |

## Outputs
_None_

## Parameters
| Name | Type | Default | Unit | Description |
|---|---|---|---|---|
| single_channel | bool |  |  | Afficher un seul canal |
| db_scale | bool |  |  | Échelle dB |

## Usage
Connect upstream TFR; ouvrez Paramètres pour choisir le canal / dB.

## Gotchas
- High refresh can drop FPS; consider decimation.

