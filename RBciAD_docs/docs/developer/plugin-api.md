# Plugin / Node API

```python
class BasePlugin:
  def setup(self): ...
  def build_widget(self): ...      # optional: returns QWidget for parameters
  def execute(self, **kwargs): ...  # compute; return dict mapping outputs
  def teardown(self): ...           # optional cleanup
```

- **Pins**: set in `setup()`  
  ```python
  from rx.subject import BehaviorSubject
  self.inputs["raw"] = BehaviorSubject(None)
  self.outputs["raw"] = BehaviorSubject(None)
  ```
- **Emit** results: `self.outputs["raw"].on_next(value)` if you push from inside long tasks.
- **Parameters UI**: wrappers declare `PARAM_DEFS` which auto-build a form (float/int/bool/enum/str).
- **Execution modes**: `auto` (default), `inprocess` (Python `.py` with `process(payload)`), `subprocess` (`--stdio` preferred, fallback `--in/--out`).

**Definition of Done**
- `help.summary` and `help.usage` not empty.
- Inputs/Outputs correct and stable.
- Parameters documented (`type`, `default`, `unit`, `desc`).
- Works with **Ctrl+F1** Quick Help and **Shift+F1** Node Page.
