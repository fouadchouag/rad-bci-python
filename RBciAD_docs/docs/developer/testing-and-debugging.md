# Testing & Debugging

- **Smoke test**: drop the node in an empty graph, connect minimal inputs, toggle parameters, check outputs update.
- **I/O shape**: ensure `ndarray_2d` is `[ch x samples]` (transpose if needed).
- **Nyquist guard**: with `sfreq`, verify `low/high` clamp correctly.
- **Logging**: use `print()` for subprocesses (stderr is captured in error messages).
- **Perf**: if you stream large arrays, prefer in-process Python or persistent `--stdio` to avoid repeated JSON (the wrapper caches `.tolist()` for `raw`).

**Unit tests (optional)**: write small tests calling your `process(payload)` (Python) or CLI with fixed input files.
