# Help System (in-app)

- **F1**: opens full docs viewer (User + Developer).
- **Shift+F1**: opens the selected node's page in *Nodes Catalog*.
- **Ctrl+F1** or **"?" badge**: opens **Quick Help** using the node's `help` dict.

## `help` dict (class attribute)
```python
help = {
  "summary": "One-line description.",
  "inputs": {"raw": "2D float [ch x samples]", "sfreq": "float (Hz)"},
  "outputs": {"raw": "2D float [ch x samples]"},
  "parameters": [{"name":"low","type":"float","default":1.0,"unit":"Hz","desc":"High-pass"}],
  "usage": "Place after acquisition; keep low<high<Nyquist.",
  "gotchas": ["sfreq must be > 0"]
}
```

**Low-code autofill:** After creating a node, a small dialog asks for **Summary** and **Usage** and injects a complete `help` block automatically.
