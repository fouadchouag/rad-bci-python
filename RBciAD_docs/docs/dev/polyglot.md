# Polyglot Plugins

RBciAD supports two recommended paths for polyglot extensions.

## Option A — Native In‑Process (low latency, reviewer‑preferred)
**When:** You need C/C++/Rust performance but want Python‑class UX (no extra processes).

### C++ with pybind11 (sketch)
```cpp
// bandpower.cpp
#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>
namespace py = pybind11;

float bandpower(const py::array_t<float>& x, float sfreq) {
    // TODO: compute and return a float
    return 0.0f;
}

PYBIND11_MODULE(rbciad_native, m) {
    m.def("bandpower", &bandpower, "Compute bandpower of a segment");
}
```

Build a wheel (via `pyproject.toml` + `cibuildwheel`) and install. Then in your plugin:

```python
from core.node_base import BasePlugin
from rx.subject import BehaviorSubject
from rbciad_native import bandpower

class BandpowerNode(BasePlugin):
    category = "Processing"
    display_name = "Bandpower (Native)"

    def setup(self):
        self.inputs = {"segment": BehaviorSubject(None), "sfreq": BehaviorSubject(None)}
        self.outputs = {"alpha": BehaviorSubject(None)}

    def execute(self, in_data: dict, **kwargs):
        seg = in_data.get("segment"); sf = in_data.get("sfreq")
        if seg is None or sf is None: return None
        val = bandpower(seg, float(sf))
        self.outputs["alpha"].on_next(val)
        return val
```

### Rust with pyo3/maturin (sketch)
```rust
use pyo3::prelude::*;
use numpy::{PyArray2};

#[pyfunction]
fn bandpower(x: &PyArray2<f32>, sfreq: f32) -> PyResult<f32> {
    // TODO
    Ok(0.0)
}

#[pymodule]
fn rbciad_native(_py: Python, m: &PyModule) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(bandpower, m)?)?;
    Ok(())
}
```

## Option B — Subprocess Wrapper (robust, slightly higher latency)
**When:** You need isolation or must call external tools (Node.js, R, .exe).

### JSON I/O Contract
- **Input file:** `temp_io/input_<node>_<id>.json`
- **Output file:** `temp_io/output_<node>_<id>.json`
- **Error shape:** `{ "error": {"type": "...", "message": "..."} }`

**Example input:**
```json
{
  "segment": [[0.1, 0.2, 0.0], [0.0, -0.1, 0.3]],
  "sfreq": 256.0
}
```

### Python wrapper (BasePlugin) — build command by extension
```python
import json, subprocess, sys, os
from core.node_base import BasePlugin
from rx.subject import BehaviorSubject

class ExternalBandpower(BasePlugin):
    category = "Polyglot"
    display_name = "Bandpower (External)"
    executable = "external_scripts/bandpower.js"  # could be .js, .sh, .exe, .r

    def setup(self):
        self.inputs = {"segment": BehaviorSubject(None), "sfreq": BehaviorSubject(None)}
        self.outputs = {"alpha": BehaviorSubject(None)}

    def _build_command(self, exe):
        ext = os.path.splitext(exe)[1].lower()
        if ext == ".js": return ["node", exe]
        if ext == ".sh": return ["bash", exe]
        if ext == ".r":  return ["Rscript", exe]
        return [exe]  # .exe or native binary

    def execute(self, in_data: dict, **kwargs):
        seg, sf = in_data.get("segment"), in_data.get("sfreq")
        if seg is None or sf is None: return None

        work = "temp_io"; os.makedirs(work, exist_ok=True)
        nid = getattr(self, "_id", "node")
        fi = os.path.join(work, f"input_bandpower_{nid}.json")
        fo = os.path.join(work, f"output_bandpower_{nid}.json")

        with open(fi, "w", encoding="utf-8") as f:
            json.dump({"segment": seg, "sfreq": sf}, f)

        cmd = self._build_command(self.executable) + [fi, fo]
        try:
            subprocess.check_call(cmd, timeout=10)
        except Exception as e:
            self.logger.error(f"External failed: {e}")
            return None

        if not os.path.exists(fo): return None
        with open(fo, "r", encoding="utf-8") as f:
            out = json.load(f)
        if "error" in out: 
            self.logger.error(out["error"])
            return None

        val = out.get("alpha")
        self.outputs["alpha"].on_next(val)
        return val
```

### Example Node.js script (`bandpower.js`) — sketch
```javascript
// node bandpower.js input.json output.json
const fs = require('fs');
const [,, fin, fout] = process.argv;
const data = JSON.parse(fs.readFileSync(fin, 'utf-8'));
const seg = data.segment; const sf = data.sfreq;
// TODO: compute alpha bandpower
fs.writeFileSync(fout, JSON.stringify({ alpha: 0.0 }));
```

## Choosing a path
- Use **native in‑process** for low latency and seamless UX.
- Use **subprocess** for isolation, crash‑safety, or ecosystems like Node/R.
