# BCI_Config

**Category:** BCI/Utils

**Language:** Python

**Source:** `bci_config_node.py`

## Summary
No-code workflow config manager: scans all nodes in the workflow, provides a friendly UI to edit their parameters (auto-generated from export_config/config_hints), and supports preview/revert/apply (selected/class/all) plus preset save/load.

## Inputs
| Name | Description |
|---|---|
| config_in | dict — preset config to apply programmatically |

## Outputs
| Name | Description |
|---|---|
| config_out | dict — last applied preset, format {"nodes": {key: {"class","plugin_name","config"}}} |

## Parameters
_None_

## Usage
Place in workflow and click "Scan workflow" to discover nodes. Select a node to edit its parameters, then Apply. Presets are saved/loaded as JSON and tolerant of node ID changes.

## Gotchas
- Uses gc.get_objects() to find nodes — may be slow on very large workflows.
- Node identity uses id(), which changes between runs; presets handle this via class-based fallback.
- Apply targets: "selected" applies only to the highlighted node, "class" applies to all nodes of the same type, "all" applies to every scanned node.
- Preset loading auto-switches to "all" if no node is selected.

