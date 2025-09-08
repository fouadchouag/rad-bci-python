# Nodes Catalog Generator

This tool scans your plugin wrappers (`plugins/` and `custom_plugins/`) and generates **user documentation** from each node's `help` dict.

## Files created
- `docs/user/nodes/index.md` — grouped by category with links to each node
- `docs/user/nodes/<slug>.md` — one page per node
- `docs/user/nodes.md` — small trampoline page

## Run
```bash
# from your project root
python tools/generate_node_catalog.py
```
If some modules do heavy work at import time, guard it with:
```python
import os
if os.getenv("DOCS_BUILD") == "1":
    # skip heavy init
    pass
```

## MkDocs navigation
Add this to your `mkdocs.yml` (under `nav:`):
```yaml
- User Guide:
  - Overview: user/index.md
  - Nodes Catalog: user/nodes/index.md
```

## In-app
- **Shift+F1** (Context Help) can open a node page by its `display_name`.
- Quick Help (Ctrl+F1 / “?” badge) is rendered from the same `help` dict.
