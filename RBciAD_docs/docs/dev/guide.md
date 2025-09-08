# Developer Guide

This guide explains the architecture, plugin API, and how to extend RBciAD safely.

## 1) Architecture (Overview)
- **GUI:** Qt Graphics Scene for nodes, pins, and connections.
- **Reactive Engine (RxPY):** Each input/output is a `BehaviorSubject`. Calling `set_input(name, value)` triggers `execute()`; outputs are pushed with `on_next(...)`.
- **Metrics:** Hooks like `START_TTFP`, `FIRST_FRAME`, `FRAME_RENDERED`, `PARAM_CHANGE` feed CSV logs for reproducibility.

## 2) Plugin API (Python)
**Base class:** `core.node_base.BasePlugin` (import path may vary in your project).

### Required attributes
- `category: str` — e.g., "Input", "Processing", "Output", "Utils", "Polyglot"
- `display_name: str` — human‑readable title

### Required methods
```python
from core.node_base import BasePlugin
from rx.subject import BehaviorSubject

class MyNode(BasePlugin):
    category = "Processing"
    display_name = "MyNode"

    def setup(self):
        # define I/O ONLY here
        self.inputs = {"x": BehaviorSubject(None)}
        self.outputs = {"y": BehaviorSubject(None)}

    def execute(self, in_data: dict, **kwargs):
        x = in_data.get("x")
        if x is None:
            return None
        y = self._do_work(x)
        self.outputs["y"].on_next(y)
        return y

    # optional helpers
    def _do_work(self, x):
        return x
```

### Rules & Best Practices
- Define `inputs`/`outputs` **only in `setup()`**.
- Keep `execute()` **idempotent** and non‑blocking; offload long work to threads or native in‑process code.
- Emit outputs **only** via `self.outputs[name].on_next(value)`.
- Provide `help` metadata for Quick Help:
```python
help = {
  "summary": "Processes input x into output y.",
  "inputs": {"x": "any"},
  "outputs": {"y": "any"},
  "parameters": [{"name": "alpha", "type": "float", "default": 0.5, "desc": "Weight."}],
  "usage": "Place after a source node; connect y downstream.",
  "gotchas": ["x must be numeric if y is numeric."]
}
```

## 3) Dynamic Registry & Palette
- At startup, RBciAD scans `plugins/` and `custom_plugins/`.
- Each module must export exactly one plugin class (or a clear list) with `category`, `display_name`, and `BasePlugin` inheritance.
- Import failures are logged but do not crash the app; the palette skips bad plugins.

## 4) Metrics & Reproducibility
- Press `F9` (or menu) to log events into `metrics/runs/Wi/run_*.csv`.
- Aggregate with `metrics/metric_eval.py` → `metrics/metrics_sample.csv` (TTFP, P50/P95 FPS, CPU%, RSS).
- Always report dataset, parameters, and versions in your figures or tables.
