# Troubleshooting

Common issues and how to fix them.

## Installation & Launch

### `Rbciad` command not found

1. Make sure your virtual environment is active:
   ```bash
   # Windows
   .venv\Scripts\activate
   # macOS / Linux
   source .venv/bin/activate
   ```
2. Ensure you installed in developer mode: `pip install -e .`
3. On Windows, verify `.venv\Scripts` is on your PATH
4. Fallback: run `python main.py` from the repo root

### Import errors (`ModuleNotFoundError`)

- Install missing dependencies: `pip install -r requirements.txt`
- `mne` and `pyriemann` are optional but required for EEG/BCI workflows
- If using a specific node, check its help (`Ctrl+F1`) for required packages

### App crashes on startup

- Update PyQt5: `pip install --upgrade PyQt5`
- On Linux, ensure `libxcb-xinerama0` is installed: `sudo apt install libxcb-xinerama0`
- Check the console for error messages

## Connections

### "Connection refused" when linking nodes

- Pins must have the **same family** (data type). Hover over a pin to see its family.
- Each input accepts **only one** cable. Disconnect the existing one first.
- Common families: `raw`, `segment`, `sfreq`, `ch_names`, `features`, `cov`, `model`

### Data not flowing between nodes

- Check that all nodes are connected in the correct order
- Verify that upstream nodes have data loaded (e.g., file opened in Reader)
- Look at the console for error messages from the nodes

## Visualization

### Blank plot / no output

- Check that the input data is not all zeros or NaN
- Verify `sfreq` (sampling frequency) is set correctly
- Try `segment` output instead of `raw`
- For MNE-based nodes, ensure channels are picked correctly (EEG only)

### Slow UI / low FPS

- Enable **display decimation** in the visualizer node
- Use `segment` output mode instead of `raw`
- Reduce the number of visible channels
- Close other visualizer windows

### Visual artifacts (ghosting, trails)

- The app uses raster rendering. On Windows, reduce scene refresh rates or update graphics drivers
- Try restarting the app

## Filtering

### Filter error / unstable filter

- Increase the filter order or length
- Relax the transition bandwidth
- Ensure the sampling frequency is sufficient for the requested filter parameters
- For FIR filters: the filter length must be odd and less than the signal length

### Filter removes the signal of interest

- Check that the passband matches your frequency band of interest (e.g., 8–30 Hz for Motor Imagery)
- A notch filter at 50/60 Hz should only remove power line noise, not neural signals
- Use the Quick Help (`Ctrl+F1`) on the filter node to see parameter descriptions

## LSL (Live Streaming)

### LSL stream not found

- Install the LSL runtime: `pip install pylsl`
- Verify the stream exists using LSL Browser or `pylsl.resolve_streams()`
- Check that the stream name in the LSLInlet node matches the broadcaster

### High latency / dropped samples

- Reduce the segment length (smaller chunks = lower latency)
- Ensure the LSL source is running at the expected sampling rate
- Check CPU usage — other processes may be competing for resources

## BCI Pipeline

### Training fails / NaN accuracy

- Ensure epochs are extracted correctly (check epoch length and overlap)
- Verify that class labels are correct and balanced
- Check for NaN or infinite values in the feature matrix
- Try a simpler classifier (Logistic Regression) as a baseline

### Poor classification accuracy

- Verify your preprocessing (filter band, re-referencing)
- Check for data leakage (training and test data must be separated)
- Increase the number of trials per class
- Try different feature extraction methods (bandpower, CSP, Riemannian)
- Use cross-validation to get a reliable accuracy estimate

### Real-time inference too slow

- Ensure the pipeline uses `transform` mode (not `fit`) for preprocessing and feature nodes
- Check that covariance estimation uses OAS shrinkage (faster than Ledoit-Wolf)
- Target: <50ms per trial for real-time BCI

## Metrics & Performance

### Metrics not recording

- Press **F9** to start/stop metrics recording
- Metrics are saved to the `runs/` directory
- Analyze with: `python utils/metrics_eval.py runs --outdir metrics_results`

### Export fails (PNG/PDF/SVG)

- Use `Ctrl+E` for quick export
- Ensure the canvas has visible nodes (empty canvas = empty export)
- For PDF: check that `PyQt5.QtPdf` is available

## Still Stuck?

1. Check the **console output** for error messages
2. Use **Quick Help** (`Ctrl+F1`) on the problematic node
3. Open the **full documentation** (`F1`)
4. Report issues at [github.com/fouadchouag/rad-bci-python/issues](https://github.com/fouadchouag/rad-bci-python/issues)
