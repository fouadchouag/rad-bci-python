# Developer Guide (RBCIAD)

Welcome! This section explains how to add **polyglot nodes** and customize RBCIAD quickly.

**You only need this to get started:**
1. **Low-code path (recommended):** create a node from the GUI and let it generate the wrapper + help.
2. **Polyglot script contract:** if your logic is not Python, implement the `--stdio` or `--in/--out` JSON contract (templates below).
3. **Help block:** make sure your plugin class has `help = { ... }`. Low-code auto-fills it.
4. **Test:** run in the graph, verify I/O and parameters, F1/Shift+F1/Ctrl+F1 help.

If you prefer a deep dive, check the pages in this section.
