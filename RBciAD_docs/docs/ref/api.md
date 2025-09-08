# API Reference (Overview)

> This overview documents the public surfaces commonly used by plugin authors and integrators. Paths may vary based on your repo layout—adapt imports accordingly.

## core.node_base.BasePlugin
**Purpose:** Base class for all nodes.

**Key attributes**
- `category: str` – palette section (e.g., "Input", "Processing", "Output", "Utils", "Polyglot")
- `display_name: str` – human‑readable name
- `inputs: Dict[str, BehaviorSubject]` – set in `setup()`
- `outputs: Dict[str, BehaviorSubject]` – set in `setup()`
- `help: Dict` – optional Quick Help metadata

**Key methods**
- `setup(self) -> None` – define `inputs` and `outputs`.
- `execute(self, in_data: dict, **kwargs)` – compute outputs; call `on_next`.
- `set_input(self, name: str, value: Any)` – framework method that updates input & triggers `execute()`.
- `logger` – node‑scoped logger.

## gui.main_window.MainWindow
Entrypoint for the application window (scene, palette, properties, menus).

**Common actions**
- Place a node from palette (single‑click).
- Connect pins (drag output → input).
- Save/Load workflow.

## plugins.* (Examples)
- `EEGUniversalReader`: outputs `raw`, `segment`, `ch_names`, `sfreq`, `info`, `events`.
- `EEGFilter`: inputs `raw` or `segment`; parameters `hp`, `lp`, `notch`.
- `EEGVisualizer`: consumes `raw` or `segment`; embedded Matplotlib plot.
