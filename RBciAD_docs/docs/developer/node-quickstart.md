# Node Quickstart (5 minutes)

## Option A — Low-code (GUI) **recommended**
1. **Open** LowCode Creator.
2. Fill **Node name**, **Language**, **Exec mode** (`auto` is fine).
3. Add **Inputs/Outputs** and **Parameters** (use presets if helpful).
4. Click **📂 Choose script/binary…** and select your executable (or Python file).
5. Click **➕ Add to palette**.  
   - A wrapper is generated under `custom_plugins/<slug>_plugin.py`.
   - You’ll be asked for **Summary** and **Usage**; the tool injects a full `help` dict.
   - The node appears in the **Custom** category.

## Option B — Hand-written wrapper (advanced)
Create `custom_plugins/my_filter_plugin.py`:
```python
from core.node_base import BasePlugin
from rx.subject import BehaviorSubject

class MyFilterPlugin(BasePlugin):
    display_name = "My Filter"
    category = "Processing"
    language = "Python"

    # Help shows in Quick Help (Ctrl+F1 / "?" badge) and node catalog
    help = {
      "summary": "Band-pass filter for EEG segments.",
      "inputs":  {"raw": "2D float [ch x samples]", "sfreq": "float (Hz)"},
      "outputs": {"raw": "2D float [ch x samples]"},
      "parameters": [
        {"name":"low","type":"float","default":1.0,"unit":"Hz","desc":"High-pass edge"},
        {"name":"high","type":"float","default":40.0,"unit":"Hz","desc":"Low-pass edge"}
      ],
      "usage": "Place after raw acquisition; set low/high < Nyquist; feed downstream.",
      "gotchas": ["Ensure sfreq>0", "low < high"]
    }

    def setup(self):
        self.inputs  = {"raw": BehaviorSubject(None), "sfreq": BehaviorSubject(None)}
        self.outputs = {"raw": BehaviorSubject(None)}

    def execute(self, **kwargs):
        raw = kwargs.get("raw"); sfreq = float(kwargs.get("sfreq", 0) or 0)
        if raw is None or sfreq <= 0: return {}
        # TODO: filter -> raw_out
        return {"raw": raw}  # placeholder
```
Reload the palette (or re-run RBCIAD).
